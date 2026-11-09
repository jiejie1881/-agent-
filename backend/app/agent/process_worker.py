"""Private worker entry point. First read is a bounded stdin gate, not a CLI tool."""
import json
import os
import signal
import sys


def main():
    if os.name != 'nt':
        # Install before reading the gate. A dead supervisor must not leave a
        # worker tree. Linux-specific facility; fail closed elsewhere.
        import ctypes
        parent = os.getppid()
        def parent_died(*_):
            os.killpg(os.getpgrp(), signal.SIGKILL)
        signal.signal(signal.SIGTERM, parent_died)
        if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0 or os.getppid() != parent:
            return 70
    raw = sys.stdin.buffer.readline(1024 * 1024 + 2)
    request = json.loads(raw)
    if len(raw) > 1024 * 1024 + 1 or request.get('version') != 1:
        return 71
    # Paths/connection parameters are server-generated, never model arguments.
    sys.path[:0] = [request['backend'], *request['package_paths']]
    response = dict(version=1, request_id=request['request_id'])
    try:
        import asyncio
        os.environ.update(DATABASE_URL=request['database_url'], APP_ENVIRONMENT='test',
                          MODEL_BUDGET_ENABLED='false', LANGSMITH_TRACING='false',
                          LANGCHAIN_TRACING_V2='false')
        from app.core import config
        # Required by the shared settings schema; this private read worker
        # neither issues nor verifies JWTs and receives no signing credential.
        settings = config.Settings(_env_file=None, jwt_secret_key='readonly-worker-no-jwt-signing-capability')
        config.get_settings = lambda: settings
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import Session
        from app.agent.tool_capabilities import PROCESS_READ_TOOLS
        from app.agent.tool_registry import AgentToolRegistry, DEFAULT_TOOL_DEFINITIONS
        from app.agent.business_task_tools import EXTRA_DEFINITIONS, build_business_task_executors
        from app.agent.read_only_tools import build_read_only_tool_executors
        from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry
        from app.services.delivery_demand_service import DeliveryDemandService
        from app.services.dispatch_plan_service import DispatchPlanService
        from app.services.vehicle_attendance_service import VehicleAttendanceService
        from app.models.user import User
        from app.domain.permissions import has_permission
        import app.models  # noqa: F401 - register relationships, no service startup
        from sqlalchemy.engine import make_url
        url = make_url(request['database_url'])
        if url.get_backend_name() != 'mysql' or request['tool'] not in PROCESS_READ_TOOLS:
            raise ValueError('Unsupported process boundary')
        engine = create_engine(url, pool_pre_ping=False, connect_args={'connect_timeout': 5, 'read_timeout': 30})
        @event.listens_for(engine, 'connect')
        def read_only(connection, _):
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
                cursor.execute('SET SESSION MAX_EXECUTION_TIME=30000')
        try:
            with Session(engine, autoflush=False) as session:
                registry = AgentToolRegistry(tuple(d for d in (*DEFAULT_TOOL_DEFINITIONS, *EXTRA_DEFINITIONS)
                                                   if d.name in PROCESS_READ_TOOLS))
                definition = registry.get(request['tool'])
                registry.validate_arguments(request['tool'], request['arguments'])
                actor = session.get(User, request['actor_id'])
                if actor is None or not actor.is_active or not has_permission(actor.role, definition.required_permission):
                    raise PermissionError('Actor not authorized')
                executors = AgentToolExecutorRegistry([
                    *build_read_only_tool_executors(delivery_demand_service=DeliveryDemandService(session),
                        vehicle_attendance_service=VehicleAttendanceService(session),
                        dispatch_plan_service=DispatchPlanService(session)),
                    *build_business_task_executors(session)], definition_registry=registry)
                result = asyncio.run(executors.execute(request['tool'], request['arguments'],
                    AgentToolContext(current_user=actor, conversation_id=request.get('conversation_id'))))
                response.update(ok=True, result=result.model_dump(mode='json'))
                session.rollback()
        finally:
            engine.dispose()
    except Exception as exc:
        # Do not send SQL, connection strings, document text or exception repr.
        response.update(ok=False, code=type(exc).__name__)
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf8')
    if len(encoded) > 1024 * 1024:
        return 72
    sys.stdout.buffer.write(encoded); sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())

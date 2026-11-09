"""Create and serve a fresh, synthetic Step 9.5 shadow acceptance database."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import json
import os
import secrets
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
AREA = ROOT / ".validation-v11" / "step9-5-local"
DAYS = (date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12))


def prepare():
    folder = AREA / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True)
    database = folder / "demo.sqlite3"
    credentials = {"username": "step95-admin", "password": secrets.token_urlsafe(20),
                   "jwt_secret": secrets.token_urlsafe(48)}
    os.environ.update(DATABASE_URL="sqlite+pysqlite:///" + database.as_posix(),
                      JWT_SECRET_KEY=credentials["jwt_secret"])
    import app.models  # noqa: F401
    from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod, UserRole, VehicleTypeCode
    from app.infrastructure.database.base import Base
    from app.infrastructure.database.session import SessionLocal, engine
    from app.models.delivery_demand import DeliveryDemand
    from app.models.driver_scheduling import DriverAttendance
    from app.models.route import Route, RouteTerrainConfig
    from app.models.store import Store, StoreRoute
    from app.models.terrain import Terrain
    from app.models.user import User
    from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
    from app.models.vehicle_attendance import VehicleAttendance
    from app.repositories.user_repository import UserRepository
    from app.services.auth_service import AuthService

    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        admin = AuthService(session).create_user(credentials["username"], credentials["password"], UserRole.ADMIN)
        normal = Terrain(code="S95-N", name="普通演示地形")
        strict = Terrain(code="S95-S", name="限制演示地形")
        route_normal = Route(code="S95-RN", name="隔离演示常规线")
        route_strict = Route(code="S95-RS", name="隔离演示限制线")
        small = VehicleType(code=VehicleTypeCode.SMALL_VAN, name="演示小型车", min_load=100, max_load=500, is_active=True)
        big = VehicleType(code=VehicleTypeCode.BIG_VAN, name="演示合规替代车", min_load=100, max_load=500, is_active=True)
        driver1 = User(username="step95-driver-1", password_hash="unusable-test-only-hash", role=UserRole.DRIVER, is_active=True)
        driver2 = User(username="step95-driver-2", password_hash="unusable-test-only-hash", role=UserRole.DRIVER, is_active=True)
        stores = [Store(code=f"S95-S{i}", name=f"隔离演示门店{i}") for i in range(1, 4)]
        session.add_all([normal, strict, route_normal, route_strict, small, big, driver1, driver2, *stores])
        session.flush()
        vehicle1 = Vehicle(code="S95-V1", plate_number="湘A95001", vehicle_type_id=small.id,
                           driver_user_id=driver1.id, is_active=True)
        vehicle2 = Vehicle(code="S95-V2", plate_number="湘A95002", vehicle_type_id=big.id,
                           driver_user_id=driver2.id, is_active=True)
        session.add_all([vehicle1, vehicle2])
        session.flush()
        session.add_all([
            RouteTerrainConfig(route_id=route_normal.id, terrain_id=normal.id, effective_date=DAYS[0]),
            RouteTerrainConfig(route_id=route_strict.id, terrain_id=strict.id, effective_date=DAYS[0]),
            VehicleTypeTerrainPermission(vehicle_type_id=small.id, terrain_id=normal.id),
            VehicleTypeTerrainPermission(vehicle_type_id=big.id, terrain_id=normal.id),
            VehicleTypeTerrainPermission(vehicle_type_id=big.id, terrain_id=strict.id),
        ])
        for i, day in enumerate(DAYS):
            route = route_strict if i == 2 else route_normal
            session.add(StoreRoute(store_id=stores[i].id, route_id=route.id))
            session.add(DeliveryDemand(date=day, store_id=stores[i].id, period=DeliveryPeriod.MORNING,
                                       quantity=600 if i == 1 else 200, status=DeliveryDemandStatus.PENDING))
            for vehicle, driver in ((vehicle1, driver1), (vehicle2, driver2)):
                session.add(VehicleAttendance(date=day, vehicle_id=vehicle.id, available=True))
                session.add(DriverAttendance(driver_id=driver.id, date=day, period="MORNING",
                                             available=True, actor_id=admin.id))
        session.commit()
    (folder / "credentials.json").write_text(json.dumps(credentials), encoding="utf-8")
    (folder / "step9-5-marker.json").write_text(json.dumps({"database": str(database.resolve()),
        "synthetic": True, "days": [d.isoformat() for d in DAYS]}), encoding="utf-8")
    print(json.dumps({"folder": str(folder), "database": str(database),
                      "days": [d.isoformat() for d in DAYS], "synthetic": True}, ensure_ascii=False))


def serve(folder, port, real=False, fault=None):
    folder = Path(folder).resolve()
    if not folder.is_relative_to(AREA.resolve()) or folder.is_symlink():
        raise ValueError("Only a Step 9.5 isolated folder is allowed")
    marker = json.loads((folder / "step9-5-marker.json").read_text(encoding="utf-8"))
    database = (folder / "demo.sqlite3").resolve()
    if marker != {"database": str(database), "synthetic": True, "days": [d.isoformat() for d in DAYS]} or not database.is_file():
        raise ValueError("Step 9.5 database attestation failed")
    credentials = json.loads((folder / "credentials.json").read_text(encoding="utf-8"))
    os.environ.update(DATABASE_URL="sqlite+pysqlite:///" + database.as_posix(),
                      JWT_SECRET_KEY=credentials["jwt_secret"],
                      AGENT_DISPATCH_SHADOW_ENABLED="true", LOCAL_DISPATCH_DEMO_ENABLED="false",
                      AGENT_CHECKPOINT_PATH=str(folder / "checkpoints.sqlite3"),
                      UPLOAD_ROOT=str(folder / "uploads"))
    # Offline mode has no model credentials. A click cannot send externally.
    for name in ("AGENT_PROVIDER", "AGENT_MODEL", "AGENT_API_KEY", "AGENT_BASE_URL"):
        os.environ[name] = ""
    if fault:
        if real:
            raise ValueError("Fault injection cannot use real model credentials")
        from sqlalchemy.orm import Session

        from app.agent.dispatch_workflow import ShadowDispatchWorkflow
        from app.agent.exceptions import AgentModelTimeoutError
        from app.agent.model_types import AgentModelResponse
        from app.api.dependencies import DbSession
        from app.api.shadow_dispatch_dependencies import get_shadow_dispatch
        from app.core.config import get_settings
        from app.main import app
        from app.services.dispatch_context_service import DispatchContextService

        class FaultModel:
            async def chat(self, messages, tools):
                if fault == "timeout":
                    raise AgentModelTimeoutError(phase="READ")
                return AgentModelResponse(content="")

        def fault_shadow(db: DbSession):
            bind = db.get_bind()

            def load(day):
                with Session(bind=bind, autoflush=False) as session:
                    return DispatchContextService(session).load(day)

            return ShadowDispatchWorkflow(FaultModel(), load, get_settings())

        app.dependency_overrides[get_shadow_dispatch] = fault_shadow
        print(json.dumps({"mode": "offline-fault-injection", "fault": fault}), flush=True)
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port)
        return
    if real:
        import asyncio
        from decimal import Decimal
        from urllib.parse import urlsplit

        from dotenv import dotenv_values
        from sqlalchemy.orm import Session

        from app.agent.dispatch_workflow import ShadowDispatchWorkflow
        from app.agent.langchain_client import LangChainModelClient
        from app.api.dependencies import DbSession
        from app.api.shadow_dispatch_dependencies import get_shadow_dispatch
        from app.core.config import get_settings
        from app.services.dispatch_context_service import DispatchContextService
        from tests.legacy_support.step9_5_budget import (
            CAP, INPUT_RATE, MAX_CALLS, MAX_TOKENS, OUTPUT_RATE, RecordingBudgetClient,
        )

        rows = [json.loads(line) for line in (folder / "real-model-receipt.jsonl").read_text(encoding="utf-8").splitlines()]
        if rows[-1].get("overall") != "PASS" or rows[0]["metadata"].get("cost_cap_cny") != str(CAP):
            raise ValueError("A successful authorized Step 9.5 receipt is required")
        config = dotenv_values(ROOT / ".env")
        endpoint = urlsplit(config.get("AGENT_BASE_URL") or "")
        if (endpoint.scheme != "https" or endpoint.hostname != "api.siliconflow.cn"
                or config.get("AGENT_MODEL") != "deepseek-ai/DeepSeek-V4-Flash"
                or not config.get("AGENT_API_KEY")
                or Decimal(config.get("AGENT_DISPATCH_SHADOW_MAX_COST") or "0") > CAP
                or Decimal(config.get("AGENT_DISPATCH_SHADOW_INPUT_PRICE_PER_MILLION") or "-1") != INPUT_RATE
                or Decimal(config.get("AGENT_DISPATCH_SHADOW_OUTPUT_PRICE_PER_MILLION") or "-1") != OUTPUT_RATE
                or config.get("AGENT_DISPATCH_SHADOW_COST_CURRENCY") != "CNY"):
            raise ValueError("Model target or cost cap differs from the authorized receipt")
        for name in ("AGENT_PROVIDER", "AGENT_MODEL", "AGENT_API_KEY", "AGENT_BASE_URL",
                     "AGENT_DISPATCH_SHADOW_MAX_COST", "AGENT_DISPATCH_SHADOW_INPUT_PRICE_PER_MILLION",
                     "AGENT_DISPATCH_SHADOW_OUTPUT_PRICE_PER_MILLION", "AGENT_DISPATCH_SHADOW_COST_CURRENCY"):
            os.environ[name] = config[name]
        os.environ.update(AGENT_TIMEOUT="60", AGENT_DISPATCH_SHADOW_TIMEOUT="120",
                          AGENT_DISPATCH_SHADOW_OUTPUT_TOKENS="1536",
                          AGENT_DISPATCH_SHADOW_TOKEN_BUDGET=str(MAX_TOKENS))
        get_settings.cache_clear()
        settings = get_settings()
        if settings.agent_dispatch_shadow_max_cost is None or settings.agent_dispatch_shadow_max_cost > CAP:
            raise ValueError("Per-request cap is missing")
        ledger_file = folder / "browser-ledger.json"
        if ledger_file.exists():
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
            ledger["estimated_cost"] = Decimal(ledger["estimated_cost"])
        else:
            ledger = rows[-1]["ledger"]
            ledger["estimated_cost"] = Decimal(ledger["estimated_cost"])
        if (ledger["calls"] > MAX_CALLS or ledger["charged_tokens"] > MAX_TOKENS
                or Decimal(ledger["charged_tokens"]) * Decimal(9) / 1000000 > CAP):
            raise ValueError("Shared acceptance budget is exhausted")

        def persist():
            temporary = ledger_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(ledger, default=str), encoding="utf-8")
            os.replace(temporary, ledger_file)

        lock = asyncio.Lock()

        class PersistingTransport:
            def __init__(self):
                self.client = LangChainModelClient(settings, max_output_tokens=1536)

            async def chat(self, messages, tools):
                # BudgetClient has reserved tokens and calls before reaching here.
                persist()
                return await self.client.chat(messages, tools)

        class BrowserBudgetClient(RecordingBudgetClient):
            async def chat(self, messages, tools):
                async with lock:
                    try:
                        return await super().chat(messages, tools)
                    finally:
                        persist()

        from app.main import app
        from fastapi.responses import JSONResponse

        @app.middleware("http")
        async def only_shadow_model_route(request, call_next):
            path = request.url.path.rstrip("/")
            if path.startswith("/api/v1/agent/") and path not in {
                "/api/v1/agent/dispatch/shadow", "/api/v1/agent/dispatch/shadow/context",
            }:
                return JSONResponse(status_code=403, content={"code": "STEP95_ROUTE_DISABLED",
                    "message": "本地真实模型验收仅开放业务影子派车"})
            return await call_next(request)

        def controlled_shadow(db: DbSession):
            bind = db.get_bind()

            def load(day):
                with Session(bind=bind, autoflush=False) as session:
                    return DispatchContextService(session).load(day)

            client = BrowserBudgetClient(settings, ledger, max_output_tokens=1536,
                                         inner=PersistingTransport())
            return ShadowDispatchWorkflow(client, load, settings)

        app.dependency_overrides[get_shadow_dispatch] = controlled_shadow
        print(json.dumps({"mode": "authorized-real", "calls_used": ledger["calls"],
                          "reserved_upper_cny": str(Decimal(ledger["charged_tokens"]) * Decimal(9) / 1000000),
                          "cost_cap_cny": str(CAP)}), flush=True)
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port)
        return
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    server = sub.add_parser("serve")
    server.add_argument("folder")
    server.add_argument("--port", type=int, default=8089)
    server.add_argument("--real", action="store_true", help="Resume the authorized shared model budget")
    server.add_argument("--fault", choices=("timeout", "empty"), help="Offline browser error acceptance")
    args = parser.parse_args()
    prepare() if args.command == "prepare" else serve(args.folder, args.port, args.real, args.fault)


if __name__ == "__main__":
    main()

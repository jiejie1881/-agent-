"""Bounded process-local HTTP metrics and metadata-only JSON request logs."""
import json
import logging
import threading
import time
from collections import defaultdict
from uuid import uuid4

logger = logging.getLogger('logistics.http')
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class HttpTelemetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = defaultdict(lambda: {'count': 0, 'duration_ms_sum': 0.0})

    def record(self, method, route, status, elapsed):
        method = method if method in {'GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'} else 'OTHER'
        with self.lock:
            row = self.rows[(method, route, f'{status // 100}xx')]
            row['count'] += 1
            row['duration_ms_sum'] += elapsed

    def snapshot(self):
        with self.lock:
            return {'scope': 'single_process_since_start', 'requests': [
                {'method': key[0], 'route': key[1], 'status_class': key[2], **value}
                for key, value in sorted(self.rows.items())]}


def install_telemetry(app):
    metrics = HttpTelemetry()
    app.state.http_metrics = metrics

    @app.middleware('http')
    async def request_metrics(request, call_next):
        started = time.perf_counter()
        request_id = uuid4().hex  # Never trust or log an arbitrary client header.
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers['X-Request-ID'] = request_id
            return response
        finally:
            route = getattr(request.scope.get('route'), 'path', 'UNMATCHED')
            elapsed = (time.perf_counter() - started) * 1000
            metrics.record(request.method, route, status, elapsed)
            logger.info(json.dumps({'event': 'http_request', 'request_id': request_id,
                                    'method': request.method, 'route': route,
                                    'status': status, 'duration_ms': round(elapsed, 3)}))

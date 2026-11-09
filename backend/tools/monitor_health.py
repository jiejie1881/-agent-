"""Single bounded health probe. JSON stdout + nonzero exit feed an external monitor."""
import argparse
import json
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx


def probe(url):
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Health target must not contain credentials, query or fragment')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1','localhost','::1'}):
        raise ValueError('Non-loopback health checks require HTTPS')
    try:
        response = httpx.get(url, timeout=5, trust_env=False, follow_redirects=False)
        body = response.json()
        ready = response.status_code == 200 and isinstance(body, dict) and body.get('status') == 'ready'
        status = response.status_code
    except (httpx.HTTPError, ValueError):
        ready, status = False, None
    return {'event':'health_ok' if ready else 'health_alert','checked_at':datetime.now(UTC).isoformat(),
            'status_code':status,'ready':ready,'notification':'stdout_only'}, 0 if ready else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    result, code = probe(parser.parse_args().url)
    print(json.dumps(result))
    raise SystemExit(code)

"""Read-only DNS/TCP/TLS diagnosis; sends no API key or model request."""
import json
import os
from pathlib import Path
import socket
import ssl
from urllib.parse import urlsplit
from app.core.config import Settings

root = Path(__file__).resolve().parents[2]
settings = Settings(_env_file=root / '.env')
url = urlsplit(settings.agent_base_url or '')
result = {'provider': settings.agent_provider, 'model': settings.agent_model,
    'credential_present': bool(settings.agent_api_key), 'hostname': url.hostname,
    'path': url.path, 'api_path_duplicated': url.path.rstrip('/').endswith('/chat/completions'),
    'proxy_environment_present': any(os.environ.get(k) for k in ['HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy']),
    'model_request': 'REAL_MODEL_NOT_RUN', 'budget_reset': False}
try:
    result['dns_address_count'] = len(socket.getaddrinfo(url.hostname, url.port or 443))
    with socket.create_connection((url.hostname, url.port or 443), timeout=5) as raw:
        result['tcp'] = 'PASS'
        with ssl.create_default_context().wrap_socket(raw, server_hostname=url.hostname) as tls:
            result['tls'] = 'PASS'
            result['tls_version'] = tls.version()
except Exception as exc:
    result['connection_error_type'] = type(exc).__name__
print(json.dumps(result, ensure_ascii=False, indent=2))

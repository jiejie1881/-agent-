"""Loopback-only isolated SQLite demo. Does not read production database settings."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import json
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--enable-real", action="store_true", help="Enable explicit per-request model consent; never sends on startup")
    parser.add_argument("--enable-business-shadow", action="store_true", help="Enable real-business read-only shadow mode in this isolated local demo")
    args = parser.parse_args()
    if args.enable_business_shadow and not args.enable_real:
        parser.error("--enable-business-shadow requires --enable-real and per-request consent")
    root = Path(__file__).resolve().parents[3]
    folder = root / ".validation-v11" / "step9-local"
    folder.mkdir(parents=True, exist_ok=True)
    credential_file = folder / "credentials.json"
    if credential_file.exists():
        credentials = json.loads(credential_file.read_text(encoding="utf-8"))
    else:
        credentials = {"username": "demo-admin", "password": secrets.token_urlsafe(18),
                       "jwt_secret": secrets.token_urlsafe(48)}
        credential_file.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    os.environ.update(DATABASE_URL="sqlite+pysqlite:///" + (folder / "demo.sqlite3").as_posix(),
                      JWT_SECRET_KEY=credentials["jwt_secret"], LOCAL_DISPATCH_DEMO_ENABLED="true",
                      LOCAL_DISPATCH_DEMO_REAL_ENABLED=str(args.enable_real).lower(),
                      AGENT_DISPATCH_SHADOW_ENABLED=str(args.enable_business_shadow).lower(),
                      AGENT_CHECKPOINT_PATH=str(folder / "checkpoints.sqlite3"),
                      UPLOAD_ROOT=str(folder / "uploads"))
    # Offline startup must not inherit configured external model credentials.
    for name in ("AGENT_PROVIDER", "AGENT_MODEL", "AGENT_API_KEY", "AGENT_BASE_URL"):
        os.environ[name] = ""
    if args.enable_real:
        # OS values above intentionally mask credentials; explicitly parse only
        # the model configuration from a user-selected root env file below.
        from dotenv import dotenv_values
        env = dotenv_values(root / ".env")
        if args.enable_business_shadow:
            required = ("AGENT_PROVIDER", "AGENT_MODEL", "AGENT_API_KEY", "AGENT_BASE_URL",
                        "AGENT_DISPATCH_SHADOW_MAX_COST", "AGENT_DISPATCH_SHADOW_INPUT_PRICE_PER_MILLION",
                        "AGENT_DISPATCH_SHADOW_OUTPUT_PRICE_PER_MILLION", "AGENT_DISPATCH_SHADOW_COST_CURRENCY")
            missing = [name for name in required if not env.get(name)]
            if missing:
                parser.error("业务影子模式缺少本地模型及费用配置：" + ", ".join(missing))
        for name in ("AGENT_PROVIDER", "AGENT_MODEL", "AGENT_API_KEY", "AGENT_BASE_URL",
                     "AGENT_DISPATCH_SHADOW_MAX_COST", "AGENT_DISPATCH_SHADOW_INPUT_PRICE_PER_MILLION",
                     "AGENT_DISPATCH_SHADOW_OUTPUT_PRICE_PER_MILLION", "AGENT_DISPATCH_SHADOW_COST_CURRENCY"):
            if env.get(name):
                os.environ[name] = env[name]
    os.environ.update(AGENT_TIMEOUT="60", AGENT_DISPATCH_SHADOW_TIMEOUT="120",
                      AGENT_DISPATCH_SHADOW_OUTPUT_TOKENS="1536", AGENT_DISPATCH_SHADOW_TOKEN_BUDGET="120000")
    import app.models  # noqa: F401
    from app.domain.enums import UserRole
    from app.infrastructure.database.base import Base
    from app.infrastructure.database.session import SessionLocal, engine
    from app.repositories.user_repository import UserRepository
    from app.services.auth_service import AuthService
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if UserRepository(session).get_by_username(credentials["username"]) is None:
            AuthService(session).create_user(credentials["username"], credentials["password"], UserRole.ADMIN)
    print(f"Isolated local demo: http://127.0.0.1:{args.port}; credentials: {credential_file}")
    print("No production database / no automatic model requests / no Docker startup")
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

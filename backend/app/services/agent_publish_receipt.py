"""Human publication receipt, bound to one persisted Agent draft and actor."""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

from app.domain.exceptions import PermissionDeniedError
from app.services.agent_dispatch_receipt import _key


def issue_publish_receipt(plan, actor, snapshot: str, digest: str, settings,
                          *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    payload = {
        "purpose": "AGENT_CONFIRM_PUBLISH", "v": 1,
        "key_version": settings.agent_draft_receipt_key_version,
        "nonce": secrets.token_hex(24), "plan_id": plan.id,
        "delivery_date": plan.delivery_date.isoformat(), "version": plan.version,
        "user_id": actor.id, "token_version": actor.token_version,
        "snapshot_version": snapshot, "plan_sha256": digest,
        "issued_at": int(now.timestamp()),
        "expires_at": int((now + timedelta(seconds=settings.agent_publish_receipt_ttl_seconds)).timestamp()),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(_key(settings), raw, hashlib.sha256).digest()
    return ".".join(base64.urlsafe_b64encode(part).decode().rstrip("=")
                    for part in (raw, signature))


def verify_publish_receipt(token: str, plan, actor, snapshot: str, digest: str,
                           settings, *, now: datetime | None = None) -> dict:
    try:
        if len(token) > 2048:
            raise ValueError()
        pieces = token.split(".")
        if len(pieces) != 2:
            raise ValueError()
        raw, signature = (base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)) for p in pieces)
        expected = hmac.new(_key(settings), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(raw)
        now = now or datetime.now(UTC)
        if (payload.get("purpose") != "AGENT_CONFIRM_PUBLISH" or
                payload.get("v") != 1 or
                payload.get("key_version") != settings.agent_draft_receipt_key_version or
                payload.get("plan_id") != plan.id or
                payload.get("delivery_date") != plan.delivery_date.isoformat() or
                payload.get("version") != plan.version or
                payload.get("user_id") != actor.id or
                payload.get("token_version") != actor.token_version or
                payload.get("snapshot_version") != snapshot or
                payload.get("plan_sha256") != digest or
                not isinstance(payload.get("nonce"), str) or len(payload["nonce"]) != 48 or
                not isinstance(payload.get("issued_at"), int) or
                not isinstance(payload.get("expires_at"), int) or
                payload["issued_at"] > int(now.timestamp()) + 30 or
                payload["expires_at"] <= int(now.timestamp()) or
                payload["expires_at"] - payload["issued_at"] > settings.agent_publish_receipt_ttl_seconds):
            raise ValueError()
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise PermissionDeniedError("Agent 发布确认凭据无效或已过期") from exc

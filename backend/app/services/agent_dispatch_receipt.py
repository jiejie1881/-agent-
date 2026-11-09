"""Short-lived, signed proof that a candidate came from a valid shadow run."""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

from app.domain.exceptions import BusinessError, PermissionDeniedError
from app.schemas.dispatch_candidate import DispatchCandidate, POLICY_VERSION


def candidate_digest(candidate: DispatchCandidate) -> str:
    payload = candidate.model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _key(settings) -> bytes:
    secret = settings.agent_draft_receipt_secret
    value = secret.get_secret_value() if secret is not None else ""
    if len(value.encode("utf-8")) < 32:
        raise PermissionDeniedError("Agent 草稿凭据密钥未配置")
    return value.encode("utf-8")


def issue_receipt(result, actor, settings, *, now: datetime | None = None) -> str:
    if (result.status != "SUCCESS" or result.candidate is None or
            result.validation is None or not result.validation.is_valid or
            not result.freshness_checked or result.stale_context or
            result.snapshot_version != result.candidate.snapshot_version):
        raise BusinessError("影子结果不可采纳", 409, "CANDIDATE_NOT_ACCEPTABLE")
    now = now or datetime.now(UTC)
    payload = {
        "v": 1, "key_version": settings.agent_draft_receipt_key_version,
        "nonce": secrets.token_hex(24), "run_id": result.run_id,
        "user_id": actor.id, "token_version": actor.token_version,
        "delivery_date": result.candidate.delivery_date.isoformat(),
        "snapshot_version": result.snapshot_version,
        "policy_version": POLICY_VERSION,
        "candidate_sha256": candidate_digest(result.candidate),
        "issued_at": int(now.timestamp()),
        "expires_at": int((now + timedelta(seconds=settings.agent_draft_receipt_ttl_seconds)).timestamp()),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_key(settings), raw, hashlib.sha256).digest()
    return ".".join(base64.urlsafe_b64encode(part).decode("ascii").rstrip("=")
                    for part in (raw, signature))


def verify_receipt(token: str, candidate: DispatchCandidate, actor, settings,
                   *, now: datetime | None = None) -> dict:
    try:
        if len(token) > 2048:
            raise ValueError()
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError()
        raw, signature = (base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)) for p in parts)
        expected = hmac.new(_key(settings), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(raw)
        now = now or datetime.now(UTC)
        if (payload.get("v") != 1 or payload.get("key_version") != settings.agent_draft_receipt_key_version or
                payload.get("user_id") != actor.id or
                payload.get("token_version") != actor.token_version or
                payload.get("delivery_date") != candidate.delivery_date.isoformat() or
                payload.get("snapshot_version") != candidate.snapshot_version or
                payload.get("policy_version") != POLICY_VERSION or
                payload.get("candidate_sha256") != candidate_digest(candidate) or
                not isinstance(payload.get("nonce"), str) or len(payload["nonce"]) != 48 or
                not isinstance(payload.get("issued_at"), int) or
                not isinstance(payload.get("expires_at"), int) or
                payload["issued_at"] > int(now.timestamp()) + 30 or
                payload["expires_at"] <= int(now.timestamp()) or
                payload["expires_at"] - payload["issued_at"] > 900):
            raise ValueError()
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise PermissionDeniedError("Agent 草稿凭据无效或已过期") from exc

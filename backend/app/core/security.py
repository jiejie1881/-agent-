import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.exceptions import AuthenticationError

PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码长度不能少于8位")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_value)
        expected = base64.urlsafe_b64decode(digest_value)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def _encode_segment(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_segment(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


def _create_token(
    subject: str,
    role: str,
    token_version: int,
    token_type: str,
    secret: str,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    header = _encode_segment({"alg": "HS256", "typ": "JWT"})
    payload = _encode_segment(
        {
            "sub": subject,
            "role": role,
            "ver": token_version,
            "typ": token_type,
            "iat": int(now.timestamp()),
            "exp": int((now + expires_delta).timestamp()),
        }
    )
    signing_input = f"{header}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{signing_input}.{encoded_signature}"


def create_access_token(
    subject: str, role: str, token_version: int, secret: str, expire_minutes: int
) -> str:
    return _create_token(
        subject,
        role,
        token_version,
        "access",
        secret,
        timedelta(minutes=expire_minutes),
    )


def create_refresh_token(
    subject: str, role: str, token_version: int, secret: str, expire_days: int
) -> str:
    return _create_token(
        subject,
        role,
        token_version,
        "refresh",
        secret,
        timedelta(days=expire_days),
    )


def decode_token(
    token: str, secret: str, expected_type: str
) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
        if _decode_segment(header) != {"alg": "HS256", "typ": "JWT"}:
            raise AuthenticationError()
        signing_input = f"{header}.{payload}"
        expected = hmac.new(
            secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(actual, expected):
            raise AuthenticationError()
        claims = _decode_segment(payload)
        if claims.get("exp", 0) <= int(datetime.now(timezone.utc).timestamp()):
            raise AuthenticationError()
        if not isinstance(claims.get("sub"), str):
            raise AuthenticationError()
        if claims.get("typ") != expected_type:
            raise AuthenticationError("Token类型无效")
        if not isinstance(claims.get("ver"), int):
            raise AuthenticationError()
        return claims
    except AuthenticationError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error):
        raise AuthenticationError() from None


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    return decode_token(token, secret, "access")


def decode_refresh_token(token: str, secret: str) -> dict[str, Any]:
    return decode_token(token, secret, "refresh")

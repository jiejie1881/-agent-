from pathlib import Path

from app.core.config import get_settings


def upload_root() -> Path:
    configured = Path(get_settings().upload_root)
    if configured.is_absolute():
        return configured.resolve()
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / configured).resolve()


def delivery_proof_directory() -> Path:
    return upload_root() / "delivery-proofs"

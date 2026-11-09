import pytest

from app.domain.exceptions import BusinessError
from app.services.knowledge_management_service import MAX_UPLOAD
from tests.test_knowledge_management import governance as _governance, upload_rule


@pytest.fixture(name="governance")
def private_governance(session, tmp_path):
    return _governance.__wrapped__(session, tmp_path)


@pytest.mark.parametrize("name", ["../rule.md", "..\\rule.md", "/tmp/rule.md", "C:\\rule.md", "bad.exe", "CON.md", "bad\x00.txt", "bad.md."])
def test_upload_rejects_unsafe_filename(governance, name):
    manager, base, actors = governance
    with pytest.raises(BusinessError):
        manager.upload(actors["admin"], base.id, name, b"synthetic")
    assert not (manager.root / "blobs").exists()


@pytest.mark.parametrize("data", [b"", b"\xff\xfe", b"hello\x00world", b"x" * (MAX_UPLOAD + 1)],
                         ids=["empty", "invalid-utf8", "nul-bytes", "over-5mb"])
def test_upload_rejects_bad_or_excessive_content(governance, data):
    manager, base, actors = governance
    with pytest.raises(BusinessError):
        manager.upload(actors["admin"], base.id, "synthetic.md", data)


def test_path_traversal_and_corrupt_blob_are_rejected(governance):
    manager, base, actors = governance
    for path in ["../outside", "../../x", "/absolute", "..\\x"]:
        with pytest.raises(BusinessError):
            manager.path(path)
    v = upload_rule(manager, base, actors["admin"])
    manager.path(v.storage_key).write_bytes(b"synthetic tampering")
    with pytest.raises(BusinessError, match="摘要"):
        manager.read_version(v)

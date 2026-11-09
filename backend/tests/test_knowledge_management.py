"""A1 metadata/authorization on private synthetic databases and owned files."""
import pytest
from sqlalchemy import select

from app.domain.enums import UserRole
from app.domain.exceptions import BusinessError, ConflictError, PermissionDeniedError
from app.models.audit_log import AuditLog
from app.models.knowledge import KnowledgeBase, KnowledgeDocument
from app.schemas.knowledge import KnowledgeBaseInput, KnowledgeBaseUpdate, KnowledgeDocumentAclInput
from app.services.auth_service import AuthService
from app.services.knowledge_management_service import KnowledgeManagementService


@pytest.fixture
def governance(session, tmp_path):
    root = KnowledgeManagementService.provision_storage(tmp_path / "knowledge-private")
    actors = {name: AuthService(session).create_user("knowledge-" + name, "SyntheticPass123!", role)
              for name, role in [("admin", UserRole.ADMIN), ("viewer", UserRole.VIEWER),
                                 ("dispatcher", UserRole.DISPATCHER), ("driver", UserRole.DRIVER)]}
    manager = KnowledgeManagementService(session, root, offline=True)
    base = manager.create_base(actors["admin"], KnowledgeBaseInput(name="合成物流规则", visibility="PUBLIC"))
    return manager, base, actors


def upload_rule(manager, base, actor, *, text="# 载重\n每趟货物不得超过车辆载重。\n# 出勤\n司机请假后代班必须人工确认。", expected_revision=None):
    return manager.upload(actor, base.id, "物流规则.md", text.encode(), expected_revision=expected_revision)


def test_storage_is_explicit_and_cannot_replace_existing_directory(session, tmp_path):
    manager = KnowledgeManagementService(session, tmp_path / "missing")
    with pytest.raises(BusinessError, match="尚未显式"):
        manager.path("blobs/example.txt")
    assert not manager.root.exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        manager.provision_storage(existing)


def test_document_version_upload_is_idempotent_and_stale_update_is_rejected(governance):
    manager, base, actors = governance
    v1 = upload_rule(manager, base, actors["admin"])
    assert upload_rule(manager, base, actors["admin"]).id == v1.id
    doc = manager.document(actors["admin"], v1.document_id)
    v2 = upload_rule(manager, base, actors["admin"], text="# 更新\n先确认出勤再派车。", expected_revision=doc.revision)
    assert v2.version == 2 and v2.id != v1.id
    assert manager.read_version(v1).startswith("# 载重")
    with pytest.raises(ConflictError):
        upload_rule(manager, base, actors["admin"], text="旧客户端的覆盖", expected_revision=0)
    assert manager.document(actors["admin"], doc.id).current_version_id == v2.id


@pytest.mark.parametrize("role", ["viewer", "dispatcher", "driver"])
def test_non_admin_cannot_mutate_knowledge(governance, role):
    manager, base, actors = governance
    with pytest.raises(PermissionDeniedError):
        manager.create_base(actors[role], KnowledgeBaseInput(name="拒绝"))
    assert any(a.action == "RAG_PERMISSION_DENIED" for a in manager.session.scalars(select(AuditLog)))


def test_base_and_document_permissions_and_revision(governance):
    manager, base, actors = governance
    v = upload_rule(manager, base, actors["admin"])
    d = manager.document(actors["admin"], v.document_id)
    manager.update_document_acl(actors["admin"], d.id, KnowledgeDocumentAclInput(expected_revision=d.revision, visibility="ADMIN"))
    assert not manager.documents(actors["viewer"], base.id)
    assert manager.documents(actors["admin"], base.id)
    manager.update_base(actors["admin"], base.id, KnowledgeBaseUpdate(name=base.name, expected_revision=base.revision,
        visibility="ROLES", read_roles=["DISPATCHER"]))
    assert manager.list_bases(actors["viewer"]) == []
    assert manager.list_bases(actors["driver"]) == []
    assert manager.list_bases(actors["dispatcher"])
    with pytest.raises(ConflictError):
        manager.update_base(actors["admin"], base.id, KnowledgeBaseUpdate(name=base.name, expected_revision=0))


def test_logical_delete_preserves_versions_files_and_audit(governance):
    manager, base, actors = governance
    v = upload_rule(manager, base, actors["admin"])
    d = manager.document(actors["admin"], v.document_id)
    original = manager.path(v.storage_key).read_bytes()
    manager.delete_document(actors["admin"], d.id, d.revision, True)
    assert manager.path(v.storage_key).read_bytes() == original
    assert manager.snapshot(base.id) == {}
    assert not manager.documents(actors["viewer"], base.id)
    assert manager.versions(actors["admin"], d.id)[0].id == v.id
    assert manager.session.scalar(select(AuditLog).where(AuditLog.action == "RAG_DOCUMENT_DELETED"))


def test_upload_audit_failure_rolls_back_document_pointer(governance, monkeypatch):
    manager, base, actors = governance
    monkeypatch.setattr(manager, "audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic audit failure")))
    with pytest.raises(RuntimeError):
        upload_rule(manager, base, actors["admin"])
    assert manager.session.scalars(select(KnowledgeDocument)).all() == []
    assert manager.session.get(KnowledgeBase, base.id).active_index_id is None

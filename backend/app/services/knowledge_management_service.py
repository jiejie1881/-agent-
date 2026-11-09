"""Governance mutations; no model calls, implicit storage setup or hard deletes."""
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import unicodedata
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.enums import UserRole
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.models.knowledge import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeEvaluationRun, KnowledgeIndexVersion, utcnow
from app.services.audit_log_service import AuditLogService
from app.services.knowledge_execution import require_knowledge_execution

MAX_UPLOAD = 5 * 1024 * 1024
MARKER = ".knowledge-governance-v1"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class KnowledgeManagementService:
    def __init__(self, session, storage_root, *, offline=False):
        self.session = session
        self.root = Path(storage_root).absolute()
        self.offline = offline

    @staticmethod
    def provision_storage(path):
        """Explicit provisioning only. Never called on import, app startup or upload."""
        root = Path(path).absolute()
        for parent in root.parents:
            if parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
                raise BusinessError("存储父路径含链接", 409)
        root.mkdir(parents=False, exist_ok=False)
        with (root / MARKER).open("x", encoding="utf-8") as stream:
            json.dump({"format": 1, "identity": uuid4().hex}, stream)
        return root

    def path(self, relative):
        if not self.root.is_dir() or not (self.root / MARKER).is_file():
            raise BusinessError("知识存储尚未显式配置", 503, "KNOWLEDGE_STORAGE_UNPROVISIONED")
        p = Path(relative)
        if p.is_absolute() or not p.parts or any(part in {".", ".."} for part in p.parts) or "\\" in str(relative):
            raise BusinessError("非法知识存储路径", 422)
        target = self.root / p
        for part in (self.root, *target.parents, target):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
                raise BusinessError("知识存储禁止链接", 409)
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise BusinessError("知识路径超出专属存储", 422)
        return target

    def audit(self, actor, action, object_type, object_id, details):
        AuditLogService(self.session).add(actor, action, object_type, object_id, details)

    def admin(self, actor):
        if not actor.is_active or actor.role != UserRole.ADMIN:
            self.audit(actor, "RAG_PERMISSION_DENIED", "Knowledge", None, {"result": "DENIED"})
            self.session.commit()
            raise PermissionDeniedError()

    @staticmethod
    def may_read(base, actor):
        return bool(actor.is_active and actor.role != UserRole.DRIVER and (
            actor.role == UserRole.ADMIN or (base.status == "ACTIVE" and (
                base.visibility == "PUBLIC" or (base.visibility == "ROLES" and actor.role.value in base.read_roles)))))

    def base(self, base_id, actor, *, write=False):
        if write:
            self.admin(actor)
        value = self.session.get(KnowledgeBase, base_id)
        if value is None or not self.may_read(value, actor):
            raise NotFoundError("知识库不存在或无权访问")
        return value

    def list_bases(self, actor):
        return [b for b in self.session.scalars(select(KnowledgeBase).order_by(KnowledgeBase.id)) if self.may_read(b, actor)]

    def create_base(self, actor, data):
        self.admin(actor)
        try:
            base = KnowledgeBase(**data.model_dump(), created_by=actor.id)
            self.session.add(base)
            self.session.flush()
            self.audit(actor, "RAG_BASE_CREATED", "KnowledgeBase", base.id, {"result": "SUCCESS", "visibility": base.visibility})
            self.session.commit()
            return base
        except IntegrityError:
            self.session.rollback()
            raise ConflictError("知识库名称已存在") from None
        except Exception:
            self.session.rollback()
            raise

    def update_base(self, actor, base_id, data):
        base = self.base(base_id, actor, write=True)
        values = data.model_dump(exclude={"expected_revision"})
        try:
            result = self.session.execute(update(KnowledgeBase).where(
                KnowledgeBase.id == base.id, KnowledgeBase.revision == data.expected_revision).values(
                    **values, revision=KnowledgeBase.revision + 1), execution_options={"synchronize_session": False})
            if result.rowcount != 1:
                raise ConflictError("知识库版本已变化，请刷新")
            self.audit(actor, "RAG_BASE_UPDATED", "KnowledgeBase", base.id, {"result": "SUCCESS", "fields": sorted(values)})
            self.session.commit()
            self.session.refresh(base)
            return base
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def filename(name):
        name = unicodedata.normalize("NFC", name)
        if (not name or len(name) > 180 or Path(name).name != name or PureWindowsPath(name).name != name
                or any(c in name for c in '/\\:\x00<>"|?*') or any(ord(c) < 32 for c in name)
                or name.endswith((".", " ")) or Path(name).suffix.lower() not in {".md", ".txt"}):
            raise BusinessError("仅支持安全命名的 UTF-8 Markdown/TXT 文档", 422)
        if name.split(".")[0].upper() in {"CON", "NUL", "AUX", "PRN", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise BusinessError("文档名称为保留名称", 422)
        return name

    def documents(self, actor, base_id):
        base = self.base(base_id, actor)
        return [d for d in self.session.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.base_id == base_id).order_by(KnowledgeDocument.id)) if self.may_read_document(base, d, actor)]

    @classmethod
    def may_read_document(cls, base, doc, actor):
        return cls.may_read(base, actor) and (actor.role == UserRole.ADMIN or (
            not doc.deleted and (doc.visibility == "INHERIT" or
                (doc.visibility == "ROLES" and actor.role.value in doc.read_roles))))

    def document(self, actor, document_id, *, write=False):
        value = self.session.get(KnowledgeDocument, document_id)
        if value is None:
            raise NotFoundError("知识文档不存在")
        base = self.base(value.base_id, actor, write=write)
        if not self.may_read_document(base, value, actor):
            raise NotFoundError("知识文档不存在或无权访问")
        return value

    def update_document_acl(self, actor, document_id, data):
        doc = self.document(actor, document_id, write=True)
        try:
            result = self.session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.id == doc.id, KnowledgeDocument.revision == data.expected_revision).values(
                    visibility=data.visibility, read_roles=data.read_roles, revision=KnowledgeDocument.revision + 1),
                execution_options={"synchronize_session": False})
            if result.rowcount != 1:
                raise ConflictError("文档权限版本冲突")
            self.audit(actor, "RAG_DOCUMENT_ACL_UPDATED", "KnowledgeDocument", doc.id,
                {"result": "SUCCESS", "visibility": data.visibility, "read_roles": data.read_roles})
            self.session.commit()
            self.session.refresh(doc)
            return doc
        except Exception:
            self.session.rollback()
            raise

    def upload(self, actor, base_id, filename, content, *, source_label="upload", expected_revision=None, document_id=None):
        base = self.base(base_id, actor, write=True)
        if base.status != "ACTIVE":
            raise ConflictError("归档知识库不能上传")
        name = self.filename(filename)
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_UPLOAD:
            raise BusinessError("文档不能为空且不得超过5MB", 422)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError:
            raise BusinessError("文档必须采用UTF-8编码", 422) from None
        if not text.strip() or "\x00" in text or len(source_label) > 300:
            raise BusinessError("文档内容或来源格式无效", 422)
        digest = hashlib.sha256(content).hexdigest()
        doc = self.document(actor, document_id, write=True) if document_id else self.session.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.base_id == base_id, KnowledgeDocument.key == name.casefold()).with_for_update())
        if doc and doc.base_id != base_id:
            raise NotFoundError("知识文档不存在")
        if doc and doc.deleted:
            raise ConflictError("已删除文档不能覆盖；请使用新的文档名称")
        previous = self.session.get(KnowledgeDocumentVersion, doc.current_version_id) if doc else None
        if previous and previous.sha256 == digest and previous.source_label == source_label:
            return previous
        if doc and expected_revision != doc.revision:
            raise ConflictError("文档版本已变化或未提供版本，请刷新")
        relative = f"blobs/{uuid4().hex}{Path(name).suffix.lower()}"
        blob = self.path(relative)
        blob.parent.mkdir(exist_ok=True)
        # Preserve a failed transaction's owned blob for diagnosis; never overwrite/delete.
        with blob.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if doc is None:
                doc = KnowledgeDocument(base_id=base_id, key=name.casefold(), title=name)
                self.session.add(doc)
                self.session.flush()
            else:
                changed = self.session.execute(update(KnowledgeDocument).where(
                    KnowledgeDocument.id == doc.id, KnowledgeDocument.revision == expected_revision).values(
                        revision=KnowledgeDocument.revision + 1), execution_options={"synchronize_session": False})
                if changed.rowcount != 1:
                    raise ConflictError("文档版本冲突")
            version = KnowledgeDocumentVersion(document_id=doc.id, version=previous.version + 1 if previous else 1,
                sha256=digest, storage_key=relative, original_name=name, source_label=source_label, created_by=actor.id)
            self.session.add(version)
            self.session.flush()
            doc.current_version_id = version.id
            self.audit(actor, "RAG_DOCUMENT_UPLOADED", "KnowledgeDocument", doc.id,
                       {"result": "SUCCESS", "version_id": version.id, "version": version.version, "sha256": digest})
            self.session.commit()
            self.session.refresh(doc)
            return version
        except IntegrityError:
            self.session.rollback()
            raise ConflictError("文档并发版本冲突") from None
        except Exception:
            self.session.rollback()
            raise

    def versions(self, actor, document_id):
        self.document(actor, document_id)
        return list(self.session.scalars(select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document_id).order_by(KnowledgeDocumentVersion.version.desc())))

    def read_version(self, version):
        raw = self.path(version.storage_key).read_bytes()
        if hashlib.sha256(raw).hexdigest() != version.sha256:
            raise BusinessError("文档摘要校验失败", 409, "DOCUMENT_INTEGRITY")
        return raw.decode("utf-8-sig")

    def delete_document(self, actor, document_id, expected_revision, confirmed):
        doc = self.document(actor, document_id, write=True)
        if not confirmed:
            raise BusinessError("删除需要人工确认", 422)
        try:
            result = self.session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.id == doc.id, KnowledgeDocument.revision == expected_revision,
                KnowledgeDocument.deleted.is_(False)).values(deleted=True, revision=KnowledgeDocument.revision + 1),
                execution_options={"synchronize_session": False})
            if result.rowcount != 1:
                raise ConflictError("文档已变化或已删除")
            self.audit(actor, "RAG_DOCUMENT_DELETED", "KnowledgeDocument", doc.id, {"result": "SUCCESS", "physical_files_retained": True})
            self.session.commit()
            self.session.refresh(doc)
            return doc
        except Exception:
            self.session.rollback()
            raise

    def snapshot(self, base_id):
        docs = list(self.session.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.base_id == base_id, KnowledgeDocument.deleted.is_(False)).order_by(KnowledgeDocument.id)))
        return {str(d.id): d.current_version_id for d in docs}

    def index(self, actor, index_id, *, write=False):
        value = self.session.get(KnowledgeIndexVersion, index_id)
        if value is None:
            raise NotFoundError("知识索引不存在")
        self.base(value.base_id, actor, write=write)
        return value

    def publish(self, actor, index_id, expected_active_id, expected_revision, confirmed, *, rollback=False):
        value = self.index(actor, index_id, write=True)
        base = self.base(value.base_id, actor, write=True)
        try:
            require_knowledge_execution(self.session, self.offline)
            if not confirmed or base.status != "ACTIVE":
                raise ConflictError("知识库不可发布或缺少人工确认")
            if not rollback and self.snapshot(base.id) != value.snapshot:
                raise ConflictError("文档快照已变化，不能发布旧候选")
            if rollback and value.status != "PUBLISHED":
                raise ConflictError("只能回退到曾发布且验证过的版本")
            latest = self.session.scalar(select(KnowledgeEvaluationRun).where(
                KnowledgeEvaluationRun.index_id == value.id).order_by(KnowledgeEvaluationRun.id.desc()).limit(1))
            if latest is None or latest.status != "PASS":
                raise ConflictError("最近一次质量检查未通过")
            if value.status not in {"VALIDATED", "PUBLISHED"}:
                raise ConflictError("索引状态不可发布")
            expected_kind = 'OFFLINE_SYNTHETIC' if self.offline else 'REAL_MODEL_DOCUMENT_SMOKE'
            if value.validation_kind != expected_kind:
                raise ConflictError("真实模型质量准入尚未授权")
            from app.services.knowledge_job_service import KnowledgeJobService
            KnowledgeJobService(self.session, self.root, offline=self.offline).checked_index(value)
            result = self.session.execute(update(KnowledgeBase).where(
                KnowledgeBase.id == base.id, KnowledgeBase.revision == expected_revision,
                KnowledgeBase.active_index_id == expected_active_id).values(
                    active_index_id=value.id, revision=KnowledgeBase.revision + 1),
                execution_options={"synchronize_session": False})
            if result.rowcount != 1:
                raise ConflictError("活动索引已变化，发布已停止")
            guarded = self.session.execute(update(KnowledgeIndexVersion).where(
                KnowledgeIndexVersion.id == value.id, KnowledgeIndexVersion.status.in_(["VALIDATED", "PUBLISHED"]),
                KnowledgeIndexVersion.validation_kind == expected_kind).values(status="PUBLISHED", published_at=utcnow()),
                execution_options={"synchronize_session": False})
            if guarded.rowcount != 1:
                raise ConflictError("索引验证状态已变化")
            self.audit(actor, "RAG_INDEX_ROLLED_BACK" if rollback else "RAG_INDEX_PUBLISHED", "KnowledgeBase", base.id,
                {"result": "SUCCESS", "index_id": value.id, "previous_index_id": expected_active_id,
                 "validation_kind": value.validation_kind, "publication_scope": "LOCAL_OFFLINE_ONLY" if self.offline else 'REVIEWED_DEPLOYMENT_DOCUMENT_SMOKE'})
            self.session.commit()
            self.session.refresh(base)
            self.session.refresh(value)
            return value
        except Exception:
            self.session.rollback()
            self.audit(actor, "RAG_PUBLICATION_FAILED", "KnowledgeBase", base.id,
                       {"result": "FAILED", "index_id": value.id, "error_type": "PUBLICATION_REJECTED"})
            self.session.commit()
            raise

    def retire_index(self, actor, index_id, expected_revision, confirmed):
        value = self.index(actor, index_id, write=True)
        base = self.base(value.base_id, actor, write=True)
        if not confirmed:
            raise BusinessError("索引退役需要人工确认", 422)
        try:
            result = self.session.execute(update(KnowledgeBase).where(
                KnowledgeBase.id == base.id, KnowledgeBase.revision == expected_revision,
                or_(KnowledgeBase.active_index_id.is_(None), KnowledgeBase.active_index_id != value.id)).values(
                    revision=KnowledgeBase.revision + 1), execution_options={"synchronize_session": False})
            if result.rowcount != 1:
                raise ConflictError("活动索引不能退役或知识库版本已变化")
            value.status = "RETIRED"
            self.audit(actor, "RAG_INDEX_RETIRED", "KnowledgeIndex", value.id,
                       {"result": "SUCCESS", "physical_files_retained": True})
            self.session.commit()
            self.session.refresh(base)
            return value
        except Exception:
            self.session.rollback()
            raise

"""长期记忆服务（MySQL 权威 + Chroma 派生投影 + Outbox 可靠同步）。

设计要点
--------
1. **身份不信任模型**：``user_id`` 一律由调用方从认证上下文传入，记忆查询强制附带
   ``tenant_id/user_id/project_id`` 三个作用域条件，跨用户查询一律 ``NotFoundError``。
2. **MySQL 是权威**：向量只是投影。召回结果必须回 MySQL 复核状态/版本/过期，
   墓碑或过期记忆即使向量残留也不可被检索到。
3. **Outbox 可靠同步**：写入/更新/删除先提交 MySQL 与 Outbox，再由 ``sync_outbox``
   幂等推送到 Chroma；失败按指数退避重试，进程崩溃后 ``PROCESSING`` 会被重置重放。
4. **可重建**：``rebuild_index`` 清空并重建集合，从 MySQL 全量重放。

兼容性：保留原有 ``save/list/search/sync/delete/owned`` 语义（PENDING→ACTIVE→DELETED），
新能力（memory_key 幂等、版本快照、审计、归档、最终删除、重建索引、会话摘要）为增量。
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update as sql_update

from app.domain.exceptions import NotFoundError
from app.models.agent_memory import (
    MEMORY_STATUS_ACTIVE,
    MEMORY_STATUS_ARCHIVED,
    MEMORY_STATUS_DELETED,
    MEMORY_STATUS_PENDING,
    AgentMemory,
    AgentMemoryAudit,
    AgentMemoryOutbox,
    AgentMemoryVersion,
    AgentSessionSummary,
)

logger = logging.getLogger(__name__)

MAX_MEMORY_LENGTH = 2000
MAX_MEMORY_KEY_LENGTH = 191
_BACKOFF_CAP_SECONDS = 300
_OUTBOX_BATCH = 200

# 敏感信息与个人身份信息：禁止写入长期记忆（沿用既有规则并补充）
_SENSITIVE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|password|passwd|secret[_ -]?key|bearer\s|密码|密钥|口令|"
    r"身份证|银行卡|信用卡|\b\d{17}[\dXx]\b|\b1[3-9]\d{9}\b)"
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class AgentMemoryService:
    """长期记忆核心服务：不依赖任何具体 Agent 节点。"""

    def __init__(
        self,
        db,
        collection,
        embedding,
        *,
        tenant_id: str = "logistics",
        project_id: str = "logistics-dispatch",
        embedding_version: str = "unknown",
    ):
        self.db = db
        self.collection = collection
        self.embedding = embedding
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.embedding_version = embedding_version

    # ---------------------------------------------------------------- 作用域
    def _scope(self, user_id: int) -> tuple:
        return (
            AgentMemory.tenant_id == self.tenant_id,
            AgentMemory.user_id == int(user_id),
            AgentMemory.project_id == self.project_id,
        )

    def owned(self, user_id: int, memory_id: str, for_update: bool = False, include_deleted: bool = False):
        query = select(AgentMemory).where(AgentMemory.memory_id == memory_id, *self._scope(user_id))
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.db.scalar(query)
        if row is None or (row.status == MEMORY_STATUS_DELETED and not include_deleted):
            raise NotFoundError("记忆不存在")
        return row

    # ---------------------------------------------------------------- 校验
    @staticmethod
    def validate_content(content: str) -> str:
        content = (content or "").strip()
        if not content or len(content) > MAX_MEMORY_LENGTH:
            raise ValueError("记忆内容长度必须为1到2000字符")
        if _SENSITIVE_PATTERN.search(content):
            raise ValueError("请勿保存敏感信息")
        return content

    @staticmethod
    def validate_key(memory_key: str | None) -> str | None:
        if memory_key is None:
            return None
        key = memory_key.strip()
        if not key:
            return None
        if len(key) > MAX_MEMORY_KEY_LENGTH:
            raise ValueError("记忆键长度不能超过191字符")
        if _SENSITIVE_PATTERN.search(key):
            raise ValueError("记忆键不得包含敏感信息")
        return key

    # ---------------------------------------------------------------- 快照 / 审计 / Outbox
    def _snapshot(self, row: AgentMemory) -> None:
        self.db.add(
            AgentMemoryVersion(
                memory_id=row.memory_id,
                version=int(row.version),
                memory_value=row.memory_value,
                summary=row.summary,
                status=row.status,
                source=row.source,
                created_by=row.user_id,
            )
        )

    def _audit(
        self,
        *,
        row: AgentMemory,
        action: str,
        before: dict | None = None,
        after: dict | None = None,
        actor_user_id: int | None = None,
        reason: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.db.add(
            AgentMemoryAudit(
                memory_id=row.memory_id,
                action=action,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                project_id=row.project_id,
                actor_user_id=actor_user_id,
                before_json=before,
                after_json=after,
                reason=reason,
                trace_id=trace_id,
            )
        )

    def _payload(self, row: AgentMemory, *, status: str) -> dict[str, Any]:
        # user_id 统一用字符串（与 search 的 where 条件一致，避免 int/str 不匹配）
        return {
            "memory_id": row.memory_id,
            "tenant_id": row.tenant_id,
            "user_id": str(int(row.user_id)),
            "project_id": row.project_id,
            "memory_type": row.memory_type,
            "status": status,
            "embedding_version": row.embedding_version,
            "version": int(row.version),
        }

    def _enqueue(self, row: AgentMemory, operation: str) -> None:
        self.db.add(
            AgentMemoryOutbox(
                memory_id=row.memory_id,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                project_id=row.project_id,
                embedding_version=row.embedding_version,
                operation=operation,
                payload_json={"version": int(row.version)},
                status="PENDING",
                # MySQL DATETIME(0) 会对小数秒四舍五入，截断到秒避免"刚入队就未到期"
                available_at=utcnow().replace(microsecond=0),
            )
        )

    # ---------------------------------------------------------------- 写入
    def save(
        self,
        user_id: int,
        content: str,
        memory_type: str = "preference",
        memory_id: str | None = None,
        source_conversation_id: int | None = None,
        expires_at: datetime | None = None,
        importance: float = 0.5,
        *,
        memory_key: str | None = None,
        source: str = "user_explicit",
        source_ref: str | None = None,
        confidence: float = 1.0,
        metadata: dict | None = None,
        actor_user_id: int | None = None,
        trace_id: str | None = None,
    ) -> AgentMemory:
        """写入或更新一条记忆（同 user+type+key 幂等；同内容去重）。"""
        content = self.validate_content(content)
        memory_key = self.validate_key(memory_key)
        if expires_at is not None and expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)

        row: AgentMemory | None
        if memory_id:
            row = self.owned(user_id, memory_id, for_update=True)
        elif memory_key:
            row = self.db.scalar(
                select(AgentMemory).where(
                    *self._scope(user_id),
                    AgentMemory.memory_type == memory_type,
                    AgentMemory.memory_key == memory_key,
                    AgentMemory.status != MEMORY_STATUS_DELETED,
                )
            )
        else:
            row = self.db.scalar(
                select(AgentMemory).where(
                    *self._scope(user_id),
                    AgentMemory.memory_value == content,
                    AgentMemory.status != MEMORY_STATUS_DELETED,
                )
            )

        before = None
        if row is None:
            row = AgentMemory(
                memory_id=str(uuid4()),
                tenant_id=self.tenant_id,
                user_id=int(user_id),
                project_id=self.project_id,
                memory_type=memory_type,
                memory_key=memory_key,
                version=1,
                status=MEMORY_STATUS_PENDING,
                embedding_version=self.embedding_version,
            )
            self.db.add(row)
        else:
            before = {
                "status": row.status,
                "version": int(row.version),
                "value_sha256": _digest(row.memory_value),
            }
            row.version += 1
            row.status = MEMORY_STATUS_PENDING
            row.deleted_at = None

        row.memory_type = memory_type
        row.memory_value = content
        row.summary = content if len(content) <= 512 else content[:509] + "..."
        row.source = source
        row.source_ref = source_ref
        row.source_conversation_id = source_conversation_id
        row.confidence = float(confidence)
        row.importance = float(importance)
        row.metadata_json = metadata
        row.expires_at = expires_at
        row.updated_at = utcnow()
        if row.memory_key is None and memory_key is not None:
            row.memory_key = memory_key

        self.db.flush()
        self._snapshot(row)
        self._audit(
            row=row,
            action="UPDATE" if before else "CREATE",
            before=before,
            after={
                "status": row.status,
                "version": int(row.version),
                "value_sha256": _digest(row.memory_value),
                "value_length": len(row.memory_value),
                "memory_type": row.memory_type,
                "source": row.source,
            },
            actor_user_id=actor_user_id,
            trace_id=trace_id,
        )
        self._enqueue(row, "UPSERT")
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, user_id: int, memory_id: str, **fields) -> AgentMemory:
        row = self.owned(user_id, memory_id, for_update=True)
        content = fields.pop("content", None)
        return self.save(
            user_id,
            content if content is not None else row.memory_value,
            memory_type=fields.pop("memory_type", row.memory_type),
            memory_id=memory_id,
            expires_at=fields.pop("expires_at", row.expires_at),
            importance=fields.pop("importance", row.importance),
            memory_key=fields.pop("memory_key", row.memory_key),
            **fields,
        )

    # ---------------------------------------------------------------- 读取
    def list(self, user_id: int, limit: int = 100):
        return list(
            self.db.scalars(
                select(AgentMemory)
                .where(*self._scope(user_id), AgentMemory.status != MEMORY_STATUS_DELETED)
                .order_by(AgentMemory.updated_at.desc())
                .limit(min(max(int(limit), 1), 100))
            )
        )

    def list_memories(
        self,
        user_id: int,
        *,
        memory_type: str | None = None,
        status: str | None = None,
        include_expired: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AgentMemory], int]:
        conditions = list(self._scope(user_id))
        conditions.append(AgentMemory.status == (status or MEMORY_STATUS_ACTIVE))
        if memory_type:
            conditions.append(AgentMemory.memory_type == memory_type)
        if not include_expired:
            now = utcnow()
            conditions.append(
                (AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > now)
            )
        total = self.db.scalar(select(func.count()).select_from(AgentMemory).where(*conditions)) or 0
        rows = list(
            self.db.scalars(
                select(AgentMemory)
                .where(*conditions)
                .order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.desc())
                .limit(max(1, min(int(limit), 200)))
                .offset(max(0, int(offset)))
            )
        )
        return rows, int(total)

    def version_history(self, user_id: int, memory_id: str, limit: int = 20) -> list[AgentMemoryVersion]:
        self.owned(user_id, memory_id, include_deleted=True)
        return list(
            self.db.scalars(
                select(AgentMemoryVersion)
                .where(AgentMemoryVersion.memory_id == memory_id)
                .order_by(AgentMemoryVersion.version.desc())
                .limit(max(1, int(limit)))
            )
        )

    # ---------------------------------------------------------------- 检索
    def search(
        self,
        user_id: int,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
        budget: int = 3000,
    ) -> list[dict]:
        """向量召回 + MySQL 权威复核（状态/版本/过期/预算）。"""
        top_k = max(1, min(int(top_k), 10))
        query = (query or "").strip()
        if not query or not self.collection.count():
            return []
        result = self.collection.query(
            query_embeddings=[self.embedding.embed_query(query)],
            n_results=max(top_k * 3, top_k),
            where={"user_id": str(int(user_id))},
            include=["metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        now = utcnow()
        hits: list[dict] = []
        for memory_id, meta, distance in zip(ids, metadatas, distances):
            score = 1.0 - float(distance)
            if score < threshold:
                continue
            try:
                row = self.owned(int(user_id), memory_id)
            except NotFoundError:
                continue
            if row.status != MEMORY_STATUS_ACTIVE:
                continue
            if int((meta or {}).get("version", 0)) != int(row.version):
                continue  # 索引落后于权威数据：等 Outbox 补齐
            if row.expires_at is not None and row.expires_at <= now:
                continue
            if len(row.memory_value) > budget:
                continue
            budget -= len(row.memory_value)
            hits.append(
                {
                    "memory_id": row.memory_id,
                    "content": row.memory_value,
                    "memory_type": row.memory_type,
                    "score": score,
                    "importance": row.importance,
                    "version": int(row.version),
                }
            )
        return hits[:top_k]

    # ---------------------------------------------------------------- 删除 / 归档
    def delete(self, user_id: int, memory_id: str, hard: bool = False) -> dict:
        """软删除（墓碑 + 清向量）或最终删除（清版本、Outbox 与行）。"""
        row = self.owned(user_id, memory_id, for_update=True, include_deleted=hard)
        if hard:
            try:
                self.collection.delete(ids=[memory_id])
            except Exception as exc:  # noqa: BLE001 - 向量清理失败由重建兜底
                logger.warning("最终删除前清理向量失败（可由重建索引兜底）: %s", exc)
            self._audit(
                row=row,
                action="HARD_DELETE",
                before={
                    "status": row.status,
                    "version": int(row.version),
                    "value_sha256": _digest(row.memory_value),
                },
            )
            self.db.execute(sql_delete(AgentMemoryVersion).where(AgentMemoryVersion.memory_id == memory_id))
            self.db.execute(sql_delete(AgentMemoryOutbox).where(AgentMemoryOutbox.memory_id == memory_id))
            self.db.execute(sql_delete(AgentMemory).where(AgentMemory.memory_id == memory_id))
            self.db.commit()
            return {"memory_id": memory_id, "status": "PURGED", "vector_cleanup": "DONE"}

        row.status = MEMORY_STATUS_DELETED
        row.deleted_at = utcnow()
        row.version += 1
        row.updated_at = utcnow()
        self.db.flush()
        self._snapshot(row)
        self._audit(
            row=row,
            action="DELETE",
            before={"status": MEMORY_STATUS_ACTIVE, "version": int(row.version) - 1},
            after={"status": row.status, "version": int(row.version)},
        )
        self._enqueue(row, "DELETE")
        self.db.commit()
        # 墓碑先落地；向量清理由 sync/Outbox 保证（索引故障不影响删除语义）
        return {"memory_id": memory_id, "status": MEMORY_STATUS_DELETED}

    def archive(self, user_id: int, memory_id: str) -> AgentMemory:
        row = self.owned(user_id, memory_id, for_update=True)
        row.status = MEMORY_STATUS_ARCHIVED
        row.version += 1
        row.updated_at = utcnow()
        self.db.flush()
        self._snapshot(row)
        self._audit(
            row=row,
            action="ARCHIVE",
            before={"status": MEMORY_STATUS_ACTIVE, "version": int(row.version) - 1},
            after={"status": row.status, "version": int(row.version)},
        )
        self._enqueue(row, "DELETE")
        self.db.commit()
        self.db.refresh(row)
        return row

    # ---------------------------------------------------------------- 投影同步
    def _project_row(self, row: AgentMemory) -> None:
        """把单行记忆投影到 Chroma（幂等）。"""
        if row.status in {MEMORY_STATUS_ACTIVE, MEMORY_STATUS_PENDING} and row.expires_at is not None and row.expires_at <= utcnow():
            self.collection.delete(ids=[row.memory_id])
            return
        if row.status not in {MEMORY_STATUS_ACTIVE, MEMORY_STATUS_PENDING}:
            self.collection.delete(ids=[row.memory_id])
            return
        vector = self.embedding.embed_query(row.memory_value)
        self.collection.upsert(
            ids=[row.memory_id],
            embeddings=[vector],
            documents=[row.memory_value],
            metadatas=[
                {
                    "user_id": str(int(row.user_id)),
                    "version": int(row.version),
                    "status": MEMORY_STATUS_ACTIVE,
                    "memory_type": row.memory_type,
                    "memory_id": row.memory_id,
                    "tenant_id": row.tenant_id,
                    "project_id": row.project_id,
                    "embedding_version": row.embedding_version,
                }
            ],
        )

    def sync(self, user_id: int) -> int:
        """旧接口：投影该用户所有待同步行（PENDING/DELETED），失败不吞异常。"""
        rows = list(
            self.db.scalars(
                select(AgentMemory).where(
                    *self._scope(user_id),
                    AgentMemory.status.in_([MEMORY_STATUS_PENDING, MEMORY_STATUS_DELETED]),
                )
            )
        )
        for candidate in rows:
            row = self.db.scalar(
                select(AgentMemory)
                .where(AgentMemory.memory_id == candidate.memory_id, *self._scope(user_id))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                continue
            try:
                self._project_row(row)
            except Exception as exc:  # noqa: BLE001 - 记录失败后继续抛给调用方
                self._mark_failure(row.memory_id, exc)
                self.db.commit()
                raise
            if row.status == MEMORY_STATUS_PENDING:
                row.status = MEMORY_STATUS_ACTIVE
            self._mark_done(row.memory_id)
            self.db.commit()
        return len(rows)

    def _mark_done(self, memory_id: str) -> None:
        self.db.execute(
            sql_update(AgentMemoryOutbox)
            .where(
                AgentMemoryOutbox.memory_id == memory_id,
                AgentMemoryOutbox.status.in_(["PENDING", "PROCESSING", "FAILED"]),
            )
            .values(status="DONE", last_error=None, updated_at=utcnow())
        )

    def _mark_failure(self, memory_id: str, exc: Exception) -> None:
        entries = self.db.scalars(
            select(AgentMemoryOutbox).where(
                AgentMemoryOutbox.memory_id == memory_id,
                AgentMemoryOutbox.status.in_(["PENDING", "PROCESSING", "FAILED"]),
            )
        ).all()
        for entry in entries:
            entry.attempts += 1
            entry.last_error = str(exc)[:500]
            entry.status = "FAILED"
            backoff = min(2 ** min(entry.attempts, 8), _BACKOFF_CAP_SECONDS)
            entry.available_at = (utcnow() + timedelta(seconds=backoff)).replace(microsecond=0)
            entry.updated_at = utcnow()

    def _outbox_scope(self, user_id: int | None):
        conditions = [AgentMemoryOutbox.tenant_id == self.tenant_id,
                      AgentMemoryOutbox.project_id == self.project_id,
                      AgentMemoryOutbox.embedding_version == self.embedding_version]
        if user_id is not None:
            conditions.append(AgentMemoryOutbox.user_id == int(user_id))
        return conditions

    def _vector_scope(self, user_id: int | None):
        conditions = [{"tenant_id": self.tenant_id}, {"project_id": self.project_id},
                      {"embedding_version": self.embedding_version}]
        if user_id is not None:
            conditions.append({"user_id": str(int(user_id))})
        return {"$and": conditions}

    def sync_outbox(self, limit: int = _OUTBOX_BATCH, *, user_id: int | None = None) -> dict[str, int]:
        """排空项目 Outbox。HTTP 调用只处理当前用户的任务。"""
        conditions = self._outbox_scope(user_id)
        self.db.execute(
            sql_update(AgentMemoryOutbox)
            .where(*conditions, AgentMemoryOutbox.status == "PROCESSING")
            .values(status="PENDING")
        )
        self.db.commit()

        now = utcnow()
        entries = list(
            self.db.scalars(
                select(AgentMemoryOutbox)
                .where(
                    *conditions,
                    AgentMemoryOutbox.status.in_(["PENDING", "FAILED"]),
                    AgentMemoryOutbox.available_at <= now,
                )
                .order_by(AgentMemoryOutbox.id)
                .limit(max(1, int(limit)))
            )
        )
        processed = failed = 0
        for entry in entries:
            entry.status = "PROCESSING"
            self.db.commit()
            try:
                if entry.operation == "DELETE":
                    self.collection.delete(ids=[entry.memory_id])
                else:
                    row = self.db.get(AgentMemory, entry.memory_id)
                    if row is None:
                        self.collection.delete(ids=[entry.memory_id])
                    elif row.status in {MEMORY_STATUS_PENDING, MEMORY_STATUS_ACTIVE}:
                        # PENDING 同样必须投影：同步成功即视为已生效（旧接口语义）
                        self._project_row(row)
                        if row.status == MEMORY_STATUS_PENDING:
                            row.status = MEMORY_STATUS_ACTIVE
                    else:
                        self.collection.delete(ids=[entry.memory_id])
                entry.status = "DONE"
                entry.last_error = None
                processed += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不影响其它条目
                entry.attempts += 1
                entry.last_error = str(exc)[:500]
                entry.status = "FAILED"
                backoff = min(2 ** min(entry.attempts, 8), _BACKOFF_CAP_SECONDS)
                entry.available_at = (utcnow() + timedelta(seconds=backoff)).replace(microsecond=0)
                failed += 1
                logger.warning("Outbox 同步失败 memory=%s attempts=%s: %s", entry.memory_id, entry.attempts, exc)
            entry.updated_at = utcnow()
            self.db.commit()

        remaining = self.db.scalar(
            select(func.count())
            .select_from(AgentMemoryOutbox)
            .where(
                *conditions,
                AgentMemoryOutbox.status.in_(["PENDING", "FAILED"]),
            )
        )
        return {"processed": processed, "failed": failed, "remaining": int(remaining or 0)}

    def rebuild_index(self, user_id: int | None = None) -> dict:
        """从 MySQL 重建指定范围的投影，保留范围之外的向量和待同步任务。"""
        where = self._vector_scope(user_id)
        existing = set(self.collection.get(where=where, include=[]).get("ids") or [])
        conditions = [AgentMemory.tenant_id == self.tenant_id, AgentMemory.project_id == self.project_id]
        if user_id is not None:
            conditions.append(AgentMemory.user_id == int(user_id))
        rows = list(
            self.db.scalars(
                select(AgentMemory).where(
                    *conditions,
                    AgentMemory.status == MEMORY_STATUS_ACTIVE,
                    (AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > utcnow()),
                )
            )
        )
        for row in rows:
            self.collection.upsert(
                ids=[row.memory_id],
                embeddings=[self.embedding.embed_query(row.memory_value)],
                documents=[row.memory_value],
                metadatas=[self._payload(row, status=row.status)],
            )
        stale = existing.difference(row.memory_id for row in rows)
        if stale:
            self.collection.delete(ids=sorted(stale))
        mysql_active = len(rows)
        vectors = len(self.collection.get(where=where, include=[]).get("ids") or [])
        return {
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "embedding_version": self.embedding_version,
            "mysql_active_memories": int(mysql_active or 0),
            "chroma_vectors": int(vectors),
            "consistent": int(mysql_active or 0) == int(vectors),
        }

    def stats(self, user_id: int | None = None) -> dict:
        conditions = [AgentMemory.tenant_id == self.tenant_id, AgentMemory.project_id == self.project_id]
        if user_id is not None:
            conditions.append(AgentMemory.user_id == int(user_id))
        mysql_active = self.db.scalar(
            select(func.count()).select_from(AgentMemory).where(*conditions, AgentMemory.status == MEMORY_STATUS_ACTIVE)
        )
        outbox_pending = self.db.scalar(
            select(func.count())
            .select_from(AgentMemoryOutbox)
            .where(
                *self._outbox_scope(user_id),
                AgentMemoryOutbox.status.in_(["PENDING", "FAILED"]),
            )
        )
        vectors = len(self.collection.get(where=self._vector_scope(user_id), include=[]).get("ids") or [])
        return {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "embedding_version": self.embedding_version,
            "mysql_active_memories": int(mysql_active or 0),
            "chroma_vectors": int(vectors),
            "outbox_pending": int(outbox_pending or 0),
            "consistent": int(mysql_active or 0) == int(vectors),
        }

    # ---------------------------------------------------------------- 会话摘要
    def write_session_summary(
        self,
        user_id: int,
        *,
        session_id: str,
        summary: str,
        message_count: int = 0,
        link_memory: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        summary = self.validate_content(summary)
        existing = self.db.scalar(
            select(AgentSessionSummary).where(
                AgentSessionSummary.tenant_id == self.tenant_id,
                AgentSessionSummary.project_id == self.project_id,
                AgentSessionSummary.session_id == session_id,
            )
        )
        memory = None
        if link_memory:
            memory = self.save(
                user_id,
                summary,
                memory_type="task_summary",
                memory_key=f"session:{session_id}",
                source="agent_session",
                source_ref=session_id,
            )
        if existing is None:
            existing = AgentSessionSummary(
                tenant_id=self.tenant_id,
                user_id=int(user_id),
                project_id=self.project_id,
                session_id=session_id,
            )
            self.db.add(existing)
        existing.user_id = int(user_id)
        existing.summary = summary
        existing.message_count = int(message_count)
        existing.memory_id = memory.memory_id if memory is not None else existing.memory_id
        existing.metadata_json = metadata
        existing.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(existing)
        return {
            "session_id": session_id,
            "memory_id": existing.memory_id,
            "message_count": existing.message_count,
        }


def memory_service(db):
    """按配置构造服务（Chroma 派生索引 + 配置的 embedding provider）。"""
    from app.core.config import get_settings
    from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
    from app.services.agent_memory_index import build_memory_index

    settings = get_settings()
    index = build_memory_index(
        persist_dir=settings.agent_memory_vector_dir,
        project_id=settings.agent_memory_project_id,
        embedding_version=settings.agent_memory_embedding_version,
    )
    return AgentMemoryService(
        db,
        index,
        OpenAICompatibleEmbeddingClient(settings),
        tenant_id=settings.agent_memory_tenant_id,
        project_id=settings.agent_memory_project_id,
        embedding_version=settings.agent_memory_embedding_version,
    )

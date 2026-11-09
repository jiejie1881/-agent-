"""Safe job presentation from existing audit metadata, without schema changes."""

STAGES = ("PARSING", "CHUNKING", "EMBEDDING", "INDEXING", "READY")
JOB_EVENTS = ("RAG_JOB_STARTED", "RAG_JOB_STAGE", "RAG_JOB_COMPLETED", "RAG_JOB_FAILED")


def describe_job(job, events):
    """A stage count is not a percentage or a duration estimate.

    Legacy events without an attempt number remain usable, but unknown timestamps
    stay null. A queued retry must not inherit a prior attempt's completion time.
    """
    events = sorted(events, key=lambda event: event.id)
    starts = [event for event in events if event.action == "RAG_JOB_STARTED" or (
        event.action == "RAG_JOB_STAGE" and (event.changes or {}).get("stage") == "PARSING")]
    matching = [event for event in starts if (event.changes or {}).get("attempt") == job.attempts]
    start = next((event for event in matching if event.action == "RAG_JOB_STARTED"), None)
    if start is None and matching:
        start = matching[0]
    if start is None and starts:
        # Older jobs have no attempt metadata: use their latest parsing boundary.
        legacy = [event for event in starts if "attempt" not in (event.changes or {})]
        start = legacy[-1] if legacy else None
    current = [event for event in events if (start is None or event.id >= start.id)
               and (event.changes or {}).get("attempt", job.attempts) == job.attempts]
    terminal = [event for event in current if event.action in {"RAG_JOB_COMPLETED", "RAG_JOB_FAILED"}]
    terminal = terminal[-1] if terminal else None
    if job.status == "QUEUED":
        start = terminal = None
        current = []
    position = STAGES.index(job.stage) + 1 if job.stage in STAGES else 0
    completed = len(STAGES) if job.status == "SUCCEEDED" else max(0, position - 1)
    if job.status == "QUEUED":
        position = completed = 0
    messages = {
        "OSError": "读取文档或写入本次隔离索引失败，请核对存储后安全重试。",
        "TimeoutError": "本次构建超过时限或租约已过期，请核对任务状态。",
        "LEASE_EXPIRED": "执行器租约已过期；恢复只会标记失败，不会自动重新调用模型。",
        "ConflictError": "文档版本、索引或任务租约已变化，请刷新后核对。",
        "BusinessError": "文档内容或切块结果不满足构建要求，请核对本次文档版本。",
        "UnicodeError": "文档编码无法解析，仅支持有效的 UTF-8 Markdown/TXT。",
        "UnicodeDecodeError": "文档编码无法解析，仅支持有效的 UTF-8 Markdown/TXT。",
    }
    return {
        "started_at": start.created_at if start else None,
        "finished_at": terminal.created_at if terminal and job.status in {"SUCCEEDED", "FAILED"} else None,
        "progress": {"unit": "stages", "current_step": position, "completed_steps": completed, "total_steps": len(STAGES)},
        "failure_message": (messages.get(job.error_type, "构建失败，请按任务编号核对审计记录。") if job.status == "FAILED" else None),
        "timeline": [{"action": event.action, "stage": (event.changes or {}).get("stage"),
                      "attempt": (event.changes or {}).get("attempt"), "created_at": event.created_at}
                     for event in current],
    }

"""Explicit one-shot OFFLINE worker; never accepts a MySQL DSN or auto-provisions."""
import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.knowledge_job_service import KnowledgeJobService
from app.services.knowledge_management_service import MARKER


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one approved private SQLite knowledge job (Hash only)")
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--database", required=True, help="existing knowledge-offline.sqlite3 inside this storage root")
    parser.add_argument("--actor", type=int, required=True)
    parser.add_argument("--job", type=int, required=True)
    parser.add_argument("--offline", action="store_true", required=True)
    args = parser.parse_args(argv)
    root, database = Path(args.storage_root).absolute(), Path(args.database).absolute()
    if (not root.is_dir() or not (root / MARKER).is_file() or database.name != "knowledge-offline.sqlite3"
            or not database.is_file() or not database.resolve().is_relative_to(root.resolve())
            or root.is_symlink() or database.is_symlink()):
        parser.error("Only an existing isolated knowledge-offline.sqlite3 under an explicitly provisioned root is allowed")
    url = URL.create("sqlite+pysqlite", database="file:" + database.as_posix(), query={"mode": "rw", "uri": "true"})
    engine = create_engine(url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            actor = session.get(User, args.actor)
            if actor is None:
                parser.error("Synthetic actor does not exist")
            job = KnowledgeJobService(session, root, offline=True).run(actor, args.job)
            print(json.dumps({"job_id": job.id, "status": job.status, "stage": job.stage,
                              "error_type": job.error_type, "scope": "OFFLINE_SYNTHETIC"}))
            return 0 if job.status == "SUCCEEDED" else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

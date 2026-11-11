"""Unauthenticated process and dependency health checks."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from common.database import get_db
from common.errors import AppException, get_request_id


router = APIRouter()


@router.get("/live")
def liveness(request: Request) -> dict[str, object]:
    """Report that the API process is responding."""

    return {"data": {"status": "ok"}, "request_id": get_request_id(request)}


@router.get("/ready")
def readiness(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    """Check database connectivity, migrations, and an imported seed package."""

    try:
        db.execute(text("SELECT 1"))

        migration_exists = db.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'alembic_version'"
                ")"
            )
        ).scalar()
        if not migration_exists:
            raise AppException("UNAVAILABLE", "数据库迁移未执行", 503)

        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != "0001_initial_schema":
            raise AppException("UNAVAILABLE", "数据库迁移版本不匹配", 503)

        import_runs_exists = db.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'import_runs'"
                ")"
            )
        ).scalar()
        if not import_runs_exists:
            raise AppException("UNAVAILABLE", "数据库迁移未执行", 503)

        seed_exists = db.execute(
            text("SELECT EXISTS (SELECT 1 FROM import_runs WHERE status = 'succeeded')")
        ).scalar()
        if not seed_exists:
            raise AppException("UNAVAILABLE", "未导入种子数据", 503)

        return {"data": {"status": "ready"}, "request_id": get_request_id(request)}
    except AppException:
        raise
    except Exception as exc:
        raise AppException("UNAVAILABLE", "数据库检查失败", 503) from exc

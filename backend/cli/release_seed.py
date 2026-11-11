"""Validate release approval against the actual package, then import it."""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from seed_import.validator import load_and_validate


def verify_package(directory: Path, *, production: bool):
    package = load_and_validate({name: directory / f"{name}.json" for name in ("courses", "nodes", "edges", "exercises")})
    if package.total_errors:
        raise ValueError("种子包未通过四文件校验，请运行 cli/seed_import.py 查看定位")
    if production:
        approval = json.loads((directory / "approval.json").read_text(encoding="utf-8"))
        if approval.get("status") != "approved" or not str(approval.get("reviewer", "")).strip():
            raise ValueError("正式种子尚未由教学专家确认")
        reviewed = date.fromisoformat(approval["reviewed_at"])
        today = datetime.now(timezone(timedelta(hours=8))).date()
        if reviewed > today or approval.get("checksum") != package.checksum:
            raise ValueError("专家确认日期或种子checksum不匹配，请重新审核")
    return package


def main():
    from common.config import settings
    from seed_import.service import import_seed_package

    try:
        package = verify_package(Path(sys.argv[1]), production=settings.environment.lower() != "development")
    except (ValueError, KeyError, OSError) as exc:
        print(f"种子发布检查失败：{exc}", file=sys.stderr)
        return 1
    report = import_seed_package(package, operator=os.environ.get("SEED_OPERATOR", "deploy@system"))
    print(report.model_dump_json(indent=2))
    return 0 if report.status in {"succeeded", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

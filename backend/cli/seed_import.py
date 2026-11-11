"""Command-line entry point for importing the four-file seed package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from seed_import.validator import compute_checksum, load_and_validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入并校验知识图谱种子数据")
    for name in ("courses", "nodes", "edges", "exercises"):
        parser.add_argument(f"--{name}", required=True, type=Path, help=f"{name}.json路径")
    parser.add_argument("--operator", default="system", help="执行导入的运维人员标识")
    args = parser.parse_args(argv)

    from seed_import.service import import_seed_package

    package = load_and_validate(
        {
            "courses": args.courses,
            "nodes": args.nodes,
            "edges": args.edges,
            "exercises": args.exercises,
        }
    )
    report = import_seed_package(package, operator=args.operator)
    if report.status == "succeeded":
        headline = f"导入成功：run_id={report.run_id}"
    elif report.status == "skipped":
        headline = f"跳过：checksum相同，run_id={report.run_id}"
    else:
        headline = f"导入失败：run_id={report.run_id}"
    print(headline)
    print(report.model_dump_json(indent=2))
    return 0 if report.status in {"succeeded", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

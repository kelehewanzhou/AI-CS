"""Write a reproducible manifest without environment variables or secrets."""
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = ("backend/requirements.lock", "web/pnpm-lock.yaml", "docker-compose.yml", "docker-compose.tls.yml", "backend/Dockerfile", "nginx/Dockerfile")
    artifacts = {file: {"sha256": hashlib.sha256((ROOT / file).read_bytes()).hexdigest()} for file in files}
    images = sorted(set(re.findall(r"(?:postgres:17|python:3\.13-slim|node:24-alpine|nginx:1\.30\.6)@sha256:[0-9a-f]{64}", "\n".join((ROOT / file).read_text(encoding="utf-8") for file in files))))
    data = {"recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "source_artifacts": artifacts, "pinned_base_images": images, "application_image_ids": "Not built: Docker daemon unavailable; record IDs and registry digests on deployment host"}
    target = ROOT / "docs/验收证据/task9-versions.json"
    target.parent.mkdir(exist_ok=True, parents=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()

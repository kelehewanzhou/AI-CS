"""Verify recorded versions, license checksums and dependency lock alignment."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    # Git may check text out as LF or CRLF on different operating systems.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "third_party/components.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    lock = (ROOT / "backend/requirements.lock").read_text(encoding="utf-8")
    web_lock = (ROOT / "web/pnpm-lock.yaml").read_text(encoding="utf-8")
    requirements = (ROOT / "backend/requirements.in").read_text(encoding="utf-8")
    records = {(r["ecosystem"], r["name"].lower()): r for r in manifest["components"]}
    errors = []
    for group in ("dependencies", "devDependencies"):
        for name, version in package[group].items():
            record = records.get(("npm", name.lower()))
            if not record or record["version"] != version:
                errors.append(f"Unrecorded or mismatched direct npm version: {name}")
            if f"specifier: {version}" not in web_lock:
                errors.append(f"npm lock importer version missing: {name}")
    for name, version in re.findall(r"^([\w-]+)(?:\[[^\]]+\])?==([^\s]+)", requirements, re.M):
        record = records.get(("pypi", name.lower()))
        if not record or record["version"] != version:
            errors.append(f"Unrecorded or mismatched direct Python version: {name}")
        if not re.search(rf"^{re.escape(name.lower())}(?:\[[^\]]+\])?=={re.escape(version)}\s", lock, re.M):
            errors.append(f"Python lock version missing: {name}")
    if package["packageManager"] != "pnpm@" + records[("npm", "pnpm")]["version"]:
        errors.append("Package manager version mismatch")
    for record in manifest["components"] + manifest.get("native_dependency_licenses", []):
        if not record.get("license") or not record.get("license_files"):
            errors.append(f"Missing license evidence: {record['name']}")
        for entry in record.get("license_files", []):
            path = (ROOT / entry["path"]).resolve()
            if not path.is_relative_to((ROOT / "third_party/licenses").resolve()) or not path.is_file():
                errors.append(f"Missing/invalid license path: {entry['path']}")
            elif digest(path) != entry["sha256"]:
                errors.append(f"License checksum mismatch: {entry['path']}")
    for artifact, expected in manifest["source_sha256"].items():
        actual = digest(ROOT / artifact)
        if actual != expected:
            errors.append(f"Reviewed source changed; repeat review: {artifact}")
    for dockerfile, target in (("backend/Dockerfile", "/app/third_party/licenses/"),
                               ("nginx/Dockerfile", "/usr/share/nginx/html/third-party-licenses/")):
        if f"COPY third_party/licenses/ {target}" not in (ROOT / dockerfile).read_text(encoding="utf-8"):
            errors.append(f"License delivery copy missing: {dockerfile}")
    print(json.dumps({"passed": not errors, "components": len(manifest["components"]), "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

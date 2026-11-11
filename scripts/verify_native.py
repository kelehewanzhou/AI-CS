"""Verify Task 9 with a disposable PostgreSQL cluster and real Nginx on Windows.

This complements Compose acceptance when Docker is unavailable. No existing
database is used. All data, generated config and logs stay in a new temp folder.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url, process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Temporary server exited; inspect the temporary logs")
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Temporary server did not become ready")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--nginx-dir", type=Path, required=True)
    parser.add_argument("--bash", type=Path, default=Path("C:/Program Files/Git/bin/bash.exe"))
    parser.add_argument("--output", type=Path, default=ROOT / "docs/验收证据/task9-native.json")
    parser.add_argument("--browser", action="store_true", help="Run optional Playwright/Edge browser paths")
    args = parser.parse_args()
    scratch = Path(tempfile.mkdtemp(prefix="kglearn-task9-"))
    env = os.environ.copy()
    env["PATH"] = str(args.pg_bin.resolve()) + os.pathsep + env["PATH"]
    env["PYTHONIOENCODING"] = "utf-8"
    pg_port, api_port, nginx_port = port(), port(), port()
    origin = f"http://127.0.0.1:{nginx_port}"
    admin_password, migration_password, app_password = (secrets.token_hex(24) for _ in range(3))
    admin = "kglearn_admin"
    env.update(POSTGRES_USER=admin, POSTGRES_DB="kglearn", POSTGRES_PASSWORD=admin_password,
               DB_PASSWORD=app_password, DB_MIGRATION_PASSWORD=migration_password,
               PGHOST="127.0.0.1", PGPORT=str(pg_port), PGUSER=admin, PGPASSWORD=admin_password,
               ALLOWED_ORIGINS=origin, SESSION_SECRET_KEY=secrets.token_hex(32), ENVIRONMENT="development",
               DATABASE_URL=f"postgresql+psycopg://kglearn_app:{app_password}@127.0.0.1:{pg_port}/kglearn",
               KGLEARN_TEST_MIGRATION_URL=f"postgresql+psycopg://kglearn_migrator:{migration_password}@127.0.0.1:{pg_port}/kglearn",
               KGLEARN_TEST_HTTP_URL=origin, KGLEARN_NATIVE_ACCEPTANCE="1")
    password_file = scratch / "init-password"
    password_file.write_text(admin_password, encoding="utf-8")
    os.chmod(password_file, 0o600)
    nginx = backend = None
    pg_started = False
    started = time.monotonic()
    evidence = {"date": datetime.now(timezone(timedelta(hours=8))).isoformat(), "mode": "isolated native PostgreSQL/Nginx; Docker not exercised"}

    def run(command, *, cwd=ROOT, capture=True, variables=env):
        result = subprocess.run([str(item) for item in command], cwd=cwd, env=variables,
                                stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None,
                                text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            # Test output and native tool diagnostics contain no environment dump.
            if result.stdout:
                print(result.stdout)
            raise RuntimeError(f"Verification command failed: {Path(str(command[0])).name}")
        return result.stdout or ""

    try:
        # initdb drops the Administrators group from its Windows token. Give the
        # current account explicit access to this new isolated directory.
        if os.name == "nt":
            identity = next(csv.reader([run(["whoami", "/user", "/fo", "csv", "/nh"]).strip()]))
            run(["icacls", scratch, "/grant", f"*{identity[1]}:(OI)(CI)F", "/T", "/Q"])
        run([args.pg_bin / "initdb.exe", "-D", scratch / "pgdata", "-U", admin, "--pwfile", password_file, "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C"])
        password_file.unlink()
        run([args.pg_bin / "pg_ctl.exe", "-D", scratch / "pgdata", "-l", scratch / "postgres.log", "-o", f"-h 127.0.0.1 -p {pg_port}", "-w", "start"], capture=False)
        pg_started = True
        evidence["postgres_version"] = run([args.pg_bin / "postgres.exe", "--version"]).strip()
        run([args.pg_bin / "createdb.exe", "kglearn"])
        run([args.pg_bin / "psql.exe", "-X", "-v", "ON_ERROR_STOP=1", "-d", "kglearn", "-f", ROOT / "database/init/roles.sql.inc"])
        migration_env = env | {"DATABASE_URL": env["KGLEARN_TEST_MIGRATION_URL"]}
        run([sys.executable, "-m", "cli.migrate"], cwd=ROOT / "backend", variables=migration_env)
        # Running a second time proves one-shot migration/grants are repeatable.
        run([sys.executable, "-m", "cli.migrate"], cwd=ROOT / "backend", variables=migration_env)

        nginx_root = scratch / "nginx"
        (nginx_root / "conf.d").mkdir(parents=True)
        (nginx_root / "snippets").mkdir()
        (nginx_root / "logs").mkdir()
        (nginx_root / "temp").mkdir()
        runtime = scratch / "runtime"
        runtime.mkdir()
        for file in (ROOT / "nginx/snippets").glob("*.conf"):
            content = file.read_text(encoding="utf-8")
            content = content.replace("/etc/nginx/snippets", (nginx_root / "snippets").as_posix())
            content = content.replace("/usr/share/nginx/html", (ROOT / "web/out").as_posix())
            content = content.replace("/var/run/kglearn", runtime.as_posix()).replace("backend:8000", f"127.0.0.1:{api_port}")
            (nginx_root / "snippets" / file.name).write_text(content, encoding="utf-8")
        maps = (ROOT / "nginx/templates/maps.conf.template").read_text(encoding="utf-8").replace("${ORIGIN_ENTRIES}", f'    "{origin}" 1;').replace("${TRUSTED_PROXY_ENTRIES}", "")
        (nginx_root / "conf.d/00-maps.conf").write_text(maps, encoding="utf-8")
        server = (ROOT / "nginx/templates/http.conf.template").read_text(encoding="utf-8").replace("${NGINX_SERVER_NAME}", "localhost").replace("listen 80;", f"listen 127.0.0.1:{nginx_port};").replace("/etc/nginx/snippets", (nginx_root / "snippets").as_posix())
        (nginx_root / "conf.d/default.conf").write_text(server, encoding="utf-8")
        config = (ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")
        config = config.replace("user nginx;", "").replace("/dev/stderr", (nginx_root / "logs/error.log").as_posix()).replace("/dev/stdout", (nginx_root / "logs/access.log").as_posix())
        config = config.replace("/var/run/nginx.pid", (nginx_root / "nginx.pid").as_posix()).replace("/etc/nginx/mime.types", (args.nginx_dir / "conf/mime.types").resolve().as_posix()).replace("/etc/nginx/conf.d", (nginx_root / "conf.d").as_posix())
        (nginx_root / "nginx.conf").write_text(config, encoding="utf-8")
        nginx_cmd = [args.nginx_dir / "nginx.exe", "-p", nginx_root.as_posix() + "/", "-c", "nginx.conf"]
        run(nginx_cmd + ["-t"])
        evidence["nginx_version"] = run([args.nginx_dir / "nginx.exe", "-v"]).strip()
        backend_log = (scratch / "backend.log").open("w", encoding="utf-8")
        backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(api_port), "--no-access-log", "--no-proxy-headers"], cwd=ROOT / "backend", env=env, stdout=backend_log, stderr=subprocess.STDOUT)
        wait_http(f"http://127.0.0.1:{api_port}/health/live", backend)
        nginx = subprocess.Popen([str(item) for item in nginx_cmd], cwd=nginx_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_http(origin + "/nginx-live", nginx)
        output = run([sys.executable, "-m", "pytest", "backend/tests/test_deployment_postgres.py", "-q"])
        print(output)
        evidence["postgres_and_proxy_tests"] = output.strip().split("\n")[-1]

        if args.browser:
            # Restart the isolated proxy to reset the login rate bucket between
            # the deliberate rate-limit tests and the four browser logins.
            run(nginx_cmd + ["-s", "quit"])
            nginx.wait(timeout=10)
            nginx = subprocess.Popen([str(item) for item in nginx_cmd], cwd=nginx_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_http(origin + "/nginx-live", nginx)
            browser_result = run([sys.executable, ROOT / "scripts/verify_browser.py"])
            evidence["browser_acceptance"] = json.loads(browser_result.strip().splitlines()[-1])
            print("Browser student/teacher paths and retry acceptance passed")

        # Execute the actual container backup and restore shell scripts unchanged.
        backup_dir = scratch / "backup"
        backup_env = env | {"BACKUP_DIR": backup_dir.as_posix(), "VERIFY_SQL": (ROOT / "database/verify_restore.sql").as_posix(), "MSYS_NO_PATHCONV": "1"}
        before = time.monotonic()
        dump = run([args.bash, ROOT / "scripts/backup.sh", "daily"], variables=backup_env).strip().splitlines()[-1]
        restored = run([args.bash, ROOT / "scripts/restore.sh", dump, "--yes"], variables=backup_env)
        print(restored)
        evidence["restore_seconds"] = round(time.monotonic() - before, 3)
        evidence["restored_counts_and_foreign_keys"] = restored.strip().splitlines()[2:]
        # Integrity failure must stop before replacing the rehearsal database.
        dump_path = Path(dump)
        original = dump_path.read_bytes()
        dump_path.write_bytes(original + b"tampered")
        failed = subprocess.run([str(args.bash), str(ROOT / "scripts/restore.sh"), dump, "--yes"], cwd=ROOT, env=backup_env, capture_output=True)
        assert failed.returncode != 0
        dump_path.write_bytes(original)
        evidence["tampered_backup_rejected"] = True
        # Maintenance does not break Nginx's process health endpoint.
        (runtime / "maintenance").touch()
        maintenance = httpx.get(origin + "/api/v1/graph/subgraph")
        assert maintenance.status_code == 503 and maintenance.json()["code"] == "UNAVAILABLE"
        assert httpx.get(origin + "/nginx-live").status_code == 200
        (runtime / "maintenance").unlink()
        backend.terminate()
        backend.wait(timeout=10)
        unavailable = httpx.get(origin + "/api/v1/health/live")
        assert unavailable.status_code == 503 and unavailable.json()["code"] == "UNAVAILABLE"
        assert unavailable.headers["x-request-id"] == unavailable.json()["request_id"]
        evidence["maintenance_and_upstream_failure"] = "503 UNAVAILABLE, matching request_id; process probe remains 200"
        access = (nginx_root / "logs/access.log").read_text(encoding="utf-8")
        logs = access + (scratch / "backend.log").read_text(encoding="utf-8")
        assert all(value not in logs for value in (admin_password, migration_password, app_password, "initial-test-123456", "changed-test-123456", '"Cookie"', '"password"', "Traceback (most recent call last)"))
        evidence["log_privacy"] = "No tested passwords, Cookie header, request body or stack trace in application/access logs"
        evidence["total_seconds"] = round(time.monotonic() - started, 3)
        evidence["limits"] = ["Docker image build, Compose orchestration and Linux container startup not run", "Production certificate and school gateway not available", "Expert approval/signatures pending", "Offsite encrypted transfer requires institution destination/key; not run"]
        if not args.browser:
            evidence["limits"].append("Browser interactions not run")
        args.output.parent.mkdir(exist_ok=True, parents=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {args.output}")
        print(f"Temporary diagnostic logs: {scratch}")
        return 0
    finally:
        if nginx is not None:
            subprocess.run([str(item) for item in nginx_cmd] + ["-s", "quit"], cwd=nginx_root, env=env, capture_output=True)
            try:
                nginx.wait(timeout=10)
            except subprocess.TimeoutExpired:
                nginx.terminate()
        if backend is not None and backend.poll() is None:
            backend.terminate()
            backend.wait(timeout=10)
        if pg_started:
            subprocess.run([str(args.pg_bin / "pg_ctl.exe"), "-D", str(scratch / "pgdata"), "-m", "fast", "-w", "stop"], env=env, capture_output=True)
        print(f"Isolated runtime stopped; diagnostics: {scratch}")


if __name__ == "__main__":
    raise SystemExit(main())

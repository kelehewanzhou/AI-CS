"""Cross-platform release operations. Uses Docker's dotenv parser, never a shell."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"


def run(args, *, capture=False, env=None):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, text=True,
                          encoding="utf-8", stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


class Operations:
    def __init__(self, *, version=None, tls=False):
        if not shutil.which("docker"):
            raise ValueError("Docker CLI不可用，请在安装Docker Engine/Compose v2的目标机执行")
        self.env = os.environ.copy()
        self.command = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(ROOT / ".env")]
        release = RUNTIME / "release.env"
        if release.exists():
            self.command += ["--env-file", str(release)]
        # Read only flags with a narrow grammar. Docker parses every actual value.
        text = (ROOT / ".env").read_text(encoding="utf-8-sig")
        self.tls = tls or bool(re.search(r"(?m)^COMPOSE_TLS=[\"']?1[\"']?\s*$", text))
        self.command += ["-f", str(ROOT / "docker-compose.yml")]
        if self.tls:
            self.command += ["-f", str(ROOT / "docker-compose.tls.yml")]
        if version:
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", version) or version == "latest":
                raise ValueError("使用明确版本号，例如v1.0.0；不能使用latest")
            self.env["VERSION"] = version
        self.config = json.loads(self.compose("config", "--format", "json", capture=True).stdout)
        self.api = self.config["services"]["backend"]["environment"]
        self.version = self.config["services"]["backend"]["image"].rsplit(":", 1)[1]

    def compose(self, *args, capture=False):
        return run(self.command + list(args), capture=capture, env=self.env)

    def check(self):
        services = self.config["services"]
        pg = services["postgres"]["environment"]
        passwords = [str(pg[name]) for name in ("POSTGRES_PASSWORD", "DB_PASSWORD", "DB_MIGRATION_PASSWORD")]
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{16,}", value) for value in passwords) or len(set(passwords)) != 3:
            raise ValueError("数据库三类账号须使用不同的16位以上URL安全随机密码")
        secret = str(self.api["SESSION_SECRET_KEY"])
        if len(secret) < 64 or "generate-random" in secret:
            raise ValueError("SESSION_SECRET_KEY须为至少64位随机字符串")
        for service, username, password in (("backend", "kglearn_app", passwords[1]), ("migrate", "kglearn_migrator", passwords[2])):
            connection = urlsplit(services[service]["environment"]["DATABASE_URL"])
            if (connection.scheme, connection.username, connection.password, connection.hostname, connection.path) != ("postgresql+psycopg", username, password, "postgres", "/kglearn"):
                raise ValueError(f"{service}数据库URL须与对应账号密码、postgres服务及kglearn库一致")
        production = self.api["ENVIRONMENT"].lower() != "development"
        origins = self.api["ALLOWED_ORIGINS"].split(",")
        if any(not re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::[0-9]+)?", item) for item in origins):
            raise ValueError("ALLOWED_ORIGINS须为精确Origin，逗号分隔且不含空格、路径或通配符")
        if production and any(not origin.startswith("https://") for origin in origins):
            raise ValueError("生产环境仅允许外部HTTPS Origin")
        if production and not self.tls and not services["nginx"]["environment"].get("NGINX_TRUSTED_PROXIES"):
            raise ValueError("生产环境须启用本机TLS，或配置学校HTTPS网关的可信代理网段")
        if self.tls and any(not (ROOT / "nginx/ssl" / name).is_file() for name in ("fullchain.pem", "privkey.pem")):
            raise ValueError("请提供nginx/ssl/fullchain.pem和privkey.pem")
        sys.path.insert(0, str(ROOT / "backend"))
        from cli.release_seed import verify_package

        source = services["seed-import"]["volumes"][0]["source"]
        package = verify_package(Path(source), production=production)
        for directory in (RUNTIME, ROOT / "backup", ROOT / "credentials"):
            directory.mkdir(exist_ok=True, mode=0o700)
        # The backend image runs as uid 1000. Only its credential output is writable.
        if os.name != "nt" and os.geteuid() == 0:
            os.chown(ROOT / "credentials", 1000, 1000)
        print(f"配置与种子校验通过：{self.version} / checksum={package.checksum}")

    def backup(self, kind="daily", *, offsite=False):
        result = self.compose("exec", "-T", "postgres", "bash", "/opt/kglearn/backup.sh", kind, capture=True)
        path = result.stdout.strip().splitlines()[-1]
        if not re.fullmatch(r"/backup/kglearn_[A-Za-z0-9_]+\.dump", path):
            raise ValueError("备份脚本未返回预期文件名")
        print(f"备份已验证：{path}")
        if offsite:
            run(["bash", "scripts/backup-offsite.sh", str(ROOT / "backup" / Path(path).name)])
            print("加密异机副本已上传")
        return path

    def deploy(self):
        self.check()
        lock = RUNTIME / "deploy.lock"
        # Exclusive creation also prevents concurrent maintenance releases.
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        maintenance = RUNTIME / "maintenance"
        state = {"version": self.version, "phase": "build", "backup": None}

        def record():
            state["recorded_at"] = datetime.now().astimezone().isoformat()
            (RUNTIME / "deployment.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        entered_maintenance = False
        try:
            record()
            self.compose("build", "backend", "nginx")
            self.compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", "postgres")
            maintenance.touch()
            entered_maintenance = True
            self.compose("stop", "backend")
            # Back up after writes have stopped, so a recovery loses no later writes.
            state["phase"] = "backup"
            record()
            state["backup"] = self.backup("release")
            for service in ("migrate", "seed-import"):
                state["phase"] = service
                record()
                self.compose("up", "--no-deps", "--force-recreate", "--exit-code-from", service, service)
            state["phase"] = "start"
            record()
            for service in ("backend", "nginx"):
                self.compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "--wait-timeout", "180", service)
            # Probe through the real Nginx locations before exposing the application.
            # /nginx-live is an independent container-process health probe.
            maintenance.unlink()
            if self.tls:
                host = self.config["services"]["nginx"]["environment"]["NGINX_SERVER_NAME"]
                self.compose("exec", "-T", "nginx", "curl", "--fail", "--silent", "--resolve", f"{host}:443:127.0.0.1", f"https://{host}/health/ready")
            else:
                self.compose("exec", "-T", "nginx", "curl", "--fail", "--silent", "http://localhost/health/ready")
            (RUNTIME / "release.env").write_text(f"VERSION={self.version}\n", encoding="utf-8")
            state["phase"] = "succeeded"
            record()
            print(f"部署完成：{self.version}")
        except BaseException:
            state["phase"] = "failed:" + state["phase"]
            record()
            if entered_maintenance:
                maintenance.touch()
                try:
                    self.compose("stop", "backend")
                except subprocess.CalledProcessError:
                    pass
                print("发布失败，维护标记已保留；修复后重试，不自动降级数据库。", file=sys.stderr)
            raise
        finally:
            lock.unlink()


def init_env():
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = {name: secrets.token_hex(24) for name in ("DB_ADMIN_PASSWORD", "DB_MIGRATION_PASSWORD", "DB_PASSWORD")}
    values["SESSION_SECRET_KEY"] = secrets.token_hex(32)
    for key, value in values.items():
        template = re.sub(rf"(?m)^{key}=.*$", f"{key}={value}", template)
    template = template.replace("REPLACE_WITH_DB_PASSWORD", values["DB_PASSWORD"]).replace("REPLACE_WITH_DB_MIGRATION_PASSWORD", values["DB_MIGRATION_PASSWORD"])
    # Never overwrite an existing environment or print generated secrets.
    fd = os.open(ROOT / ".env", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(template)
    for directory in (RUNTIME, ROOT / "backup", ROOT / "credentials"):
        directory.mkdir(exist_ok=True, mode=0o700)
    print("已生成本地.env；未覆盖既有配置，密码未输出。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tls", action="store_true")
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("init-env")
    for name in ("check", "build", "deploy"):
        sub = subs.add_parser(name)
        sub.add_argument("version", nargs="?")
    backup = subs.add_parser("backup")
    backup.add_argument("--offsite", action="store_true")
    restore = subs.add_parser("restore")
    restore.add_argument("file", help="Container path /backup/kglearn_*.dump")
    restore.add_argument("--yes", action="store_true")
    account = subs.add_parser("create-account")
    account.add_argument("username")
    account.add_argument("role", choices=("student", "teacher"))
    subs.add_parser("status")
    args = parser.parse_args()
    try:
        if args.action == "init-env":
            init_env()
            return 0
        ops = Operations(version=getattr(args, "version", None), tls=args.tls)
        if args.action == "check":
            ops.check()
        elif args.action == "build":
            ops.check()
            ops.compose("build", "backend", "nginx")
        elif args.action == "deploy":
            ops.deploy()
        elif args.action == "backup":
            ops.backup(offsite=args.offsite)
        elif args.action == "restore":
            ops.compose("exec", *(["-T"] if args.yes else []), "postgres", "bash", "/opt/kglearn/restore.sh", args.file, *(["--yes"] if args.yes else []))
        elif args.action == "create-account":
            ops.compose("run", "--rm", "--no-deps", "-v", f"{ROOT / 'credentials'}:/app/backend/tmp", "migrate", "python", "-m", "cli.accounts", "create", "--username", args.username, "--role", args.role)
        else:
            ops.compose("ps", "--all")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError):
        # Do not echo command/config output: it can contain credentials.
        print("操作失败。检查Docker、环境/种子配置、部署阶段记录及对应服务日志；配置输出未打印。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

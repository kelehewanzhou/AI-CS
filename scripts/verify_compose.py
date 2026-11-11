"""Check Compose configurations with the official CLI, without a Docker daemon."""
import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-executable", required=True, type=Path)
    args = parser.parse_args()
    env = os.environ.copy()
    admin, app, migration = (secrets.token_hex(24) for _ in range(3))
    env.update(DB_ADMIN_PASSWORD=admin, DB_PASSWORD=app, DB_MIGRATION_PASSWORD=migration,
               SESSION_SECRET_KEY=secrets.token_hex(32), ALLOWED_ORIGINS="http://localhost:8080", ENVIRONMENT="development",
               DATABASE_URL=f"postgresql+psycopg://kglearn_app:{app}@postgres:5432/kglearn",
               MIGRATION_DATABASE_URL=f"postgresql+psycopg://kglearn_migrator:{migration}@postgres:5432/kglearn")

    def config(*files):
        command = [str(args.compose_executable)]
        for file in files:
            command += ["-f", str(ROOT / file)]
        result = subprocess.run(command + ["config", "--format", "json"], cwd=ROOT, env=env, capture_output=True, encoding="utf-8", check=True)
        return json.loads(result.stdout)

    base = config("docker-compose.yml")
    tls = config("docker-compose.yml", "docker-compose.tls.yml")
    services = base["services"]
    assert set(services) == {"postgres", "migrate", "seed-import", "backend", "nginx"}
    assert "ports" not in services["postgres"] and "ports" not in services["backend"]
    for service, dependency, condition in (("migrate", "postgres", "service_healthy"), ("seed-import", "migrate", "service_completed_successfully"), ("backend", "seed-import", "service_completed_successfully"), ("nginx", "backend", "service_healthy")):
        assert services[service]["depends_on"][dependency]["condition"] == condition
    assert all(service["logging"]["options"] == {"max-size": "10m", "max-file": "5"} for service in services.values())
    assert all(port["host_ip"] == "127.0.0.1" for port in services["nginx"]["ports"])
    assert any(port["target"] == 443 for port in tls["services"]["nginx"]["ports"])
    version = subprocess.run([str(args.compose_executable), "version", "--short"], capture_output=True, encoding="utf-8", check=True).stdout.strip()
    record = {"compose_version": version, "base_config_valid": True, "tls_config_valid": True, "services": sorted(services), "dependency_order_verified": True, "internal_database_and_backend": True, "log_rotation_verified": True, "docker_daemon_execution": False}
    target = ROOT / "docs/验收证据/task9-compose.json"
    target.parent.mkdir(exist_ok=True, parents=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Compose {version}: base/TLS configuration, dependency order, network exposure and log rotation passed")


if __name__ == "__main__":
    main()

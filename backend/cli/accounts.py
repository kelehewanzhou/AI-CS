"""Provision student and teacher accounts from the command line."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    # Support both ``python cli/accounts.py`` from backend and
    # ``python backend/cli/accounts.py`` from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from argon2 import PasswordHasher
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.models import User
from common.database import engine


ph = PasswordHasher()
USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,64}$")


def generate_password(length: int = 16) -> str:
    """Generate a 16-character password containing all three required classes."""

    if length < 3:
        raise ValueError("password length must be at least 3")
    groups = (string.ascii_letters, string.digits, "!@#$%")
    characters = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def _credential_file(username: str, role: str, password: str) -> Path:
    output_dir = Path("./tmp")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(output_dir, 0o700)
    except OSError:
        pass
    output_file = output_dir / f"credentials_{datetime.now().strftime('%Y%m%d')}.txt"
    with output_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{username}\t{role}\t{password}\n")
    try:
        os.chmod(output_file, 0o600)
    except OSError:
        # Windows ACLs are managed separately; the file is still created only
        # in the operator's local working directory.
        pass
    return output_file


def create_account(username: str, role: str) -> int:
    """Create one account without ever storing the temporary password."""

    if not USERNAME_PATTERN.fullmatch(username):
        print("错误：用户名必须为3-64位小写字母、数字或下划线")
        return 1
    if role not in {"student", "teacher"}:
        print("错误：role必须为student或teacher")
        return 1

    temporary_password = generate_password()
    user = User(
        username=username,
        password_hash=ph.hash(temporary_password),
        role=role,
        must_change_password=True,
    )
    try:
        with Session(engine) as db:
            if db.query(User).filter(User.username == username).first():
                print(f"错误：用户名{username}已存在")
                return 1
            db.add(user)
            db.commit()
    except IntegrityError:
        print(f"错误：用户名{username}已存在")
        return 1

    output_file = _credential_file(username, role, temporary_password)
    print(f"账号创建成功：{username} ({role})")
    print(f"临时密码已写入：{output_file}")
    print("请通过安全渠道发放，发放后删除该文件")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="账号管理CLI")
    subparsers = parser.add_subparsers(dest="command")
    create_parser = subparsers.add_parser("create", help="创建账号")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument(
        "--role", required=True, choices=["student", "teacher"]
    )
    args = parser.parse_args()

    if args.command == "create":
        return create_account(args.username, args.role)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Гейт для make migrate-down / migrate-reset: пускает только локальный DATABASE_URL.

DATABASE_URL берётся из окружения, затем из .env, затем из alembic.ini (fallback).
Хост обязан быть localhost / 127.0.0.1 / ::1 — иначе exit 1.
"""

import configparser
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def resolve_database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    root = Path(__file__).resolve().parent.parent
    env_file = root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip("\"'")

    ini = configparser.ConfigParser()
    if ini.read(root / "alembic.ini"):
        return ini.get("alembic", "sqlalchemy.url", fallback=None)
    return None


def main() -> int:
    url = resolve_database_url()
    if not url:
        print(
            "require_local_db: DATABASE_URL не найден (env / .env / alembic.ini)", file=sys.stderr
        )
        return 1
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    if host not in LOCAL_HOSTS:
        print(
            f"require_local_db: хост DATABASE_URL не локальный: {host!r}. "
            "downgrade разрешён только для localhost / 127.0.0.1 / ::1.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

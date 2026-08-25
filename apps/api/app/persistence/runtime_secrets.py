from __future__ import annotations

import os
import re
import secrets
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import URL

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,62}$")
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_MAX_SECRET_BYTES = 64 * 1024


def initialize_runtime_secrets(
    target: Path,
    *,
    database_host: str,
    database_port: int,
    database_name: str,
    database_user: str,
) -> None:
    """Create the project-scoped database password and DSN files idempotently."""

    if not _IDENTIFIER.fullmatch(database_name):
        raise ValueError("POSTGRES_DB must be a non-empty safe PostgreSQL identifier.")
    if not _IDENTIFIER.fullmatch(database_user):
        raise ValueError("POSTGRES_USER must be a non-empty safe PostgreSQL identifier.")
    if not _HOST.fullmatch(database_host):
        raise ValueError("DATABASE_HOST must be a non-empty DNS hostname.")
    if not 1 <= database_port <= 65_535:
        raise ValueError("DATABASE_PORT must be between 1 and 65535.")

    target.mkdir(parents=True, exist_ok=True)
    password_path = target / "postgres_password"
    if password_path.exists():
        password = _read_existing_password(password_path)
    else:
        password = secrets.token_urlsafe(48)
        _atomic_write(password_path, password)

    database_url = URL.create(
        "postgresql+asyncpg",
        username=database_user,
        password=password,
        host=database_host,
        port=database_port,
        database=database_name,
    ).render_as_string(hide_password=False)
    _atomic_write(target / "database_url", database_url)


def initialize_writable_directory(target: Path, *, uid: int, gid: int) -> None:
    """Give one explicit runtime volume root to the long-lived non-root app user."""

    target.mkdir(parents=True, exist_ok=True)
    chown = getattr(os, "chown", None)
    if chown is None:
        raise RuntimeError("Writable-volume ownership initialization requires a POSIX host.")
    chown(target, uid, gid)
    os.chmod(target, 0o750)


def initialize_provider_secret(
    target: Path,
    *,
    provider: Literal["deepseek", "openai"],
    secret: str,
) -> None:
    """Persist one stdin-delivered provider key in an API-only named volume."""

    normalized = secret.strip()
    if not normalized or "\x00" in normalized:
        raise ValueError("Provider secret must contain non-empty UTF-8 text.")
    if len(normalized.encode("utf-8")) > _MAX_SECRET_BYTES:
        raise ValueError("Provider secret exceeds the 64 KiB limit.")

    target.mkdir(parents=True, exist_ok=True)
    selected = target / f"{provider}_api_key"
    unselected = target / (
        "openai_api_key" if provider == "deepseek" else "deepseek_api_key"
    )
    if unselected.exists():
        os.chmod(unselected, 0o600)
    unselected.unlink(missing_ok=True)
    _atomic_write(selected, normalized)


def _read_existing_password(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Existing PostgreSQL runtime secret is invalid.")
    password = path.read_text(encoding="utf-8").strip()
    if not password or "\x00" in password:
        raise ValueError("Existing PostgreSQL runtime secret is invalid.")
    return password


def _atomic_write(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        if path.exists():
            os.chmod(path, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o444)
    finally:
        temporary.unlink(missing_ok=True)


def _read_provider_secret_from_stdin() -> str:
    payload = sys.stdin.buffer.read(_MAX_SECRET_BYTES + 1)
    if len(payload) > _MAX_SECRET_BYTES:
        raise ValueError("Provider secret exceeds the 64 KiB limit.")
    try:
        return payload.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Provider secret must contain UTF-8 text.") from exc


def main() -> None:
    parser = ArgumentParser(add_help=False)
    parser.add_argument("--provider-secret", choices=("deepseek", "openai"))
    arguments = parser.parse_args()
    if arguments.provider_secret:
        provider = arguments.provider_secret
        initialize_provider_secret(
            Path(
                os.environ.get(
                    "PROVIDER_SECRET_DIRECTORY", "/run/agent-studio-provider-secrets"
                )
            ),
            provider=provider,
            secret=_read_provider_secret_from_stdin(),
        )
        print(f"{provider.capitalize()} provider secret is ready.")
        return

    target = Path(os.environ.get("RUNTIME_SECRET_DIRECTORY", "/run/agent-studio-secrets"))
    try:
        port = int(os.environ.get("DATABASE_PORT", "5432"))
    except ValueError as exc:
        raise ValueError("DATABASE_PORT must be an integer.") from exc
    initialize_runtime_secrets(
        target,
        database_host=os.environ.get("DATABASE_HOST", "db"),
        database_port=port,
        database_name=os.environ.get("POSTGRES_DB", "agent_studio"),
        database_user=os.environ.get("POSTGRES_USER", "agent_studio"),
    )
    knowledge_path = os.environ.get("KNOWLEDGE_STORAGE_PATH")
    if knowledge_path:
        initialize_writable_directory(
            Path(knowledge_path),
            uid=int(os.environ.get("APP_UID", "10001")),
            gid=int(os.environ.get("APP_GID", "10001")),
        )
    print("Runtime secrets and writable volume ownership are ready.")


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_production_images_are_pinned_non_root_and_do_not_use_dev_servers() -> None:
    api = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    web = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")

    assert "python:3.12-slim-bookworm" in api
    assert "node:24-bookworm-slim" in web
    assert ":latest" not in api + web
    assert "USER 10001:10001" in api
    assert "USER 10001:10001" in web
    assert "--reload" not in api
    assert "next dev" not in web
    assert "pnpm install --frozen-lockfile" in web
    assert "ARG DEEPSEEK_API_KEY" not in api + web
    assert "ARG OPENAI_API_KEY" not in api + web
    assert "ENV DEEPSEEK_API_KEY" not in api + web
    assert "ENV OPENAI_API_KEY" not in api + web
    assert "pip uninstall --yes pip setuptools wheel" in api
    assert "-name tests -prune" in api


def test_compose_keeps_database_internal_and_secrets_out_of_web() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    web_section = compose.split("\n  web:\n", maxsplit=1)[1].split("\nnetworks:\n", maxsplit=1)[0]
    db_section = compose.split("\n  db:\n", maxsplit=1)[1].split("\n  api:\n", maxsplit=1)[0]

    assert '"127.0.0.1:${API_PORT-8000}:8000"' in compose
    assert '"127.0.0.1:${WEB_PORT-3000}:3000"' in compose
    assert "\n    ports:" not in db_section
    assert "internal: true" in compose
    assert "privileged: true" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "DATABASE_URL" not in web_section
    assert "POSTGRES_PASSWORD" not in web_section
    assert "DEEPSEEK_API_KEY" not in web_section
    assert "OPENAI_API_KEY" not in web_section
    assert "--workers\", \"1" in compose or "--workers" not in compose


def test_provider_overrides_use_an_api_only_named_volume() -> None:
    deepseek = (ROOT / "compose.deepseek.yaml").read_text(encoding="utf-8")
    openai = (ROOT / "compose.openai.yaml").read_text(encoding="utf-8")
    script = (ROOT / "scripts/docker-up.ps1").read_text(encoding="utf-8")

    for override in (deepseek, openai):
        assert "provider_secrets" in override
        assert "PROVIDER_SECRET_DIRECTORY" in override
        assert ":/run/agent-studio-provider-secrets:ro" in override
        assert "\nsecrets:" not in override
    assert "DEEPSEEK_API_KEY:" not in deepseek
    assert "OPENAI_API_KEY:" not in openai
    assert "run --rm -T --no-deps secret-init" in script
    assert "--provider-secret $Provider" in script
    assert '$upArguments += "--force-recreate"' in script

    shutdown_script = (ROOT / "scripts/docker-down.ps1").read_text(encoding="utf-8")
    assert '"compose.deepseek.yaml"' in shutdown_script
    assert '"compose.openai.yaml"' in shutdown_script


def test_dockerignore_excludes_secrets_and_host_build_artifacts() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for required in (
        ".git",
        ".venv",
        "**/node_modules",
        "**/.next",
        ".env",
        ".runtime-secrets",
        "*.db",
        "**/test-results",
    ):
        assert required in dockerignore
    assert "!.env.example" in dockerignore

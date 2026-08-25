FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime

ENV APP_ENV=production-like \
    PATH=/opt/agent-studio/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/app app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && python -m pip check \
    && python -m pip uninstall --yes pip setuptools wheel \
    && find /usr/local/lib/python3.12/site-packages -type d -name tests -prune -exec rm -rf '{}' + \
    && rm -rf /wheels

WORKDIR /opt/agent-studio
USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]

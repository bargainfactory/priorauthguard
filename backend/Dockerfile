# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# PriorAuthGuard backend image.
#
# Multi-stage so the production image carries only Python + the compiled
# wheel — no dev tooling, no build artifacts, no .git.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

# --- builder ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# System deps: blake3 and orjson have wheels, but cryptography sometimes
# needs OpenSSL headers on the slim image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY pa_guard ./pa_guard

# Install into a venv so we can copy it into the runtime stage cleanly.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --upgrade pip
RUN pip install ".[]"
RUN pip install asyncpg aiosqlite

# --- runtime ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PAG_ENVIRONMENT=production \
    PAG_API_HOST=0.0.0.0 \
    PAG_API_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root.
RUN useradd --create-home --shell /bin/bash paguard

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY pa_guard ./pa_guard

USER paguard
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PAG_API_PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "pa_guard.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

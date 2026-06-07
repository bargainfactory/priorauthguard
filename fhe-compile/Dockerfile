# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Reproducible FHE training + compilation container.
#
# Concrete ML caps at Python < 3.13, so we pin Python 3.12 here and run
# the QAT + compile pipeline inside this image. The host filesystem is
# bind-mounted at /work so the compiled artifact lands directly in
# `backend/.fhe_cache/denial_risk_v0.compiled` — exactly where the
# Phase 0 FHEInferenceService auto-loader looks for it.
#
# Usage (from repo root):
#
#     docker build -t pa-guard-fhe -f fhe-compile/Dockerfile fhe-compile
#     docker run --rm -v "$(pwd):/work" pa-guard-fhe
#
# The container prints model accuracy, plaintext-vs-FHE agreement on a
# held-out set, and the final artifact path before exiting.
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Concrete ML pulls in scipy / scikit-learn / torch; install build deps
# the wheels need for native extensions on the slim base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        libffi-dev \
        git \
    && rm -rf /var/lib/apt/lists/*

# Pinned to known-good combinations as of 2026-Q2. Bumping concrete-ml
# requires re-checking the brevitas / torch matrix.
RUN pip install --upgrade pip
RUN pip install \
    "concrete-ml>=1.9,<2.0" \
    "brevitas>=0.11,<0.12" \
    "torch>=2.4,<2.6" \
    numpy

WORKDIR /work

# The training script lives at /work/fhe-compile/train_and_compile.py once
# the host repo is mounted. Default CMD runs it; override with a different
# `docker run … python …` invocation if you want to introspect.
CMD ["python", "/work/fhe-compile/train_and_compile.py"]

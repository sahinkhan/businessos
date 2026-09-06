# syntax=docker/dockerfile:1
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS wheel-builder
COPY pyproject.toml README.md ./
COPY requirements/constraints-py313.txt /build/constraints-py313.txt
COPY platform ./platform
COPY examples/proof_module ./examples/proof_module
ENV PIP_CONSTRAINT=/build/constraints-py313.txt
RUN python -m pip wheel --no-deps --wheel-dir /wheels . \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./examples/proof_module

FROM base AS development
COPY pyproject.toml README.md ./
COPY requirements ./requirements
COPY platform ./platform
COPY examples/proof_module ./examples/proof_module
RUN python -m pip install --no-cache-dir \
    --constraint requirements/constraints-py313.txt \
    -e '.[dev,providers]' \
    -e examples/proof_module
COPY . .
CMD ["uvicorn", "businessos.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY requirements/constraints-py313.txt /tmp/constraints-py313.txt
COPY --from=wheel-builder /wheels/businessos-*.whl /tmp/wheels/
RUN python -m pip install --no-cache-dir \
    --constraint /tmp/constraints-py313.txt \
    /tmp/wheels/businessos-*.whl \
    && rm -rf /tmp/wheels /tmp/constraints-py313.txt
USER 65532:65532
WORKDIR /srv/businessos
CMD ["uvicorn", "businessos.asgi:application", "--host", "0.0.0.0", "--port", "8000"]

FROM production AS migration-smoke
USER root
COPY --from=wheel-builder /wheels/businessos_phase1_proof-*.whl /tmp/wheels/
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/businessos_phase1_proof-*.whl \
    && rm -rf /tmp/wheels \
    && mkdir -p /tmp/businessos-migration-smoke \
    && chown 65532:65532 /tmp/businessos-migration-smoke
USER 65532:65532
WORKDIR /tmp/businessos-migration-smoke
RUN businessos migrate plan

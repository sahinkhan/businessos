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
COPY foundations ./foundations
COPY examples/proof_module ./examples/proof_module

ENV PIP_CONSTRAINT=/build/constraints-py313.txt
RUN python -m pip wheel --no-deps --wheel-dir /wheels . \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/tenant \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/identity \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/organization \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/currency \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/geography \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/reference_data \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/uom \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/party \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/policy \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/audit \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./foundations/data_governance \
    && python -m pip wheel --no-deps --wheel-dir /wheels ./examples/proof_module

FROM base AS development

COPY pyproject.toml README.md ./
COPY requirements ./requirements
COPY platform ./platform
COPY foundations ./foundations
COPY examples/proof_module ./examples/proof_module

RUN python -m pip install --no-cache-dir \
    --constraint requirements/constraints-py313.txt \
    -e '.[dev,providers]' \
    -e foundations/tenant \
    -e foundations/identity \
    -e foundations/organization \
    -e foundations/currency \
    -e foundations/geography \
    -e foundations/reference_data \
    -e foundations/uom \
    -e foundations/party \
    -e foundations/policy \
    -e foundations/audit \
    -e foundations/data_governance \
    -e examples/proof_module

COPY . .

CMD ["uvicorn", "businessos.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production

COPY requirements/constraints-py313.txt /tmp/constraints-py313.txt
COPY scripts/bootstrap_first_tenant.py /opt/businessos/bootstrap_first_tenant.py
COPY --from=wheel-builder /wheels/*.whl /tmp/wheels/

RUN python -m pip install --no-cache-dir \
    --constraint /tmp/constraints-py313.txt \
    '/tmp/wheels/businessos-0.2.0-py3-none-any.whl[providers]' \
    /tmp/wheels/businessos_foundation_tenant-*.whl \
    /tmp/wheels/businessos_foundation_identity-*.whl \
    /tmp/wheels/businessos_foundation_organization-*.whl \
    /tmp/wheels/businessos_foundation_currency-*.whl \
    /tmp/wheels/businessos_foundation_geography-*.whl \
    /tmp/wheels/businessos_foundation_reference_data-*.whl \
    /tmp/wheels/businessos_foundation_uom-*.whl \
    /tmp/wheels/businessos_foundation_party-*.whl \
    /tmp/wheels/businessos_foundation_policy-*.whl \
    /tmp/wheels/businessos_foundation_audit-*.whl \
    /tmp/wheels/businessos_foundation_data_governance-*.whl \
    && rm -rf /tmp/wheels /tmp/constraints-py313.txt

USER 65532:65532
WORKDIR /srv/businessos

CMD ["uvicorn", "businessos.asgi:application", "--host", "0.0.0.0", "--port", "8000"]

FROM production AS migration-smoke

USER root
COPY tests/fixtures/approved-module-inventory.ci.json /opt/businessos/ci-approved-inventory.json
ENV BOS_APPROVED_MODULE_INVENTORY=/opt/businessos/ci-approved-inventory.json
COPY --from=wheel-builder /wheels/businessos_phase1_proof-*.whl /tmp/wheels/
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/businessos_phase1_proof-*.whl \
    && rm -rf /tmp/wheels \
    && mkdir -p /tmp/businessos-migration-smoke \
    && chown 65532:65532 /tmp/businessos-migration-smoke

USER 65532:65532
WORKDIR /tmp/businessos-migration-smoke

RUN businessos migrate plan

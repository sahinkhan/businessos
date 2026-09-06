# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

FROM base AS development
COPY pyproject.toml README.md ./
COPY platform ./platform
RUN python -m pip install --no-cache-dir -e '.[dev,providers]'
COPY . .
CMD ["uvicorn", "businessos.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY pyproject.toml README.md ./
COPY platform ./platform
RUN python -m pip install --no-cache-dir .
USER 65532:65532
CMD ["uvicorn", "businessos.asgi:application", "--host", "0.0.0.0", "--port", "8000"]


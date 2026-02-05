# Railway BE Dockerfile for FastAPI backend
# Avoids pnpm autodetection by using Python-only image
#
# Build context must be the repo root (not packages/quantum/)
# Railway config: "dockerfilePath": "packages/quantum/Dockerfile"

FROM python:3.11-slim

WORKDIR /app

# Build arguments for deployment fingerprint
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown

# Persist build metadata as env vars for /__version endpoint
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_TIME=${BUILD_TIME}

# Layer 1: Install dependencies first (cached unless requirements.txt changes)
COPY packages/quantum/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Layer 2: Copy repo structure markers (for db.py repo-root detection)
# These files help jobs/db.py locate the repo root via upward search
COPY pnpm-workspace.yaml /app/pnpm-workspace.yaml

# Layer 3: Copy backend code to /app/packages/quantum so "import packages.quantum.*" resolves
# This is the main application code - changes here invalidate this layer
COPY packages/quantum /app/packages/quantum

# Railway injects PORT env var; default to 8000 for local testing
CMD ["sh", "-c", "uvicorn packages.quantum.api:app --host 0.0.0.0 --port ${PORT:-8000}"]

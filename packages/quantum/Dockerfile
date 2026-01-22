# Railway BE Dockerfile for FastAPI backend
# Avoids pnpm autodetection by using Python-only image

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY packages/quantum/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy backend code to /app/packages/quantum so "import packages.quantum.*" resolves
COPY packages/quantum /app/packages/quantum

# Railway injects PORT env var; default to 8000 for local testing
CMD ["sh", "-c", "uvicorn packages.quantum.api:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS ui
WORKDIR /build
RUN npm install -g pnpm@11.19.0 --ignore-scripts
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng poppler-utils libnfs-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
RUN uv sync --frozen --no-editable
COPY alembic.ini ./
COPY migrations/ migrations/
COPY --from=ui /build/dist frontend/dist/
RUN groupadd --gid 10001 hub && useradd --uid 10001 --gid hub --no-create-home hub
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8765
CMD ["uvicorn", "hub.api:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"]

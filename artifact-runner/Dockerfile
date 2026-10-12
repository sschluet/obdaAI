FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-impress libreoffice-calc fonts-liberation poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
COPY scripts/artifact_smoke.py ./artifact_smoke.py
RUN uv sync --frozen --no-editable
RUN groupadd --gid 10001 hub && useradd --uid 10001 --gid hub --no-create-home hub
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER 10001:10001
CMD ["python", "-m", "hub.artifact_runner"]

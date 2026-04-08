FROM python:3.12-slim AS base

# Install system dependencies (ffmpeg for audio conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r secretary && useradd -r -g secretary -m secretary

WORKDIR /app

# Install Python dependencies
FROM base AS deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Final image
FROM deps AS final

COPY secretary/ secretary/

# Create data directory for SQLite
RUN mkdir -p data && chown secretary:secretary data

USER secretary

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "secretary.main:app", "--host", "0.0.0.0", "--port", "8000"]

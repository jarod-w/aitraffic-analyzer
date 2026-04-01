FROM python:3.12-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    libpcap-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[postgres]"

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Build frontend
COPY frontend/package.json frontend/
RUN cd frontend && npm install --legacy-peer-deps

COPY frontend/ frontend/
RUN cd frontend && npm run build

# Copy backend source
COPY prism/ prism/

# Runtime directories
RUN mkdir -p /data /scripts /data/certs /data/uploads

ENV PRISM_HOST=0.0.0.0
ENV PRISM_PORT=3000
ENV PRISM_DATA_DIR=/data
ENV PRISM_CERTS_DIR=/data/certs
ENV PRISM_SCRIPTS_DIR=/scripts
ENV PRISM_UPLOADS_DIR=/data/uploads
ENV PRISM_DB_PATH=/data/prism.db

EXPOSE 3000 8080

CMD ["python", "-m", "prism.main"]

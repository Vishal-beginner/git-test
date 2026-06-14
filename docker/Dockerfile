# Stage 1: builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim AS runtime

# Security: run as non-root user
RUN groupadd -r shipnav && useradd -r -g shipnav -d /app -s /bin/bash shipnav

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=shipnav:shipnav src/ ./src/
COPY --chown=shipnav:shipnav config/ ./config/
COPY --chown=shipnav:shipnav pyproject.toml .

# Create VDR data directory
RUN mkdir -p /app/vdr_data && chown shipnav:shipnav /app/vdr_data

USER shipnav

# Expose API port and WebSocket port
EXPOSE 8080
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Default environment
ENV CONFIG_PATH=/app/config/ship.yaml
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]

# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as non-root
RUN groupadd --gid 1001 shipnav \
    && useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false shipnav

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ src/
COPY config/ config/

# Create VDR log directory with correct ownership
RUN mkdir -p data/vdr && chown -R shipnav:shipnav /app

USER shipnav

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["config/ship.yaml"]

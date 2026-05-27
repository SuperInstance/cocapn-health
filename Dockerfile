FROM python:3.12-slim

LABEL org.opencontainers.image.title="cocapn-health"
LABEL org.opencontainers.image.description="Fleet service health checker with HTTP/TCP/DNS/system checks and REST API"
LABEL org.opencontainers.image.source="https://github.com/SuperInstance/cocapn-health"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd --system appgroup && useradd --system --gid appgroup appuser

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Switch to non-root user
USER appuser

# Health check: CLI exits 0 when all services up
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -m cocapn_health.cli --format oneline --system --fail || exit 1

ENTRYPOINT ["cocapn-health"]
CMD ["--format", "oneline", "--system"]

# Baarn Raadsinformatie - Docker Image
# Kan draaien als MCP server, API server of als background sync service

FROM python:3.11-slim AS base

LABEL maintainer="Tiemen R. Tuinstra <tiemen@tuinstra.family>"
LABEL description="Baarn Raadsinformatie MCP server en sync service"

# Set working directory
WORKDIR /app

# Install system dependencies voor PDF processing en compilatie
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# ==================== Dependencies stage ====================
FROM base AS dependencies

# Build argument voor embeddings (default: aan)
ARG INSTALL_EMBEDDINGS=true

# Copy requirements files
COPY requirements.txt requirements-embeddings.txt ./

# Install base dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install embeddings dependencies (torch CPU-only voor kleinere image)
RUN if [ "$INSTALL_EMBEDDINGS" = "true" ]; then \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
        pip install --no-cache-dir -r requirements-embeddings.txt; \
    fi

# ==================== Final stage ====================
FROM base AS final

# Copy installed packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data/documents /app/data/cache /app/logs

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO
ENV AUTO_SYNC_ENABLED=true
ENV AUTO_SYNC_DAYS=365
ENV AUTO_DOWNLOAD_DOCS=true
ENV AUTO_INDEX_DOCS=true
ENV EMBEDDINGS_ENABLED=true

# Data volume
VOLUME ["/app/data", "/app/logs"]

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=5m --timeout=30s --start-period=60s --retries=3 \
    CMD python -c "from core.database import get_database; db = get_database(); print(db.get_statistics())"

# Default: run MCP server (Claude Desktop zal dit starten)
# Alternatieven:
#   - API server: CMD ["python", "api_server.py"]
#   - Sync service: CMD ["python", "sync_service.py"]
CMD ["python", "mcp_server.py"]

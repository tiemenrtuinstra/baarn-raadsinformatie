# Baarn Raadsinformatie - Docker Image
# Draait een background sync service die data up-to-date houdt

FROM python:3.11-slim

LABEL maintainer="Tiemen R. Tuinstra <tiemen@tuinstra.family>"
LABEL description="Baarn Raadsinformatie sync service"

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
ENV AUTO_INDEX_DOCS=false

# Data volume
VOLUME ["/app/data", "/app/logs"]

# Health check
HEALTHCHECK --interval=5m --timeout=30s --start-period=60s --retries=3 \
    CMD python -c "from core.database import get_database; db = get_database(); print(db.get_statistics())"

# Run sync service
CMD ["python", "sync_service.py"]

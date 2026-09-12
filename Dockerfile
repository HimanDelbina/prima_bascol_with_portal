# ==========================================================
# Prima Bascol - Production Dockerfile
# Industrial Weighbridge Management System
# ==========================================================

FROM python:3.12-slim AS base

# Python runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# Install required system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq5 \
    libpq-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libfreetype6-dev \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create non-root application user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -d /home/appuser -m appuser

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application source code
COPY . /app/

# Create persistent directories and set permissions
RUN mkdir -p /app/staticfiles /app/media /app/backups && \
    chown -R appuser:appuser /app

# Ensure entrypoint script is executable
RUN chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER appuser

# Expose internal port
EXPOSE 8000

# Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health/ || exit 1

# Entrypoint and default command
ENTRYPOINT ["/app/docker-entrypoint.sh"]

CMD ["gunicorn", "prima_bascol.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--worker-class", "gthread", "--access-logfile", "-", "--error-logfile", "-", "--timeout", "120"]

# ─── OnFood Server Watcher Dockerfile ─────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source and templates
COPY . .

# Create logs directory mount point
RUN mkdir -p /logs

# Default environment variables
ENV SERVER_URL=http://localhost:8000 \
    LOG_DIRECTORY=/logs \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=9000 \
    ADMIN_USERNAME=karthiksupport \
    ADMIN_PASSWORD=karthik@6

EXPOSE 9000

# Healthcheck to verify the web server is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9000/login || exit 1

CMD ["uvicorn", "web:app", "--host", "0.0.0.0", "--port", "9000"]

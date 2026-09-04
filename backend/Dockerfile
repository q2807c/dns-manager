FROM python:3.11-slim

WORKDIR /app

# Use Aliyun mirror for faster apt downloads in China
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# Install system dependencies
# - postgresql-client: pg_isready (used by entrypoint in Full mode)
# - openssh-client: ssh-keyscan for F5 connection
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl postgresql-client openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Use Aliyun mirror for faster pip downloads in China
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create directories for SSH keys, backups, and logs
RUN mkdir -p /app/keys /app/backups /app/logs /app/data

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

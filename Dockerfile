# DepotGate Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create data directories
RUN mkdir -p /app/data/staging /app/data/shipped

# Create non-root user for security
RUN groupadd -g 1000 depotgate && \
    useradd -m -u 1000 -g depotgate depotgate && \
    chown -R depotgate:depotgate /app

# Set environment variables
ENV DEPOTGATE_HOST=0.0.0.0
ENV DEPOTGATE_PORT=8000
ENV DEPOTGATE_STORAGE_BASE_PATH=/app/data/staging
ENV DEPOTGATE_SINK_FILESYSTEM_BASE_PATH=/app/data/shipped

# Expose port
EXPOSE 8000

# Switch to non-root user
USER depotgate

# Run the service
CMD ["python", "-m", "depotgate.main"]

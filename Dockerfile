# Build context is the STACK ROOT, not this repository:
#
#     docker build -f DepotGate/Dockerfile .
#
# The image installs the canonical protocol package from the sibling LegiVellum
# checkout. `legivellum` is a hard dependency and is not published to an index,
# so a repo-scoped context cannot satisfy it -- the build fails with
# "No matching distribution found for legivellum" rather than silently
# producing an image that cannot validate receipts.

# DepotGate Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
# The canonical protocol package first: receipt models, validation, and the
# schema, which ships as package data so validation needs no source checkout.
COPY LegiVellum/pyproject.toml LegiVellum/README.md /src/LegiVellum/
COPY LegiVellum/shared/ /src/LegiVellum/shared/
RUN pip install --no-cache-dir /src/LegiVellum

COPY DepotGate/pyproject.toml DepotGate/README.md ./
COPY DepotGate/src/ ./src/

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

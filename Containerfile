# ==============================================================================
# Edge Vision Monitor - Least-Privilege Podman Containerfile
# Target Platform: Raspberry Pi 5 (ARM64 / aarch64) and Linux x86_64
# Base: Debian Bookworm Slim with HailoRT runtime dependencies
# ==============================================================================

FROM debian:bookworm-slim

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime dependencies, libcamera / v4l2 tools, and system libraries
# Tolerate clock skew on edge devices by allowing future release dates
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until && \
    echo 'Acquire::Max-Future-Time "864000";' >> /etc/apt/apt.conf.d/99no-check-valid-until && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-yaml \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    v4l-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create application user and setup directories
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    mkdir -p /app/data /app/models /app/media /app/config && \
    chown -R appuser:appuser /app

WORKDIR /app

# Setup Python virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python requirements
COPY requirements.txt pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=appuser:appuser main.py /app/main.py
COPY --chown=appuser:appuser app/ /app/app/
COPY --chown=appuser:appuser config/ /app/config/
COPY --chown=appuser:appuser scripts/ /app/scripts/
COPY --chown=appuser:appuser models/labels.txt /app/models/labels.txt

# Create volume mount points
VOLUME ["/app/data", "/app/models", "/app/media"]

# Expose HTTP port
EXPOSE 8000

# Health check distinguishing process liveness
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Drop to non-root user
USER appuser

CMD ["python3", "main.py", "run"]

# MM_LeechBot Dockerfile
FROM python:3.13-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    aria2 \
    ffmpeg \
    p7zip-full \
    rclone \
    mediainfo \
    git \
    qbittorrent-nox \
    libmagic1 \
    curl \
    cpulimit \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install MegaCMD from official MEGA repository
RUN wget -qO /tmp/megacmd.deb https://mega.nz/linux/repo/Debian_12/amd64/megacmd-Debian_12_amd64.deb && \
    apt-get update && \
    apt-get install -y /tmp/megacmd.deb && \
    rm -f /tmp/megacmd.deb && \
    rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Install Python dependencies first (cached unless requirements.txt changes)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy code (this layer rebuilds on code changes, but pip is already cached)
COPY . /app

# Expose web server port (if used)
EXPOSE 8000

# Default command — starts aria2, qBittorrent, then the bot
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]

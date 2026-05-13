FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# System libraries sourced from dailyco/pipecat-base:
#   GL stack (cv2/OpenCV used by pipecat's WebRTC transport)
#   X11 (cv2 requires display libs even on headless servers)
#   OpenBLAS + Fortran + OpenMP (numpy, onnxruntime, Silero VAD)
#   libresample (pipecat audio pipeline)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libgl1 \
        libglvnd0 \
        libglib2.0-0 \
        libx11-6 \
        libxext6 \
        libxcb1 \
        libdrm2 \
        libopenblas0 \
        libgfortran5 \
        libgomp1 \
        libresample1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Install Node.js 22 + OpenAI Codex CLI (used by RepoInvestigator)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @openai/codex \
    && npm cache clean --force \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Copy application code
COPY bot.py bot.py
COPY ariadne ariadne

# Install the local project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Container-side defaults — overridden by docker-compose
ENV ARIADNE_DEBUG_SERVER_HOST=0.0.0.0
ENV LOGS_DIR=/logs
ENV ARIADNE_REPO_PATH=/workspace/repo
ENV ARIADNE_PROJECT_BACKGROUND_PATH=/app/ariadne/PROJECT_BACKGROUND.md

EXPOSE 7860
EXPOSE 8765

CMD ["uv", "run", "bot.py", "--host", "0.0.0.0", "-t", "daily", "--dialin"]

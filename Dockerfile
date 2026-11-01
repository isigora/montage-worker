# montage-worker: OpenMontage + Claude Agent SDK behind a small internal API.
FROM node:22-bookworm

ARG OPENMONTAGE_REPO=https://github.com/calesthio/OpenMontage.git
ARG OPENMONTAGE_COMMIT=195eab24478dc9363326aec437aefc3701635ddf

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OM_DIR=/app/OpenMontage \
    DATA_DIR=/data \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    IS_SANDBOX=1 \
    CLAUDE_CONFIG_DIR=/data/claude

# Python 3.11, FFmpeg, Korean/CJK fonts, and the shared libraries headless Chrome needs (Remotion).
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-dev build-essential git ffmpeg \
      fonts-noto-cjk fonts-noto-color-emoji \
      libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libgbm1 libasound2 \
      libxrandr2 libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 \
      libpango-1.0-0 libcairo2 libcups2 libdrm2 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv

WORKDIR /app
RUN git clone "$OPENMONTAGE_REPO" OpenMontage \
    && cd OpenMontage && git checkout "$OPENMONTAGE_COMMIT" && rm -rf .git

WORKDIR /app/OpenMontage
RUN pip install --no-cache-dir -r requirements.txt \
    && (pip install --no-cache-dir piper-tts || echo "piper-tts install failed")
RUN cd remotion-composer && npm install --no-audit --no-fund \
    && npx remotion browser ensure
RUN npx --yes hyperframes --version || echo "hyperframes warm skipped"
RUN cp .env.example .env

WORKDIR /app
COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt
COPY worker worker
COPY start.sh start.sh
RUN chmod +x start.sh

EXPOSE 8080
CMD ["/app/start.sh"]

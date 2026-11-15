FROM python:3.12

WORKDIR /app

# Нативные зависимости:
#   exiftool — EXIF фото и метаданные видео;
#   ffmpeg   — ffprobe как запасной парсер видео;
#   libheif  — чтение HEIC через pillow-heif;
#   libgl    — onnxruntime/opencv.
RUN apt-get update && apt-get install -y --no-install-recommends \
        exiftool \
        ffmpeg \
        libheif-dev \
        libgl1 \
        libglib2.0-0 \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Предзагруженная модель InsightFace (не скачивать при старте).
ENV MODEL_ROOT=/opt/insightface
RUN mkdir -p /opt/insightface/models && \
    curl -sSL -o /opt/insightface/models/buffalo_l.zip \
        https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip && \
    unzip -q /opt/insightface/models/buffalo_l.zip -d /opt/insightface/models/buffalo_l && \
    rm /opt/insightface/models/buffalo_l.zip

COPY pyproject.toml poetry.lock ./
RUN python -m pip install --upgrade pip && \
    pip install poetry --no-cache-dir && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-root --no-cache --no-interaction

COPY alembic ./alembic
COPY api ./api
COPY common ./common
COPY db ./db
COPY repositories ./repositories
COPY schemas ./schemas
COPY services ./services
COPY worker ./worker
COPY docs ./docs
COPY alembic.ini entrypoint.sh ./

# По умолчанию запускается API; воркер запускается отдельной командой
# (см. docker-compose.example.yml, сервис analyzer-worker).
CMD ["sh", "./entrypoint.sh"]

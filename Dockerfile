# Dockerfile
# Общий non-root образ Django; vision и test toolchains вынесены в отдельные stages.
FROM python:3.12-slim-bookworm AS source
WORKDIR /source
COPY src ./src
COPY templates ./templates
COPY static ./static
COPY tests ./tests
COPY scripts ./scripts
COPY docs ./docs
COPY .github ./.github
COPY README.md LICENSE docs-specification.md pyproject.toml uv.lock .env.example .gitignore .gitattributes .dockerignore .python-version manage.py package.json Dockerfile Dockerfile.bootstrap compose.yaml compose.bootstrap.yaml compose.gpu.yaml ./
RUN PYTHONPATH=/source/src python -m infrastructure.source_archive

FROM python:3.12-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/app/.venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core libglib2.0-0 libgl1 libgomp1 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock .env.example ./
RUN uv sync --frozen --no-dev --no-extra vision
COPY src ./src
COPY templates ./templates
COPY static ./static
COPY manage.py ./
COPY LICENSE ./
COPY --from=source /source/source.tar.gz ./source.tar.gz
RUN DATABASE_ENGINE=sqlite uv run --no-sync python manage.py collectstatic --noinput
RUN mkdir -p media staticfiles .cache models && useradd --uid 10001 --create-home watcher && chown -R watcher:watcher /app
USER watcher
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "2", "--threads", "32", "--timeout", "90", "--access-logfile", "-"]

FROM base AS vision
ENV YOLO_AUTOINSTALL=false YOLO_CONFIG_DIR=/app/.cache/ultralytics
RUN uv sync --frozen --no-dev --extra vision
CMD ["python", "-m", "workers.vision"]

FROM base AS testing
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-extra vision && uv run --no-sync playwright install --with-deps --no-shell chromium
COPY tests ./tests
COPY package.json ./
RUN chown -R watcher:watcher /app /opt/playwright
USER watcher
CMD ["pytest", "-q", "--tb=short", "-m", "not e2e"]

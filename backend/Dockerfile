# TaskPilot AI API (+ embedded queue worker and headless Chromium).
# Build:  docker build -t taskpilot-api ./backend
# Runs as a non-root user; the root filesystem is mounted read-only by docker-compose.prod.yml.
FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache

RUN groupadd --system --gid 10001 taskpilot \
 && useradd --system --uid 10001 --gid taskpilot --home-dir /home/taskpilot --create-home --shell /usr/sbin/nologin taskpilot \
 && mkdir -p /app/runtime /tmp/taskpilot \
 && chown -R taskpilot:taskpilot /app/runtime /tmp/taskpilot

COPY --chown=root:root app ./app
COPY --chown=root:root alembic.ini ./alembic.ini

USER taskpilot
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

# Migrations run as a separate one-shot service (see docker-compose.prod.yml), never implicitly here.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libffi8 libgdk-pixbuf-2.0-0 libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz-subset0 fonts-dejavu-core fonts-liberation2 cups-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG GIT_SHA=""
ENV GIT_SHA=$GIT_SHA
COPY app ./app

RUN useradd --system --uid 10001 --create-home dailynews \
    && mkdir -p /data/database /data/pdf /data/logs \
    && chown -R dailynews:dailynews /app /data
USER dailynews

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
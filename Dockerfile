FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup -S lingxi \
    && adduser -S -G lingxi lingxi \
    && mkdir -p /app/data \
    && chown -R lingxi:lingxi /app

COPY --chown=lingxi:lingxi server.py ./server.py
COPY --chown=lingxi:lingxi device_protocol.py ./device_protocol.py
COPY --chown=lingxi:lingxi providers ./providers
COPY --chown=lingxi:lingxi public ./public

USER lingxi

EXPOSE 8787
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)); assert data.get('ok') is True"

ENTRYPOINT ["python", "server.py"]
CMD ["--host", "0.0.0.0", "--port", "8787", "--database", "/app/data/lingxi.db"]

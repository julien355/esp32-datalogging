# Ingest service: Python standard library only, no pip install, about 25 to 40 MB of RAM.
FROM python:3.12-slim

# tzdata: daily.csv and the OED export use the site's timezone (Asia/Makassar)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --create-home --shell /usr/sbin/nologin app

WORKDIR /srv/app
COPY app/ app/
COPY tools/ tools/

ENV DATA_DIR=/data PORT=8800 BIND=0.0.0.0 PYTHONUNBUFFERED=1 TZ=UTC
USER 1000:1000
EXPOSE 8800
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8800/health', timeout=4)"
CMD ["python", "app/server.py"]

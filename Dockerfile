FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DB_PATH=/data/characters.db
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY imbot ./imbot

# The database lives on a bind mount (compose.yaml: ./data:/data). Running as the default
# container user keeps that host folder writable without uid/gid juggling on every host.
RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "-m", "imbot"]

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

# System deps (small set; add build tools if you add compiled deps later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY README.md /app/README.md
COPY .env.example /app/.env.example

# Default: run scheduler daemon (runs once on start, then weekly)
CMD ["python", "-m", "peakon_ingest.cli", "daemon"]

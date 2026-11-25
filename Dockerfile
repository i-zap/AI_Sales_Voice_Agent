FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ python3-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY agent ./agent
RUN chown -R appuser:appuser /app

USER appuser
RUN python -m livekit.agents download-files

CMD ["python", "-m", "agent.main", "start"]

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

COPY libs/qa_swarm_common ./libs/qa_swarm_common
COPY agents/vision-agent/pyproject.toml ./agents/vision-agent/pyproject.toml
COPY agents/vision-agent/src ./agents/vision-agent/src

RUN pip install --no-cache-dir ./libs/qa_swarm_common ./agents/vision-agent

EXPOSE 8000

CMD ["uvicorn", "vision_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

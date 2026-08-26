FROM python:3.11-slim

WORKDIR /app

COPY libs/qa_swarm_common ./libs/qa_swarm_common
COPY agents/discovery-agent/pyproject.toml ./agents/discovery-agent/pyproject.toml
COPY agents/discovery-agent/src ./agents/discovery-agent/src

RUN pip install --no-cache-dir ./libs/qa_swarm_common ./agents/discovery-agent

EXPOSE 8000

CMD ["uvicorn", "discovery_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

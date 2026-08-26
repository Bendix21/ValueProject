FROM python:3.11-slim

WORKDIR /app

COPY libs/qa_swarm_common ./libs/qa_swarm_common
COPY agents/validator-agent/pyproject.toml ./agents/validator-agent/pyproject.toml
COPY agents/validator-agent/src ./agents/validator-agent/src

RUN pip install --no-cache-dir ./libs/qa_swarm_common ./agents/validator-agent

EXPOSE 8000

CMD ["uvicorn", "validator_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

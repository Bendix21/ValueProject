FROM python:3.11-slim

WORKDIR /app

COPY libs/qa_swarm_common ./libs/qa_swarm_common
COPY agents/generator-agent/pyproject.toml ./agents/generator-agent/pyproject.toml
COPY agents/generator-agent/src ./agents/generator-agent/src

RUN pip install --no-cache-dir ./libs/qa_swarm_common ./agents/generator-agent

EXPOSE 8000

CMD ["uvicorn", "generator_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

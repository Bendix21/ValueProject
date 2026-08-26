FROM python:3.11-slim

WORKDIR /app

COPY libs/qa_swarm_common ./libs/qa_swarm_common
COPY agents/selenium-executor-agent/pyproject.toml ./agents/selenium-executor-agent/pyproject.toml
COPY agents/selenium-executor-agent/src ./agents/selenium-executor-agent/src

RUN pip install --no-cache-dir ./libs/qa_swarm_common ./agents/selenium-executor-agent

EXPOSE 8000

CMD ["uvicorn", "selenium_executor_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

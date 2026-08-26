FROM python:3.11-slim

WORKDIR /app

COPY libs/qa_swarm_common ./libs/qa_swarm_common
COPY agents/llm-judge-agent/pyproject.toml ./agents/llm-judge-agent/pyproject.toml
COPY agents/llm-judge-agent/src ./agents/llm-judge-agent/src

RUN pip install --no-cache-dir ./libs/qa_swarm_common ./agents/llm-judge-agent

EXPOSE 8000

CMD ["uvicorn", "llm_judge_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

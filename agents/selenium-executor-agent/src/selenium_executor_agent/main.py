import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI
from qa_swarm_common.schemas import ExecutorRequest, ExecutorResponse
from qa_swarm_common.tracing import init_tracing, traced_span

from selenium_executor_agent.config import get_settings
from selenium_executor_agent.executor import execute_scenario

app = FastAPI(title="selenium-executor-agent")
init_tracing(get_settings().lmnr_project_api_key)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=ExecutorResponse)
async def run(request: ExecutorRequest) -> ExecutorResponse:
    with traced_span("selenium-executor-agent.run", session_id=request.job_id):
        result = await asyncio.to_thread(
            execute_scenario,
            request.job_id,
            request.target_url,
            request.scenario.model_dump(),
            request.session_cookies,
        )
    return ExecutorResponse(
        status="judging",
        execution_result=result,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

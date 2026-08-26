from datetime import datetime, timezone

from fastapi import FastAPI
from qa_swarm_common.schemas import JudgeRequest, JudgeResponse
from qa_swarm_common.tracing import init_tracing, traced_span

from llm_judge_agent.config import get_settings
from llm_judge_agent.judging import judge_scenario

app = FastAPI(title="llm-judge-agent")
init_tracing(get_settings().lmnr_project_api_key)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=JudgeResponse)
async def run(request: JudgeRequest) -> JudgeResponse:
    with traced_span("llm-judge-agent.run", session_id=request.job_id):
        verdict = await judge_scenario(request.scenario, request.execution_result)
    return JudgeResponse(
        status="advancing",
        judge_verdict=verdict,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

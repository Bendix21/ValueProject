from datetime import datetime, timezone

from fastapi import FastAPI
from qa_swarm_common.schemas import ValidatorRequest, ValidatorResponse
from qa_swarm_common.tracing import init_tracing, traced_span

from validator_agent.config import get_settings
from validator_agent.validation import validate_scenario

app = FastAPI(title="validator-agent")
init_tracing(get_settings().lmnr_project_api_key)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=ValidatorResponse)
async def run(request: ValidatorRequest) -> ValidatorResponse:
    with traced_span("validator-agent.run", session_id=request.job_id):
        result = await validate_scenario(request.scenario, request.vision)
    return ValidatorResponse(
        status="executing",
        validation_result=result,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

from datetime import datetime, timezone

from fastapi import FastAPI
from qa_swarm_common.schemas import GeneratorRequest, GeneratorResponse
from qa_swarm_common.tracing import init_tracing, traced_span

from generator_agent.config import get_settings
from generator_agent.generation import generate_scenarios

app = FastAPI(title="generator-agent")
init_tracing(get_settings().lmnr_project_api_key)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=GeneratorResponse)
async def run(request: GeneratorRequest) -> GeneratorResponse:
    with traced_span("generator-agent.run", session_id=request.job_id):
        scenarios = await generate_scenarios(
            request.vision, request.target_url, request.max_scenarios, request.target_type
        )
    return GeneratorResponse(
        status="selecting",
        scenarios=scenarios,
        current_scenario_index=0,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

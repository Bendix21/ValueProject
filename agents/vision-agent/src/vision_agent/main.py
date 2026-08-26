import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI
from qa_swarm_common.schemas import VisionRequest, VisionResponse
from qa_swarm_common.tracing import init_tracing, traced_span

from vision_agent.config import get_settings
from vision_agent.ocr import run_ocr
from vision_agent.vlm import enrich_with_vlm

app = FastAPI(title="vision-agent")
init_tracing(get_settings().lmnr_project_api_key)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=VisionResponse)
async def run(request: VisionRequest) -> VisionResponse:
    with traced_span("vision-agent.run", session_id=request.job_id):
        ocr_result = await asyncio.to_thread(run_ocr, request.discovery)
        vision = await enrich_with_vlm(request.discovery, ocr_result)
    return VisionResponse(
        status="generating",
        vision=vision,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

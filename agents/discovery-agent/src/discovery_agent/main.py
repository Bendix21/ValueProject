import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI
from qa_swarm_common.schemas import DiscoveryRequest, DiscoveryResponse
from qa_swarm_common.tracing import init_tracing, traced_span

from discovery_agent.config import get_settings
from discovery_agent.selenium_client import crawl

app = FastAPI(title="discovery-agent")
init_tracing(get_settings().lmnr_project_api_key)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=DiscoveryResponse)
async def run(request: DiscoveryRequest) -> DiscoveryResponse:
    with traced_span("discovery-agent.run", session_id=request.job_id):
        pages = await asyncio.to_thread(
            crawl, request.job_id, request.target_url, request.max_pages, request.target_type
        )
    return DiscoveryResponse(
        status="vision",
        pages=pages,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

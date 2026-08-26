from datetime import datetime, timezone

from langgraph.types import Send

from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import record_agent_failure, record_agent_success
from app.graph.state import QAState
from app.observability import traced_span

VISION_TIMEOUT = 600.0


def dispatch_vision_pages(state: QAState) -> list[Send] | str:
    if state["status"] == "failed" or not state["pages"]:
        return "finalize"
    return [
        Send("vision_page", {**state, "current_page_url": page_url})
        for page_url in state["pages"]
    ]


async def vision_page_node(state: QAState) -> dict:
    page_url = state["current_page_url"]
    with traced_span(f"vision:{page_url}", session_id=state["job_id"]):
        settings = get_settings()
        payload = {"job_id": state["job_id"], "discovery": state["pages"][page_url]}

        try:
            response = await call_agent(settings.vision_agent_url, payload, timeout=VISION_TIMEOUT)
        except AgentUnavailableError as exc:
            failure_states = record_agent_failure(state["failure_states"], "vision", exc)
            return {"failure_states": failure_states}

        failure_states = record_agent_success(state["failure_states"], "vision")
        return {
            "vision_results": {page_url: response["vision"]},
            "failure_states": failure_states,
        }


async def after_vision_node(state: QAState) -> dict:
    with traced_span("after_vision", session_id=state["job_id"]):
        return {
            "status": "generating",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

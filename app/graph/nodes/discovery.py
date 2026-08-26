from datetime import datetime, timezone

from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import record_agent_failure
from app.graph.state import QAState
from app.observability import traced_span

DISCOVERY_TIMEOUT = 120.0


async def discovery_node(state: QAState) -> dict:
    with traced_span("discovery", session_id=state["job_id"]):
        settings = get_settings()
        payload = {
            "job_id": state["job_id"],
            "target_url": state["target_url"],
            "max_pages": state.get("max_pages"),
        }

        try:
            response = await call_agent(
                settings.discovery_agent_url, payload, timeout=DISCOVERY_TIMEOUT
            )
        except AgentUnavailableError as exc:
            failure_states = record_agent_failure(state["failure_states"], "discovery", exc)
            return {
                "status": "failed",
                "failure_states": failure_states,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        pages = {page["target_url"]: page for page in response["pages"]}
        return {
            "status": response["status"],
            "pages": pages,
            "updated_at": response["updated_at"],
        }

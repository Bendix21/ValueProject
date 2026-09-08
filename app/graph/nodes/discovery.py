from datetime import datetime, timezone

from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import record_agent_failure
from app.graph.state import QAState
from app.observability import traced_span

# Must stay comfortably above discovery-agent's own
# chatbot_captcha_grace_seconds (default 180s, see docker-compose.yml) plus
# scrape/screenshot overhead - otherwise call_agent times out and retries
# while the first attempt's browser session (and human solving a captcha in
# it) is still legitimately in progress.
DISCOVERY_TIMEOUT = 300.0


async def discovery_node(state: QAState) -> dict:
    with traced_span("discovery", session_id=state["job_id"]):
        settings = get_settings()
        payload = {
            "job_id": state["job_id"],
            "target_url": state["target_url"],
            "max_pages": state.get("max_pages"),
            "target_type": state.get("target_type", "web_app"),
        }

        try:
            response = await call_agent(
                settings.discovery_agent_url, payload, timeout=DISCOVERY_TIMEOUT
            )
        except AgentUnavailableError as exc:
            failure_states = record_agent_failure("discovery", exc)
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

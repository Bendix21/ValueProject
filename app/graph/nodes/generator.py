from langgraph.types import Send

from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import record_agent_failure, record_agent_success
from app.graph.state import QAState
from app.observability import traced_span

GENERATOR_TIMEOUT = 120.0


def dispatch_generation_pages(state: QAState) -> list[Send] | str:
    if not state["vision_results"]:
        return "finalize"
    return [
        Send("generate_page", {**state, "current_page_url": page_url})
        for page_url in state["vision_results"]
    ]


async def generate_page_node(state: QAState) -> dict:
    page_url = state["current_page_url"]
    with traced_span(f"generator:{page_url}", session_id=state["job_id"]):
        settings = get_settings()
        payload = {
            "job_id": state["job_id"],
            "target_url": page_url,
            "vision": state["vision_results"][page_url],
            "max_scenarios": state.get("max_scenarios"),
            "target_type": state.get("target_type", "web_app"),
        }

        try:
            response = await call_agent(
                settings.generator_agent_url, payload, timeout=GENERATOR_TIMEOUT
            )
        except AgentUnavailableError as exc:
            failure_states = record_agent_failure("generator", exc)
            return {"failure_states": failure_states}

        failure_states = record_agent_success("generator")
        return {
            "scenarios": response["scenarios"],
            "failure_states": failure_states,
        }

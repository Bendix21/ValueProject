from datetime import datetime, timezone

from langgraph.types import Send

from app.graph.state import QAState
from app.observability import traced_span


async def select_scenario_node(state: QAState) -> dict:
    with traced_span("select_scenario", session_id=state["job_id"]):
        return {
            "status": "validating",
            "current_scenario_index": len(state["scenarios"]),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def dispatch_scenarios(state: QAState) -> list[Send] | str:
    if not state["scenarios"]:
        return "finalize"
    return [
        Send("run_scenario", {**state, "selected_scenario": scenario})
        for scenario in state["scenarios"]
    ]

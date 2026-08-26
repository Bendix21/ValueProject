from datetime import datetime, timezone

from app.graph.resilience import batch_circuit_breaker_tripped
from app.graph.state import QAState
from app.observability import traced_span


async def advance_node(state: QAState) -> dict:
    with traced_span("advance", session_id=state["job_id"]):
        patch = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if batch_circuit_breaker_tripped(state):
            patch["status"] = "failed"
            patch["circuit_breaker_tripped"] = True
        return patch

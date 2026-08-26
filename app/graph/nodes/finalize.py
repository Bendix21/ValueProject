from datetime import datetime, timezone

from app.graph.state import QAState
from app.observability import traced_span


def _last_error(state: QAState) -> str | None:
    errors = [f["last_error"] for f in state["failure_states"].values() if f.get("last_error")]
    return "; ".join(errors) if errors else None


async def finalize_node(state: QAState) -> dict:
    with traced_span("finalize", session_id=state["job_id"]):
        passed = sum(1 for v in state["judge_verdicts"].values() if v["verdict"] == "pass")
        failed = len(state["judge_verdicts"]) - passed

        if state["status"] == "failed":
            final_status = "circuit_broken" if state.get("circuit_breaker_tripped") else "failed"
        else:
            final_status = "completed"

        final_report = {
            "job_id": state["job_id"],
            "target_url": state["target_url"],
            "pages_tested": len(state["pages"]),
            "scenario_count": len(state["scenarios"]),
            "passed": passed,
            "failed": failed,
        }
        if final_status != "completed":
            final_report["error"] = _last_error(state)

        return {
            "status": final_status,
            "final_report": final_report,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

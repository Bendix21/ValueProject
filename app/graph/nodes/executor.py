from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import (
    EXECUTOR_UNAVAILABLE_PREFIX,
    record_agent_failure,
    record_agent_success,
)
from app.observability import traced_span

EXECUTOR_TIMEOUT = 90.0


def _empty_evidence(url: str) -> dict:
    return {
        "screenshots": [],
        "dom_diffs": [],
        "console_logs": [],
        "network_log_path": None,
        "url_before": url,
        "url_after": url,
        "cookies_before": {},
        "cookies_after": {},
        "deterministic_signals": {},
    }


async def run_executor(
    job_id: str, target_url: str, scenario: dict, validation_result: dict, failure_states: dict
) -> tuple[dict, dict]:
    with traced_span("executor", session_id=job_id):
        scenario_id = scenario["scenario_id"]

        if not validation_result["approved"]:
            reasons = validation_result["deterministic_errors"] or [
                validation_result["llm_review_notes"]
            ]
            result = {
                "scenario_id": scenario_id,
                "status": "failure",
                "evidence": _empty_evidence(target_url),
                "error_message": f"skipped: rejected by validator ({'; '.join(reasons)})",
            }
            return result, failure_states

        settings = get_settings()
        payload = {"job_id": job_id, "target_url": target_url, "scenario": scenario}

        try:
            response = await call_agent(
                settings.selenium_executor_agent_url, payload, timeout=EXECUTOR_TIMEOUT
            )
        except AgentUnavailableError as exc:
            updated_failure_states = record_agent_failure(failure_states, "selenium_executor", exc)
            result = {
                "scenario_id": scenario_id,
                "status": "error",
                "evidence": _empty_evidence(target_url),
                "error_message": f"{EXECUTOR_UNAVAILABLE_PREFIX} {exc}",
            }
            return result, updated_failure_states

        result = response["execution_result"]
        updated_failure_states = record_agent_success(failure_states, "selenium_executor")
        return result, updated_failure_states

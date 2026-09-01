from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import (
    VALIDATOR_UNAVAILABLE_PREFIX,
    record_agent_failure,
    record_agent_success,
)
from app.observability import traced_span

VALIDATOR_TIMEOUT = 60.0


async def run_validator(job_id: str, scenario: dict, vision: dict) -> tuple[dict, dict]:
    with traced_span("validator", session_id=job_id):
        settings = get_settings()
        scenario_id = scenario["scenario_id"]
        payload = {"job_id": job_id, "scenario": scenario, "vision": vision}

        try:
            response = await call_agent(
                settings.validator_agent_url, payload, timeout=VALIDATOR_TIMEOUT
            )
        except AgentUnavailableError as exc:
            failure_delta = record_agent_failure("validator", exc)
            result = {
                "scenario_id": scenario_id,
                "deterministic_checks_passed": False,
                "deterministic_errors": [],
                "llm_review_passed": False,
                "llm_review_notes": f"{VALIDATOR_UNAVAILABLE_PREFIX} {exc}",
                "approved": False,
            }
            return result, failure_delta

        result = response["validation_result"]
        failure_delta = record_agent_success("validator")
        return result, failure_delta

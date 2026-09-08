from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import (
    EXECUTOR_UNAVAILABLE_PREFIX,
    record_agent_failure,
    record_agent_success,
)
from app.observability import traced_span

# Must stay comfortably above selenium-executor-agent's own
# chatbot_captcha_grace_seconds (default 180s, see docker-compose.yml) plus
# the time a multi-turn chatbot scenario's wait_for_response steps can take -
# up to response_timeout_ms (default 60s) per turn - same reasoning as
# DISCOVERY_TIMEOUT in discovery.py.
EXECUTOR_TIMEOUT = 420.0


def _empty_evidence(url: str) -> dict:
    return {
        "screenshots": [],
        "dom_diffs": [],
        "console_logs": [],
        "network_errors": [],
        "url_before": url,
        "url_after": url,
        "cookies_before": {},
        "cookies_after": {},
        "deterministic_signals": {},
    }


async def run_executor(
    job_id: str,
    target_url: str,
    scenario: dict,
    validation_result: dict,
    session_cookies: list[dict] | None = None,
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
            return result, {}

        settings = get_settings()
        payload = {
            "job_id": job_id,
            "target_url": target_url,
            "scenario": scenario,
            "session_cookies": session_cookies or [],
        }

        try:
            response = await call_agent(
                settings.selenium_executor_agent_url, payload, timeout=EXECUTOR_TIMEOUT
            )
        except AgentUnavailableError as exc:
            failure_delta = record_agent_failure("selenium_executor", exc)
            result = {
                "scenario_id": scenario_id,
                "status": "error",
                "evidence": _empty_evidence(target_url),
                "error_message": f"{EXECUTOR_UNAVAILABLE_PREFIX} {exc}",
            }
            return result, failure_delta

        result = response["execution_result"]
        failure_delta = record_agent_success("selenium_executor")
        return result, failure_delta

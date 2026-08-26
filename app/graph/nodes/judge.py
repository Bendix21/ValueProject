from app.clients.agent_client import AgentUnavailableError, call_agent
from app.config import get_settings
from app.graph.resilience import (
    JUDGE_UNAVAILABLE_PREFIX,
    record_agent_failure,
    record_agent_success,
)
from app.observability import traced_span

JUDGE_TIMEOUT = 60.0


async def run_judge(
    job_id: str, scenario: dict, execution_result: dict, failure_states: dict
) -> tuple[dict, dict]:
    with traced_span("judge", session_id=job_id):
        scenario_id = scenario["scenario_id"]
        settings = get_settings()
        payload = {
            "job_id": job_id,
            "scenario": scenario,
            "execution_result": execution_result,
        }

        try:
            response = await call_agent(settings.llm_judge_agent_url, payload, timeout=JUDGE_TIMEOUT)
        except AgentUnavailableError as exc:
            updated_failure_states = record_agent_failure(failure_states, "llm_judge", exc)
            verdict = {
                "scenario_id": scenario_id,
                "verdict": "fail",
                "deterministic_veto": True,
                "reasoning": f"{JUDGE_UNAVAILABLE_PREFIX} {exc}",
                "confidence": 1.0,
            }
            return verdict, updated_failure_states

        verdict = response["judge_verdict"]
        updated_failure_states = record_agent_success(failure_states, "llm_judge")
        return verdict, updated_failure_states

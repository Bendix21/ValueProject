CIRCUIT_BREAKER_THRESHOLD = 3

VALIDATOR_UNAVAILABLE_PREFIX = "validator agent unavailable:"
EXECUTOR_UNAVAILABLE_PREFIX = "executor agent unavailable:"
JUDGE_UNAVAILABLE_PREFIX = "judge agent unavailable:"


def record_agent_failure(failure_states: dict, agent_name: str, error: Exception) -> dict:
    failure_states = dict(failure_states)
    current = failure_states.get(agent_name)
    consecutive = (current["consecutive_failures"] if current else 0) + 1
    failure_states[agent_name] = {
        "agent_name": agent_name,
        "consecutive_failures": consecutive,
        "last_error": str(error),
        "degraded_mode": current["degraded_mode"] if current else False,
    }
    return failure_states


def record_agent_success(failure_states: dict, agent_name: str) -> dict:
    failure_states = dict(failure_states)
    if agent_name in failure_states and failure_states[agent_name]["consecutive_failures"] > 0:
        failure_states[agent_name] = {**failure_states[agent_name], "consecutive_failures": 0}
    return failure_states


def batch_circuit_breaker_tripped(state) -> bool:
    # Counted from the batch's own per-scenario results (one distinct dict key per scenario,
    # never contended between parallel branches) rather than from failure_states, which can
    # under-count when concurrent branches all read the same pre-dispatch snapshot.
    validator_failures = sum(
        1
        for v in state["validation_results"].values()
        if v["llm_review_notes"].startswith(VALIDATOR_UNAVAILABLE_PREFIX)
    )
    executor_failures = sum(
        1
        for r in state["execution_results"].values()
        if r["error_message"] and r["error_message"].startswith(EXECUTOR_UNAVAILABLE_PREFIX)
    )
    judge_failures = sum(
        1
        for j in state["judge_verdicts"].values()
        if j["reasoning"].startswith(JUDGE_UNAVAILABLE_PREFIX)
    )
    return max(validator_failures, executor_failures, judge_failures) >= CIRCUIT_BREAKER_THRESHOLD

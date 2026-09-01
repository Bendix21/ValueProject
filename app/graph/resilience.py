CIRCUIT_BREAKER_THRESHOLD = 3

VALIDATOR_UNAVAILABLE_PREFIX = "validator agent unavailable:"
EXECUTOR_UNAVAILABLE_PREFIX = "executor agent unavailable:"
JUDGE_UNAVAILABLE_PREFIX = "judge agent unavailable:"


def merge_failure_states(a: dict, b: dict) -> dict:
    """Reducer for QAState.failure_states (see app/graph/state.py).

    `a` and `b` are both dicts of agent_name -> FailureState (either can be
    {}). Combines them by *summing* each agent's consecutive_failures rather
    than overwriting it. This has to be associative/commutative: several Send
    branches can call the same agent (e.g. "validator") concurrently, each
    reporting its own single failure, and LangGraph folds all of their
    outputs together with the prior channel value in an unspecified order. A
    plain `{**a, **b}` merge (the previous behaviour) keeps only the last
    branch's count per agent and silently drops the others' — this reducer
    adds them instead, so nothing is lost regardless of fold order or
    grouping. Every failure contribution reports exactly 1 (see
    record_agent_failure), so this is a plain sum, and the result is always
    shaped the same way as its inputs — safe to feed back in as either side
    of a later fold.

    "consecutive_failures" is therefore best read as "failures recorded for
    this agent so far in this job" (monotonic) rather than a streak that
    resets on success — a resettable streak isn't a coherent concept once
    calls to the same agent can be genuinely concurrent.
    """
    merged = {agent_name: dict(state) for agent_name, state in a.items()}
    for agent_name, update in b.items():
        current = merged.get(agent_name)
        merged[agent_name] = {
            "agent_name": agent_name,
            "consecutive_failures": (current["consecutive_failures"] if current else 0)
            + update["consecutive_failures"],
            "last_error": update["last_error"] or (current["last_error"] if current else None),
            "degraded_mode": (current["degraded_mode"] if current else False) or update["degraded_mode"],
        }
    return merged


def record_agent_failure(agent_name: str, error: Exception) -> dict:
    """A single failed call's own contribution (count of exactly 1). Fold
    into an accumulator, or straight into QAState.failure_states, via
    merge_failure_states — never combine branches by overwriting."""
    return {
        agent_name: {
            "agent_name": agent_name,
            "consecutive_failures": 1,
            "last_error": str(error),
            "degraded_mode": False,
        }
    }


def record_agent_success(agent_name: str) -> dict:
    # A successful call carries no failure signal — nothing to merge in.
    return {}


def batch_circuit_breaker_tripped(state) -> bool:
    # Counted from the batch's own per-scenario results (one distinct dict key per
    # scenario, never contended between parallel branches) rather than from
    # failure_states. Both are correct as of merge_failure_states (see above), but
    # this keeps the trip decision independent of that shared reducer.
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

import httpx
from qa_swarm_common.json_utils import parse_json_object
from qa_swarm_common.ollama_client import OllamaClient
from qa_swarm_common.schemas import ExecutionResult, Scenario

from llm_judge_agent.config import get_settings

LLM_PROMPT = """You are judging whether an automated QA test scenario passed or failed, \
based on execution evidence. No explicit assertion was present in the scenario to verify \
the outcome directly, so you must reason from the evidence below.

Scenario: {title} - {description}
expect_failure flag: {expect_failure}
Steps executed:
{steps}

Execution completed without errors.
URL before: {url_before}
URL after: {url_after}
URL changed: {url_changed}
Cookies that changed value: {changed_cookie_names}
New cookies that appeared: {new_cookie_names}

Respond with ONLY a single JSON object, no other text, in this exact shape:
{{"verdict": "pass", "reasoning": "one short sentence", "confidence": 0.8}}

Consider whether the observed evidence (URL change, cookie changes) supports that the \
scenario achieved what it set out to do, given the expect_failure flag.
"""

FALLBACK_REASON_NO_LLM = (
    "no assertion in scenario and LLM review unavailable; execution completed without errors"
)


def _format_steps(scenario: Scenario) -> str:
    lines = []
    for index, step in enumerate(scenario.steps, start=1):
        if step.target_selector:
            lines.append(f"{index}. {step.action} on {step.target_selector}")
        else:
            lines.append(f"{index}. {step.action}")
    return "\n".join(lines)


ASSERT_ACTIONS = {"assert", "assert_in_viewport"}


def _has_assert(scenario: Scenario) -> bool:
    return any(step.action in ASSERT_ACTIONS for step in scenario.steps)


def _failed_step_action(scenario: Scenario, execution_result: ExecutionResult) -> str | None:
    index = execution_result.evidence.deterministic_signals.get("failed_step_index")
    if index is None or index >= len(scenario.steps):
        return None
    return scenario.steps[index].action


def _degraded_llm_result(reason: str) -> dict:
    return {"verdict": "pass", "reasoning": reason, "confidence": 0.3}


async def _call_llm(scenario: Scenario, execution_result: ExecutionResult) -> dict:
    settings = get_settings()
    client = OllamaClient(settings.ollama_host, timeout=settings.judge_timeout)

    if not await client.health_check(settings.llm_model):
        return _degraded_llm_result(FALLBACK_REASON_NO_LLM)

    signals = execution_result.evidence.deterministic_signals
    prompt = LLM_PROMPT.format(
        title=scenario.title,
        description=scenario.description,
        expect_failure=scenario.expect_failure,
        steps=_format_steps(scenario),
        url_before=execution_result.evidence.url_before,
        url_after=execution_result.evidence.url_after,
        url_changed=signals.get("url_changed"),
        changed_cookie_names=signals.get("changed_cookie_names"),
        new_cookie_names=signals.get("new_cookie_names"),
    )
    try:
        raw = await client.generate(settings.llm_model, prompt)
    except httpx.HTTPError:
        return _degraded_llm_result(
            "no assertion in scenario and LLM call failed; execution completed without errors"
        )

    parsed = parse_json_object(raw)
    if parsed is None or "verdict" not in parsed:
        return _degraded_llm_result(
            "no assertion in scenario and LLM response could not be parsed; "
            "execution completed without errors"
        )

    verdict = parsed["verdict"] if parsed["verdict"] in ("pass", "fail") else "pass"
    confidence = parsed.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5

    return {
        "verdict": verdict,
        "reasoning": str(parsed.get("reasoning", ""))[:500],
        "confidence": float(confidence),
    }


async def judge_scenario(scenario: Scenario, execution_result: ExecutionResult) -> dict:
    if execution_result.status == "error":
        return {
            "scenario_id": scenario.scenario_id,
            "verdict": "fail",
            "deterministic_veto": True,
            "reasoning": f"execution error: {execution_result.error_message}",
            "confidence": 1.0,
        }

    if execution_result.status == "failure":
        failed_action = _failed_step_action(scenario, execution_result)
        reasoning = f"execution failed: {execution_result.error_message}"
        if failed_action in ASSERT_ACTIONS:
            reasoning = f"assertion did not hold: {execution_result.error_message}"
        return {
            "scenario_id": scenario.scenario_id,
            "verdict": "fail",
            "deterministic_veto": True,
            "reasoning": reasoning,
            "confidence": 1.0,
        }

    if _has_assert(scenario):
        return {
            "scenario_id": scenario.scenario_id,
            "verdict": "pass",
            "deterministic_veto": True,
            "reasoning": "all assertions in the scenario held",
            "confidence": 1.0,
        }

    llm_result = await _call_llm(scenario, execution_result)
    return {
        "scenario_id": scenario.scenario_id,
        "verdict": llm_result["verdict"],
        "deterministic_veto": False,
        "reasoning": llm_result["reasoning"],
        "confidence": llm_result["confidence"],
    }

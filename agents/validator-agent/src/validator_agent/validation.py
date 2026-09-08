import httpx
from qa_swarm_common.json_utils import parse_json_object
from qa_swarm_common.ollama_client import OllamaClient
from qa_swarm_common.schemas import Scenario, VisionResult

from validator_agent.config import get_settings

ALLOWED_ACTIONS = {"click", "type", "select", "scroll", "wait", "assert", "assert_in_viewport"}
SELECTOR_REQUIRED_ACTIONS = {"click", "type", "select", "assert", "assert_in_viewport"}
VALUE_REQUIRED_ACTIONS = {"type", "select"}

CHATBOT_ACTIONS = {
    "send_message",
    "wait_for_response",
    "assert_response",
    "stop_generation",
    "regenerate",
}
CHATBOT_ALLOWED_ACTIONS = ALLOWED_ACTIONS | CHATBOT_ACTIONS
CHATBOT_SELECTOR_REQUIRED_ACTIONS = SELECTOR_REQUIRED_ACTIONS | {
    "send_message",
    "stop_generation",
    "regenerate",
}
CHATBOT_VALUE_REQUIRED_ACTIONS = VALUE_REQUIRED_ACTIONS | {"send_message"}
# wait_for_response/assert_response deliberately never require or accept a
# target_selector - they always read the whole page's response area.

REVIEW_PROMPT = """You are reviewing an automated QA test scenario for a web page, for quality \
and coherence.

Page summary: {page_summary}

Scenario title: {title}
Scenario description: {description}
expect_failure flag: {expect_failure}
Steps, in the order they will be executed:
{steps}

Respond with ONLY a single JSON object, no other text, in this exact shape:
{{"passed": true, "notes": "one short sentence explaining your assessment"}}

Consider:
- Do the steps follow a sensible order for a real user (e.g. fields are filled in before a \
form is submitted, not after)?
- Is the expect_failure flag consistent with what the scenario actually does (submitting \
invalid or incomplete data should be expect_failure=true; a normal successful flow should be \
expect_failure=false)?
- Is the scenario coherent given the page?
"""

CHATBOT_REVIEW_PROMPT = """You are reviewing an automated QA test scenario for a conversational \
chatbot web interface, for quality and coherence.

Page summary: {page_summary}

Scenario title: {title}
Scenario description: {description}
Steps, in the order they will be executed:
{steps}

Respond with ONLY a single JSON object, no other text, in this exact shape:
{{"passed": true, "notes": "one short sentence explaining your assessment"}}

Consider:
- Does every "send_message" have a plausible message for what the scenario claims to test?
- A scenario with a single "send_message" is completely normal and valid on its own - do NOT \
reject it for "lacking a follow-up" or "being incomplete". Only judge conversational coherence \
when the scenario actually has a second "send_message": in that case, does it read as a \
sensible follow-up to the first?
- Does the scenario end with an "assert_response" so the outcome is actually checked?
"""


def _is_chatbot_scenario(scenario: Scenario) -> bool:
    return any(step.action in CHATBOT_ACTIONS for step in scenario.steps)


def _format_steps(scenario: Scenario) -> str:
    lines = []
    for index, step in enumerate(scenario.steps, start=1):
        if step.action in VALUE_REQUIRED_ACTIONS | {"send_message"}:
            lines.append(f'{index}. {step.action} "{step.value}" into {step.target_selector}')
        elif step.action == "assert_response" and step.value:
            lines.append(f'{index}. {step.action} expecting "{step.value}"')
        elif step.target_selector:
            lines.append(f"{index}. {step.action} on {step.target_selector}")
        else:
            lines.append(f"{index}. {step.action}")
    return "\n".join(lines)


def _run_deterministic_checks(scenario: Scenario, known_selectors: set[str]) -> list[str]:
    chatbot = _is_chatbot_scenario(scenario)
    allowed_actions = CHATBOT_ALLOWED_ACTIONS if chatbot else ALLOWED_ACTIONS
    selector_required_actions = (
        CHATBOT_SELECTOR_REQUIRED_ACTIONS if chatbot else SELECTOR_REQUIRED_ACTIONS
    )
    value_required_actions = CHATBOT_VALUE_REQUIRED_ACTIONS if chatbot else VALUE_REQUIRED_ACTIONS

    errors = []

    if not scenario.title.strip():
        errors.append("title is empty")
    if not scenario.description.strip():
        errors.append("description is empty")
    if not scenario.steps:
        errors.append("scenario has no steps")
    if chatbot and scenario.steps and scenario.steps[0].action != "send_message":
        errors.append("chatbot scenario must start with 'send_message'")

    seen_scroll = False
    for index, step in enumerate(scenario.steps, start=1):
        if step.action not in allowed_actions:
            errors.append(f"step {index}: action '{step.action}' is not an allowed action")
            continue
        if step.action in {"wait_for_response", "assert_response"}:
            if step.target_selector:
                errors.append(
                    f"step {index}: '{step.action}' must never carry a target_selector "
                    "(it always reads the whole page's response area)"
                )
        elif step.action in selector_required_actions:
            if not step.target_selector:
                errors.append(f"step {index}: action '{step.action}' requires a target_selector")
            elif step.target_selector not in known_selectors:
                errors.append(
                    f"step {index}: target_selector '{step.target_selector}' does not match "
                    "any visible element"
                )
        if step.action in value_required_actions and not step.value:
            errors.append(f"step {index}: action '{step.action}' requires a non-empty value")
        if step.action == "assert_in_viewport" and not seen_scroll:
            errors.append(
                f"step {index}: 'assert_in_viewport' on '{step.target_selector}' has no "
                "preceding 'scroll' step, so the element is never brought into view before "
                "the assertion"
            )
        if step.action == "scroll":
            seen_scroll = True

    return errors


async def _run_llm_review(scenario: Scenario, page_summary: str) -> tuple[bool, str]:
    settings = get_settings()
    client = OllamaClient(settings.ollama_host, timeout=settings.review_timeout)

    if not await client.health_check(settings.llm_model):
        return True, "LLM review unavailable (Ollama/model unreachable), deterministic checks only"

    if _is_chatbot_scenario(scenario):
        prompt = CHATBOT_REVIEW_PROMPT.format(
            page_summary=page_summary,
            title=scenario.title,
            description=scenario.description,
            steps=_format_steps(scenario),
        )
    else:
        prompt = REVIEW_PROMPT.format(
            page_summary=page_summary,
            title=scenario.title,
            description=scenario.description,
            expect_failure=scenario.expect_failure,
            steps=_format_steps(scenario),
        )
    try:
        raw = await client.generate(settings.llm_model, prompt, options={"temperature": 0})
    except httpx.HTTPError:
        return True, "LLM review unavailable (request failed), deterministic checks only"

    parsed = parse_json_object(raw)
    if parsed is None or "passed" not in parsed:
        return True, "LLM review response could not be parsed, deterministic checks only"

    return bool(parsed["passed"]), str(parsed.get("notes", ""))[:500]


async def validate_scenario(scenario: Scenario, vision: VisionResult) -> dict:
    known_selectors = {element.selector for element in vision.enriched_elements if element.visible}

    deterministic_errors = _run_deterministic_checks(scenario, known_selectors)
    deterministic_checks_passed = not deterministic_errors

    if not deterministic_checks_passed:
        return {
            "scenario_id": scenario.scenario_id,
            "deterministic_checks_passed": False,
            "deterministic_errors": deterministic_errors,
            "llm_review_passed": False,
            "llm_review_notes": "skipped (deterministic checks failed)",
            "approved": False,
        }

    llm_review_passed, llm_review_notes = await _run_llm_review(scenario, vision.page_summary)

    return {
        "scenario_id": scenario.scenario_id,
        "deterministic_checks_passed": True,
        "deterministic_errors": [],
        "llm_review_passed": llm_review_passed,
        "llm_review_notes": llm_review_notes,
        "approved": llm_review_passed,
    }

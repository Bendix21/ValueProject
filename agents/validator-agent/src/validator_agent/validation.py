import httpx
from qa_swarm_common.json_utils import parse_json_object
from qa_swarm_common.ollama_client import OllamaClient
from qa_swarm_common.schemas import Scenario, VisionResult

from validator_agent.config import get_settings

ALLOWED_ACTIONS = {"click", "type", "select", "scroll", "wait", "assert", "assert_in_viewport"}
SELECTOR_REQUIRED_ACTIONS = {"click", "type", "select", "assert", "assert_in_viewport"}
VALUE_REQUIRED_ACTIONS = {"type", "select"}

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


def _format_steps(scenario: Scenario) -> str:
    lines = []
    for index, step in enumerate(scenario.steps, start=1):
        if step.action in VALUE_REQUIRED_ACTIONS:
            lines.append(f'{index}. {step.action} "{step.value}" into {step.target_selector}')
        elif step.target_selector:
            lines.append(f"{index}. {step.action} on {step.target_selector}")
        else:
            lines.append(f"{index}. {step.action}")
    return "\n".join(lines)


def _run_deterministic_checks(scenario: Scenario, known_selectors: set[str]) -> list[str]:
    errors = []

    if not scenario.title.strip():
        errors.append("title is empty")
    if not scenario.description.strip():
        errors.append("description is empty")
    if not scenario.steps:
        errors.append("scenario has no steps")

    seen_scroll = False
    for index, step in enumerate(scenario.steps, start=1):
        if step.action not in ALLOWED_ACTIONS:
            errors.append(f"step {index}: action '{step.action}' is not an allowed action")
            continue
        if step.action in SELECTOR_REQUIRED_ACTIONS:
            if not step.target_selector:
                errors.append(f"step {index}: action '{step.action}' requires a target_selector")
            elif step.target_selector not in known_selectors:
                errors.append(
                    f"step {index}: target_selector '{step.target_selector}' does not match "
                    "any visible element"
                )
        if step.action in VALUE_REQUIRED_ACTIONS and not step.value:
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

    prompt = REVIEW_PROMPT.format(
        page_summary=page_summary,
        title=scenario.title,
        description=scenario.description,
        expect_failure=scenario.expect_failure,
        steps=_format_steps(scenario),
    )
    try:
        raw = await client.generate(settings.llm_model, prompt)
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

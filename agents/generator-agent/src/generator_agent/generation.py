import json
import logging
import uuid

import httpx
from qa_swarm_common.json_utils import parse_json_object
from qa_swarm_common.ollama_client import OllamaClient
from qa_swarm_common.schemas import ElementInfo, VisionResult

from generator_agent.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"click", "type", "select", "scroll", "wait", "assert", "assert_in_viewport"}
SELECTOR_REQUIRED_ACTIONS = {"click", "type", "select", "assert", "assert_in_viewport"}
VALUE_REQUIRED_ACTIONS = {"type", "select"}

PROMPT_TEMPLATE = """You are generating automated QA test scenarios for a web page.

Page summary: {page_summary}

Interactive elements available on the page (use ONLY these selectors, do not invent others):
{elements}

Respond with ONLY a single JSON object, no other text, in this exact shape:
{{"scenarios": [{{"title": "short title", "description": "one sentence", \
"steps": [{{"action": "click|type|select|scroll|wait|assert|assert_in_viewport", \
"target_selector": "<selector from the list above, or null>", \
"value": "<text value, or null>"}}], "expect_failure": false, "priority": 1}}]}}

Rules:
- Only use target_selector values from the list above, copied exactly as written.
- "type" and "select" steps must have a non-null "value".
- Order steps the way a real user actually would, in this order: first any "scroll" needed \
to reveal a target, then the interaction with it ("click"/"type"/"select"), then any \
"assert"/"assert_in_viewport" LAST, checking the outcome of the action(s) before them. Never \
put a "click" on an element before the steps that lead a user to notice or reach it (e.g. \
never click a "submit"/navigation element before filling in the fields it depends on).
- Produce 1 to {max_scenarios} scenarios covering realistic user interactions with this page.
- Set "expect_failure": true ONLY for a scenario whose steps submit invalid or incomplete \
data into a real form element from the list above (e.g. leaving a required field empty, an \
invalid email format) and that expects the submission to be rejected. Never set it true for \
any other reason, and never invent a step that references something not in the list to \
manufacture a failure - every target_selector must be a real, visible element from the list \
above. If this page has no form to submit invalid data into, do not produce an \
expect_failure scenario at all.
- "assert" checks that an element is displayed (and optionally contains some text in \
"value"). Use it by default for any element you expect is already visible without \
scrolling (e.g. a top navigation link, a header, anything near the top of the page).
- "assert_in_viewport" is ONLY for confirming a "scroll" step actually brought a \
not-yet-visible element into view - use it ONLY for elements you have a real reason to \
believe are NOT visible without scrolling (e.g. a footer link, or content revealed by a \
same-page anchor link "#section"). Every "assert_in_viewport" step MUST be immediately \
preceded by a "scroll" step with the exact same target_selector. Never use \
"assert_in_viewport" on its own without that preceding "scroll" on the same element, and \
never use it for elements likely already visible on page load - use plain "assert" for those.
"""


def _format_elements(elements: list[ElementInfo]) -> str:
    lines = [
        f'- selector="{element.selector}" role={element.dom_role} '
        f'label="{element.ocr_text or element.visual_role or element.dom_role}"'
        for element in elements
    ]
    return "\n".join(lines) if lines else "(no interactive elements detected)"


def _validate_step(step: dict, known_selectors: set[str]) -> dict | None:
    if not isinstance(step, dict):
        return None
    action = step.get("action")
    if action not in ALLOWED_ACTIONS:
        return None
    target_selector = step.get("target_selector")
    value = step.get("value")
    if action in SELECTOR_REQUIRED_ACTIONS and (
        not target_selector or target_selector not in known_selectors
    ):
        return None
    if action in VALUE_REQUIRED_ACTIONS and not value:
        return None
    return {"action": action, "target_selector": target_selector, "value": value}


def _validate_scenario(candidate: dict, known_selectors: set[str]) -> dict | None:
    if not isinstance(candidate, dict):
        return None
    steps = []
    for raw_step in candidate.get("steps", []):
        step = _validate_step(raw_step, known_selectors)
        if step is None:
            return None
        steps.append(step)
    if not steps:
        return None

    priority = candidate.get("priority", 1)
    if not isinstance(priority, int):
        priority = 1

    return {
        "title": str(candidate.get("title", "Untitled scenario"))[:200],
        "description": str(candidate.get("description", ""))[:500],
        "steps": steps,
        "expect_failure": bool(candidate.get("expect_failure", False)),
        "priority": priority,
    }


FALLBACK_ROLE_PRIORITY = {
    "button": 0,
    "submit_input": 0,
    "link": 1,
}
FALLBACK_DEFAULT_ROLE_PRIORITY = 2


def _fallback_target(elements: list[ElementInfo]) -> ElementInfo | None:
    if not elements:
        return None
    return min(
        elements,
        key=lambda e: FALLBACK_ROLE_PRIORITY.get(e.dom_role, FALLBACK_DEFAULT_ROLE_PRIORITY),
    )


def _fallback_scenario(elements: list[ElementInfo]) -> dict:
    target = _fallback_target(elements)
    if target is None:
        steps = [{"action": "wait", "target_selector": None, "value": "1000"}]
    else:
        steps = [
            {"action": "click", "target_selector": target.selector, "value": None},
            {"action": "assert", "target_selector": target.selector, "value": None},
        ]
    return {
        "title": "Fallback smoke scenario",
        "description": "Deterministic fallback generated without LLM assistance.",
        "steps": steps,
        "expect_failure": False,
        "priority": 1,
    }


def _finalize_scenarios(raw_scenarios: list[dict], max_scenarios: int, page_url: str) -> list[dict]:
    return [
        {
            "scenario_id": f"scn-{uuid.uuid4().hex[:8]}",
            "page_url": page_url,
            "title": raw["title"],
            "description": raw["description"],
            "steps": raw["steps"],
            "expect_failure": raw["expect_failure"],
            "priority": raw["priority"],
        }
        for raw in raw_scenarios[:max_scenarios]
    ]


async def _call_llm(
    client: OllamaClient,
    settings,
    page_summary: str,
    elements: list[ElementInfo],
    max_scenarios: int,
) -> dict | None:
    prompt = PROMPT_TEMPLATE.format(
        page_summary=page_summary,
        elements=_format_elements(elements),
        max_scenarios=max_scenarios,
    )
    try:
        raw = await client.generate(settings.llm_model, prompt)
    except httpx.HTTPError:
        return None
    return parse_json_object(raw)


async def generate_scenarios(
    vision: VisionResult, page_url: str, max_scenarios: int | None = None
) -> list[dict]:
    settings = get_settings()
    max_scenarios = max_scenarios or settings.max_scenarios
    visible_elements = [element for element in vision.enriched_elements if element.visible]
    known_selectors = {element.selector for element in visible_elements}

    client = OllamaClient(settings.ollama_host, timeout=settings.generation_timeout)
    valid_scenarios: list[dict] = []

    if not await client.health_check(settings.llm_model):
        logger.warning(
            "generator: LLM %s not available (health_check failed), using fallback scenario",
            settings.llm_model,
        )
    else:
        parsed = await _call_llm(
            client, settings, vision.page_summary, visible_elements, max_scenarios
        )
        if parsed is None:
            logger.warning(
                "generator: LLM response could not be parsed as JSON, using fallback scenario"
            )
        else:
            raw_candidates = parsed.get("scenarios", [])
            for candidate in raw_candidates:
                validated = _validate_scenario(candidate, known_selectors)
                if validated:
                    valid_scenarios.append(validated)
                else:
                    logger.warning(
                        "generator: rejected candidate scenario (invalid action/selector/value): %s",
                        json.dumps(candidate)[:500],
                    )
            logger.info(
                "generator: LLM proposed %d candidate scenario(s), %d passed validation "
                "(max_scenarios=%d)",
                len(raw_candidates),
                len(valid_scenarios),
                max_scenarios,
            )

    if not valid_scenarios:
        valid_scenarios = [_fallback_scenario(visible_elements)]

    finalized = _finalize_scenarios(valid_scenarios, max_scenarios, page_url)
    if len(finalized) < max_scenarios:
        logger.info(
            "generator: returning %d scenario(s), below requested max_scenarios=%d",
            len(finalized),
            max_scenarios,
        )
    return finalized

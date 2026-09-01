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
INTERACTION_ACTIONS = {"click", "type", "select"}

# dom_role values (assigned by discovery-agent's roleFor) that accept a "type" step.
# input elements are reported as "<type>_input"; <textarea> as "textbox"; ARIA
# overrides may surface "textbox"/"searchbox".
TYPEABLE_ROLES = {
    "text_input",
    "email_input",
    "tel_input",
    "number_input",
    "password_input",
    "search_input",
    "url_input",
    "date_input",
    "time_input",
    "datetime-local_input",
    "month_input",
    "week_input",
    "color_input",
    "textbox",
    "textarea",
    "searchbox",
}
SELECTABLE_ROLES = {"select", "combobox", "listbox"}

# A scenario is never allowed to grow past this many steps.
MAX_STEPS = 12

PROMPT_TEMPLATE = """You are generating automated QA test scenarios for a web page.

Page summary: {page_summary}

Interactive elements available on the page. Each line gives a CSS selector, its DOM \
role, and its "kind" (what you are allowed to do with it):
{elements}

Element kinds:
- kind=typeable   -> a text field. You MAY "type" a value into it. NEVER "click" it as \
if it were a button.
- kind=selectable -> a dropdown. You MAY "select" a value in it.
- kind=clickable  -> a link, button or similar. You MAY "click" it. NEVER "type" into it.

Respond with ONLY a single JSON object, no other text, in this exact shape:
{{"scenarios": [{{"title": "short title", "description": "one sentence", \
"steps": [{{"action": "click|type|select|scroll|wait|assert|assert_in_viewport", \
"target_selector": "<selector from the list above, or null>", \
"value": "<text value, or null>"}}], "expect_failure": false, "priority": 1}}]}}

Rules:
- Use target_selector values copied EXACTLY from the list above. Never invent one.
- "type" is ONLY allowed on kind=typeable elements. "select" is ONLY allowed on \
kind=selectable elements. If the list contains no typeable element, do NOT produce any \
"type" step and do NOT produce an expect_failure scenario.
- Build every scenario's steps in exactly this order:
  1. an optional "scroll" to reveal an element far down the page,
  2. the interactions a real user performs, in natural order - fill EVERY field with \
"type" BEFORE the "click" that submits them,
  3. every "assert" / "assert_in_viewport" LAST, checking the outcome of the steps above.
  Never place an "assert" before the interaction it is meant to verify. Never click a \
submit or navigation element before the fields it depends on are filled.
- A "click" on a link (role=link) navigates away from this page; afterwards the elements \
above no longer apply. Make a link "click" the LAST step of its scenario, with no steps \
after it.
- "assert" checks that an element is displayed (optionally containing the "value" text). \
Use it for elements visible without scrolling (top navigation, headings).
- "assert_in_viewport" ONLY confirms that a preceding "scroll" worked. Every \
"assert_in_viewport" MUST be immediately preceded by a "scroll" step with the SAME \
target_selector. Otherwise use plain "assert".
- Set "expect_failure": true ONLY for a scenario that types invalid or incomplete data \
into a real typeable element and then submits it, expecting rejection. Never otherwise.
- Produce 1 to {max_scenarios} scenarios covering realistic user interactions.

Good example (page has a search box [typeable] "#q" and a button [clickable] "#go"):
{{"title": "Search for a product", "description": "User searches for a keyword.", \
"steps": [{{"action": "type", "target_selector": "#q", "value": "shoes"}}, \
{{"action": "click", "target_selector": "#go", "value": null}}, \
{{"action": "assert", "target_selector": "#results", "value": null}}], \
"expect_failure": false, "priority": 1}}

Bad example (DO NOT do this - types into a link, asserts before acting, step after a \
link click):
{{"title": "bad", "description": "bad", \
"steps": [{{"action": "assert", "target_selector": "nav a", "value": null}}, \
{{"action": "type", "target_selector": "nav a", "value": "John"}}, \
{{"action": "click", "target_selector": "nav a", "value": null}}, \
{{"action": "assert", "target_selector": "footer", "value": null}}], \
"expect_failure": false, "priority": 1}}
"""

REPAIR_HINT = (
    "Your previous response was not a single valid JSON object. Respond again with ONLY "
    "the JSON object described above - no prose, no markdown fences."
)


def _role_kind(role: str) -> str:
    if role in TYPEABLE_ROLES:
        return "typeable"
    if role in SELECTABLE_ROLES:
        return "selectable"
    return "clickable"


def _format_elements(elements: list[ElementInfo]) -> str:
    lines = [
        f'- selector="{element.selector}" role={element.dom_role} '
        f"kind={_role_kind(element.dom_role)} "
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
    # Drop individual malformed steps (bad action, unknown selector, missing value)
    # rather than discarding the whole scenario over one bad step.
    steps = []
    for raw_step in candidate.get("steps", []):
        step = _validate_step(raw_step, known_selectors)
        if step is not None:
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


def _repair_scenario(scenario: dict, roles: dict[str, str]) -> dict | None:
    """Deterministically rewrite an LLM scenario so it obeys the same rules the
    validator-agent enforces: action/role compatibility, asserts last, a scroll
    before every assert_in_viewport, a link click as the final step, and an
    expect_failure flag that matches what the steps actually do. Returns None if
    nothing viable remains."""
    steps = [dict(step) for step in scenario["steps"][:MAX_STEPS]]

    # 1. Drop type/select steps aimed at an element whose role does not support them
    #    (e.g. "type" into an <a>).
    kept: list[dict] = []
    for step in steps:
        kind = _role_kind(roles.get(step["target_selector"], ""))
        if step["action"] == "type" and kind != "typeable":
            continue
        if step["action"] == "select" and kind != "selectable":
            continue
        kept.append(step)
    steps = kept

    # 2. Re-emit every assertion after the interactions it checks. A plain "assert"
    #    moves to the end; an "assert_in_viewport" moves as a unit with a "scroll"
    #    on the same selector immediately before it (reusing an existing one, or
    #    synthesising it when the model omitted it).
    interactions: list[dict] = []
    plain_asserts: list[dict] = []
    viewport_pairs: list[list[dict]] = []
    for step in steps:
        if step["action"] == "assert":
            plain_asserts.append(step)
        elif step["action"] == "assert_in_viewport":
            if (
                interactions
                and interactions[-1]["action"] == "scroll"
                and interactions[-1]["target_selector"] == step["target_selector"]
            ):
                scroll = interactions.pop()
            else:
                scroll = {
                    "action": "scroll",
                    "target_selector": step["target_selector"],
                    "value": None,
                }
            viewport_pairs.append([scroll, step])
        else:
            interactions.append(step)
    steps = interactions + plain_asserts + [s for pair in viewport_pairs for s in pair]

    # 3. A link click navigates away; make it the last step of the scenario.
    truncated: list[dict] = []
    for step in steps:
        truncated.append(step)
        if step["action"] == "click" and roles.get(step["target_selector"]) == "link":
            break
    steps = truncated

    # 4. Keep only scenarios that still perform a real interaction.
    if not any(step["action"] in INTERACTION_ACTIONS for step in steps):
        return None

    # 5. expect_failure only survives if invalid data is typed and then submitted.
    first_type = next((i for i, s in enumerate(steps) if s["action"] == "type"), None)
    submits_after_type = first_type is not None and any(
        step["action"] == "click" for step in steps[first_type + 1 :]
    )
    expect_failure = bool(scenario["expect_failure"] and submits_after_type)

    return {
        "title": scenario["title"],
        "description": scenario["description"],
        "steps": steps,
        "expect_failure": expect_failure,
        "priority": scenario["priority"],
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


async def _generate_json(client: OllamaClient, settings, prompt: str) -> dict | None:
    """Ask Ollama for a JSON object, with one repair retry and raw-response logging
    on parse failure."""
    try:
        raw = await client.generate(
            settings.llm_model, prompt, format="json", options={"temperature": 0}
        )
    except httpx.HTTPError:
        return None
    parsed = parse_json_object(raw)
    if parsed is not None:
        return parsed

    logger.warning(
        "generator: LLM response not parseable as JSON, retrying once. Raw (truncated): %s",
        (raw or "")[:500].replace("\n", " "),
    )
    try:
        raw = await client.generate(
            settings.llm_model,
            f"{prompt}\n\n{REPAIR_HINT}",
            format="json",
            options={"temperature": 0},
        )
    except httpx.HTTPError:
        return None
    parsed = parse_json_object(raw)
    if parsed is None:
        logger.warning(
            "generator: retry response also not parseable as JSON. Raw (truncated): %s",
            (raw or "")[:500].replace("\n", " "),
        )
    return parsed


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
    return await _generate_json(client, settings, prompt)


async def generate_scenarios(
    vision: VisionResult, page_url: str, max_scenarios: int | None = None
) -> list[dict]:
    settings = get_settings()
    max_scenarios = max_scenarios or settings.max_scenarios
    visible_elements = [element for element in vision.enriched_elements if element.visible]
    known_selectors = {element.selector for element in visible_elements}
    roles = {element.selector: element.dom_role for element in visible_elements}

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
                if validated is None:
                    logger.warning(
                        "generator: rejected candidate scenario (no valid steps): %s",
                        json.dumps(candidate)[:500],
                    )
                    continue
                repaired = _repair_scenario(validated, roles)
                if repaired is None:
                    logger.warning(
                        "generator: candidate dropped by repair (no viable interaction left): %s",
                        json.dumps(candidate)[:300],
                    )
                    continue
                valid_scenarios.append(repaired)
            logger.info(
                "generator: LLM proposed %d candidate scenario(s), %d kept after repair "
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

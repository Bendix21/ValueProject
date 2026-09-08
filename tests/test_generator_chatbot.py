import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "agents" / "generator-agent" / "src")
)
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "libs" / "qa_swarm_common" / "src")
)

from qa_swarm_common.schemas import BBox, ElementInfo  # noqa: E402

from generator_agent.generation import (  # noqa: E402
    _chatbot_role_kind,
    _repair_scenario_chatbot,
    _validate_scenario_chatbot,
)

CHAT_INPUT = "#prompt"
SEND_BTN = "#send"
STOP_BTN = "#stop"
REGEN_BTN = "#regen"
OTHER_LINK = "footer a"


def _element(selector: str, dom_role: str, label: str | None = None) -> ElementInfo:
    return ElementInfo(
        element_id=selector,
        selector=selector,
        bbox=BBox(x=0, y=0, width=10, height=10),
        dom_role=dom_role,
        ocr_text=label,
        visual_role=None,
        confidence_score=1.0,
        visible=True,
        rendering_mismatch=False,
    )


KINDS = {
    CHAT_INPUT: "chat_input",
    SEND_BTN: "send_button",
    STOP_BTN: "stop_button",
    REGEN_BTN: "regenerate_button",
    OTHER_LINK: "other",
}
KNOWN_SELECTORS = set(KINDS)


def _scenario(steps, priority=1):
    return {
        "title": "t",
        "description": "d",
        "steps": [{"action": a, "target_selector": s, "value": v} for (a, s, v) in steps],
        "expect_failure": False,
        "priority": priority,
    }


def test_chatbot_role_kind_classification():
    assert _chatbot_role_kind(_element(CHAT_INPUT, "textbox")) == "chat_input"
    assert _chatbot_role_kind(_element(SEND_BTN, "button", "Send")) == "send_button"
    assert _chatbot_role_kind(_element(STOP_BTN, "button", "Stop generating")) == "stop_button"
    assert _chatbot_role_kind(_element(REGEN_BTN, "button", "Regenerate response")) == "regenerate_button"
    assert _chatbot_role_kind(_element(OTHER_LINK, "link", "Privacy policy")) == "other"


def test_validate_scenario_chatbot_forces_null_selector_on_response_steps():
    validated = _validate_scenario_chatbot(
        _scenario(
            [
                ("send_message", CHAT_INPUT, "hello"),
                ("wait_for_response", "#reply-box", None),
                ("assert_response", "#reply-box", "hi"),
            ]
        ),
        KNOWN_SELECTORS,
        KINDS,
    )
    assert validated is not None
    assert [s["target_selector"] for s in validated["steps"]] == [CHAT_INPUT, None, None]


def test_validate_scenario_chatbot_drops_send_message_on_non_chat_input():
    validated = _validate_scenario_chatbot(
        _scenario([("send_message", OTHER_LINK, "hello")]),
        KNOWN_SELECTORS,
        KINDS,
    )
    assert validated is None


def test_validate_scenario_chatbot_drops_stop_generation_without_stop_button():
    validated = _validate_scenario_chatbot(
        _scenario(
            [
                ("send_message", CHAT_INPUT, "hello"),
                ("stop_generation", CHAT_INPUT, None),
            ]
        ),
        KNOWN_SELECTORS,
        KINDS,
    )
    assert validated is not None
    assert [s["action"] for s in validated["steps"]] == ["send_message"]


def test_repair_inserts_missing_wait_for_response_and_trailing_assert():
    validated = _validate_scenario_chatbot(
        _scenario([("send_message", CHAT_INPUT, "hello")]),
        KNOWN_SELECTORS,
        KINDS,
    )
    repaired = _repair_scenario_chatbot(validated)
    assert repaired is not None
    assert [s["action"] for s in repaired["steps"]] == [
        "send_message",
        "wait_for_response",
        "assert_response",
    ]


def test_repair_drops_steps_before_first_send_message():
    validated = _validate_scenario_chatbot(
        _scenario(
            [
                ("regenerate", REGEN_BTN, None),
                ("send_message", CHAT_INPUT, "hello"),
                ("wait_for_response", None, None),
                ("assert_response", None, None),
            ]
        ),
        KNOWN_SELECTORS,
        KINDS,
    )
    repaired = _repair_scenario_chatbot(validated)
    assert repaired is not None
    assert repaired["steps"][0]["action"] == "send_message"


def test_repair_keeps_multi_turn_conversation_intact():
    validated = _validate_scenario_chatbot(
        _scenario(
            [
                ("send_message", CHAT_INPUT, "hello"),
                ("wait_for_response", None, None),
                ("send_message", CHAT_INPUT, "and then?"),
                ("wait_for_response", None, None),
                ("assert_response", None, "sure"),
            ]
        ),
        KNOWN_SELECTORS,
        KINDS,
    )
    repaired = _repair_scenario_chatbot(validated)
    assert repaired is not None
    assert [s["action"] for s in repaired["steps"]] == [
        "send_message",
        "wait_for_response",
        "send_message",
        "wait_for_response",
        "assert_response",
    ]


def test_repair_returns_none_when_no_send_message_survives():
    validated = _validate_scenario_chatbot(
        _scenario([("wait_for_response", None, None)]),
        KNOWN_SELECTORS,
        KINDS,
    )
    assert validated is not None
    assert _repair_scenario_chatbot(validated) is None

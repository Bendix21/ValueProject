import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "agents" / "generator-agent" / "src")
)

from generator_agent.generation import (  # noqa: E402
    _repair_scenario,
    _role_kind,
    _validate_scenario,
)

LINK = "nav > a"
BTN = "form button"
FIELD = "#name"
SUBMIT = "#submit"
HEADING = "h1"
FOOTER = "footer a"

ROLES = {
    LINK: "link",
    BTN: "button",
    FIELD: "text_input",
    SUBMIT: "submit_input",
    HEADING: "h1",
    FOOTER: "link",
}


def _scenario(steps, expect_failure=False):
    return {
        "title": "t",
        "description": "d",
        "steps": [
            {"action": a, "target_selector": s, "value": v} for (a, s, v) in steps
        ],
        "expect_failure": expect_failure,
        "priority": 1,
    }


def test_role_kind_mapping():
    assert _role_kind("text_input") == "typeable"
    assert _role_kind("textbox") == "typeable"
    assert _role_kind("select") == "selectable"
    assert _role_kind("link") == "clickable"
    assert _role_kind("button") == "clickable"
    assert _role_kind("h1") == "clickable"


def test_type_into_link_is_dropped():
    repaired = _repair_scenario(
        _scenario(
            [
                ("type", LINK, "John Doe"),
                ("type", LINK, "john@example.com"),
                ("click", BTN, None),
            ]
        ),
        ROLES,
    )
    assert repaired is not None
    assert [s["action"] for s in repaired["steps"]] == ["click"]
    assert repaired["steps"][0]["target_selector"] == BTN


def test_asserts_moved_after_interactions():
    repaired = _repair_scenario(
        _scenario(
            [
                ("assert", HEADING, None),
                ("click", BTN, None),
            ]
        ),
        ROLES,
    )
    assert [s["action"] for s in repaired["steps"]] == ["click", "assert"]


def test_assert_in_viewport_gets_a_preceding_scroll():
    repaired = _repair_scenario(
        _scenario(
            [
                ("click", BTN, None),
                ("assert_in_viewport", FOOTER, None),
            ]
        ),
        ROLES,
    )
    actions = [(s["action"], s["target_selector"]) for s in repaired["steps"]]
    # a link-click truncates, but BTN is a button, not a link, so nothing is cut here
    assert ("scroll", FOOTER) in actions
    i = actions.index(("scroll", FOOTER))
    assert actions[i + 1] == ("assert_in_viewport", FOOTER)


def test_existing_scroll_before_assert_in_viewport_is_not_duplicated():
    repaired = _repair_scenario(
        _scenario(
            [
                ("scroll", FOOTER, None),
                ("assert_in_viewport", FOOTER, None),
                ("click", BTN, None),
            ]
        ),
        ROLES,
    )
    actions = [s["action"] for s in repaired["steps"]]
    assert actions.count("scroll") == 1


def test_link_click_truncates_scenario():
    repaired = _repair_scenario(
        _scenario(
            [
                ("click", LINK, None),
                ("assert", HEADING, None),
                ("type", FIELD, "x"),
            ]
        ),
        ROLES,
    )
    assert [s["action"] for s in repaired["steps"]] == ["click"]
    assert repaired["steps"][0]["target_selector"] == LINK


def test_expect_failure_downgraded_when_no_form_submission():
    repaired = _repair_scenario(
        _scenario([("click", BTN, None)], expect_failure=True),
        ROLES,
    )
    assert repaired["expect_failure"] is False


def test_expect_failure_kept_for_real_form_submission():
    repaired = _repair_scenario(
        _scenario(
            [
                ("type", FIELD, "not-an-email"),
                ("click", SUBMIT, None),
            ],
            expect_failure=True,
        ),
        ROLES,
    )
    assert repaired["expect_failure"] is True
    assert [s["action"] for s in repaired["steps"]] == ["type", "click"]


def test_scenario_without_interaction_is_dropped():
    assert (
        _repair_scenario(_scenario([("assert", HEADING, None)]), ROLES) is None
    )


def test_validate_scenario_drops_bad_steps_instead_of_whole_scenario():
    validated = _validate_scenario(
        {
            "title": "t",
            "description": "d",
            "steps": [
                {"action": "click", "target_selector": BTN, "value": None},
                {"action": "click", "target_selector": "#does-not-exist", "value": None},
                {"action": "type", "target_selector": FIELD, "value": None},  # missing value
            ],
            "expect_failure": False,
            "priority": 1,
        },
        {BTN, FIELD},
    )
    assert validated is not None
    assert [s["action"] for s in validated["steps"]] == ["click"]


def test_full_repair_of_the_observed_bad_appointment_scenario():
    # Reproduces scn-0807bdd6 from job 2b820a3c: type into <a>, type into <a>,
    # click <a>, assert on an element from another page.
    a1 = "section:nth-of-type(6) > div > a:nth-of-type(1)"
    a2 = "section:nth-of-type(6) > div > a:nth-of-type(2)"
    nav = "nav > div > div:nth-of-type(3) > a"
    roles = {a1: "link", a2: "link", nav: "link"}
    repaired = _repair_scenario(
        _scenario(
            [
                ("type", a1, "John Doe"),
                ("type", a2, "john.doe@example.com"),
                ("click", a2, None),
                ("assert", nav, None),
            ],
            expect_failure=True,
        ),
        roles,
    )
    assert repaired is not None
    assert [s["action"] for s in repaired["steps"]] == ["click"]
    assert repaired["steps"][0]["target_selector"] == a2
    assert repaired["expect_failure"] is False

import operator
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, TypedDict

from app.graph.resilience import merge_failure_states


class BBox(TypedDict):
    x: int
    y: int
    width: int
    height: int


class ElementInfo(TypedDict):
    element_id: str
    selector: str
    bbox: BBox
    dom_role: str
    ocr_text: str | None
    visual_role: str | None
    confidence_score: float
    visible: bool
    rendering_mismatch: bool


class ViewportCapture(TypedDict):
    viewport_name: str
    width: int
    height: int
    screenshot_path: str
    elements: list[ElementInfo]


class DiscoveryResult(TypedDict):
    target_url: str
    viewports: list[ViewportCapture]
    dom_snapshot_path: str | None


class VisionResult(TypedDict):
    page_summary: str
    vision_mode: Literal["full", "ocr_only"]
    enriched_elements: list[ElementInfo]


class ScenarioStep(TypedDict):
    action: Literal["click", "type", "select", "scroll", "wait", "assert", "assert_in_viewport"]
    target_selector: str | None
    value: str | None


class Scenario(TypedDict):
    scenario_id: str
    page_url: str
    title: str
    description: str
    steps: list[ScenarioStep]
    expect_failure: bool
    priority: int


class ValidationResult(TypedDict):
    scenario_id: str
    deterministic_checks_passed: bool
    deterministic_errors: list[str]
    llm_review_passed: bool
    llm_review_notes: str
    approved: bool


class EvidenceCapture(TypedDict):
    screenshots: list[str]
    dom_diffs: list[dict]
    console_logs: list[str]
    network_errors: list[str]
    url_before: str
    url_after: str
    cookies_before: dict
    cookies_after: dict
    deterministic_signals: dict


class ExecutionResult(TypedDict):
    scenario_id: str
    status: Literal["success", "failure", "error"]
    evidence: EvidenceCapture
    error_message: str | None


class JudgeVerdict(TypedDict):
    scenario_id: str
    verdict: Literal["pass", "fail"]
    deterministic_veto: bool
    reasoning: str
    confidence: float


class FailureState(TypedDict):
    agent_name: str
    consecutive_failures: int
    last_error: str | None
    degraded_mode: bool


def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}


class QAState(TypedDict):
    job_id: str
    target_url: str
    status: Literal[
        "pending",
        "discovering",
        "vision",
        "generating",
        "selecting",
        "validating",
        "executing",
        "judging",
        "advancing",
        "finalizing",
        "completed",
        "failed",
        "circuit_broken",
        "cancelled",
    ]
    pages: dict[str, DiscoveryResult]
    vision_results: Annotated[dict[str, VisionResult], merge_dicts]
    max_scenarios: int | None
    max_pages: int | None
    current_page_url: str | None
    scenarios: Annotated[list[Scenario], operator.add]
    current_scenario_index: int
    selected_scenario: Scenario | None
    validation_results: Annotated[dict[str, ValidationResult], merge_dicts]
    execution_results: Annotated[dict[str, ExecutionResult], merge_dicts]
    judge_verdicts: Annotated[dict[str, JudgeVerdict], merge_dicts]
    failure_states: Annotated[dict[str, FailureState], merge_failure_states]
    circuit_breaker_tripped: bool
    final_report: dict | None
    created_at: str
    updated_at: str


def new_qa_state(
    target_url: str,
    job_id: str | None = None,
    max_scenarios: int | None = None,
    max_pages: int | None = None,
) -> QAState:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": job_id or str(uuid.uuid4()),
        "target_url": target_url,
        "status": "pending",
        "pages": {},
        "vision_results": {},
        "max_scenarios": max_scenarios,
        "max_pages": max_pages,
        "current_page_url": None,
        "scenarios": [],
        "current_scenario_index": 0,
        "selected_scenario": None,
        "validation_results": {},
        "execution_results": {},
        "judge_verdicts": {},
        "failure_states": {},
        "circuit_breaker_tripped": False,
        "final_report": None,
        "created_at": now,
        "updated_at": now,
    }

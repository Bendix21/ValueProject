from typing import Literal

from pydantic import BaseModel


class BBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class ElementInfo(BaseModel):
    element_id: str
    selector: str
    bbox: BBox
    dom_role: str
    ocr_text: str | None = None
    visual_role: str | None = None
    confidence_score: float
    visible: bool
    rendering_mismatch: bool


class ViewportCapture(BaseModel):
    viewport_name: str
    width: int
    height: int
    screenshot_path: str
    elements: list[ElementInfo] = []


class DiscoveryResult(BaseModel):
    target_url: str
    viewports: list[ViewportCapture]
    dom_snapshot_path: str | None = None
    blocked: bool = False
    block_reason: str | None = None


class VisionResult(BaseModel):
    page_summary: str
    vision_mode: Literal["full", "ocr_only"]
    enriched_elements: list[ElementInfo] = []


class ScenarioStep(BaseModel):
    action: Literal["click", "type", "select", "scroll", "wait", "assert", "assert_in_viewport"]
    target_selector: str | None = None
    value: str | None = None


class Scenario(BaseModel):
    scenario_id: str
    page_url: str
    title: str
    description: str
    steps: list[ScenarioStep] = []
    expect_failure: bool = False
    priority: int = 1


class ValidationResult(BaseModel):
    scenario_id: str
    deterministic_checks_passed: bool
    deterministic_errors: list[str] = []
    llm_review_passed: bool
    llm_review_notes: str
    approved: bool


class EvidenceCapture(BaseModel):
    screenshots: list[str] = []
    dom_diffs: list[dict] = []
    console_logs: list[str] = []
    network_log_path: str | None = None
    url_before: str
    url_after: str
    cookies_before: dict = {}
    cookies_after: dict = {}
    deterministic_signals: dict = {}


class ExecutionResult(BaseModel):
    scenario_id: str
    status: Literal["success", "failure", "error"]
    evidence: EvidenceCapture
    error_message: str | None = None


class JudgeVerdict(BaseModel):
    scenario_id: str
    verdict: Literal["pass", "fail"]
    deterministic_veto: bool
    reasoning: str
    confidence: float


class DiscoveryRequest(BaseModel):
    job_id: str
    target_url: str
    max_pages: int | None = None


class DiscoveryResponse(BaseModel):
    status: str
    pages: list[DiscoveryResult]
    updated_at: str


class VisionRequest(BaseModel):
    job_id: str
    discovery: DiscoveryResult


class VisionResponse(BaseModel):
    status: str
    vision: VisionResult
    updated_at: str


class GeneratorRequest(BaseModel):
    job_id: str
    target_url: str
    vision: VisionResult
    max_scenarios: int | None = None


class GeneratorResponse(BaseModel):
    status: str
    scenarios: list[Scenario]
    current_scenario_index: int
    updated_at: str


class ValidatorRequest(BaseModel):
    job_id: str
    scenario: Scenario
    vision: VisionResult


class ValidatorResponse(BaseModel):
    status: str
    validation_result: ValidationResult
    updated_at: str


class ExecutorRequest(BaseModel):
    job_id: str
    target_url: str
    scenario: Scenario


class ExecutorResponse(BaseModel):
    status: str
    execution_result: ExecutionResult
    updated_at: str


class JudgeRequest(BaseModel):
    job_id: str
    scenario: Scenario
    execution_result: ExecutionResult


class JudgeResponse(BaseModel):
    status: str
    judge_verdict: JudgeVerdict
    updated_at: str

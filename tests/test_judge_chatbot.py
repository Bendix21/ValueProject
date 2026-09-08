import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "llm-judge-agent" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs" / "qa_swarm_common" / "src"))

from qa_swarm_common.ollama_client import OllamaClient  # noqa: E402
from qa_swarm_common.schemas import (  # noqa: E402
    EvidenceCapture,
    ExecutionResult,
    Scenario,
    ScenarioStep,
)

from llm_judge_agent import judging  # noqa: E402


def _chatbot_scenario(title="Ask a question", description="Factual question test") -> Scenario:
    return Scenario(
        scenario_id="scn-1",
        page_url="https://chat.example.com",
        title=title,
        description=description,
        steps=[
            ScenarioStep(action="send_message", target_selector="#prompt", value="Hi"),
            ScenarioStep(action="wait_for_response", target_selector=None, value=None),
            ScenarioStep(action="assert_response", target_selector=None, value=None),
        ],
        expect_failure=False,
        priority=1,
    )


def _execution_result(status: str, transcript=None, failed_step_index=None) -> ExecutionResult:
    return ExecutionResult(
        scenario_id="scn-1",
        status=status,
        evidence=EvidenceCapture(
            url_before="https://chat.example.com",
            url_after="https://chat.example.com",
            deterministic_signals={"failed_step_index": failed_step_index},
            conversation_transcript=transcript or [],
        ),
        error_message=None if status == "success" else "boom",
    )


def test_is_chatbot_scenario_true_for_chatbot_actions():
    assert judging._is_chatbot_scenario(_chatbot_scenario())


def test_is_chatbot_scenario_false_for_web_app_actions():
    scenario = Scenario(
        scenario_id="scn-2",
        page_url="https://shop.example.com",
        title="t",
        description="d",
        steps=[ScenarioStep(action="click", target_selector="#go", value=None)],
        expect_failure=False,
        priority=1,
    )
    assert not judging._is_chatbot_scenario(scenario)


def test_format_transcript_truncates_long_conversations():
    transcript = [{"role": "assistant", "text": "x" * 10000}]
    formatted = judging._format_transcript(transcript)
    assert len(formatted) <= judging.TRANSCRIPT_CHAR_LIMIT + len("...(truncated)...\n")


async def test_judge_error_status_fails_without_llm_call(monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called on infra error")

    monkeypatch.setattr(OllamaClient, "health_check", _boom)
    result = await judging.judge_scenario(_chatbot_scenario(), _execution_result("error"))
    assert result["verdict"] == "fail"
    assert result["deterministic_veto"] is True


async def test_judge_failure_status_uses_assertion_wording():
    scenario = _chatbot_scenario()
    result = await judging.judge_scenario(
        scenario, _execution_result("failure", failed_step_index=2)
    )
    assert result["verdict"] == "fail"
    assert result["deterministic_veto"] is True
    assert "assertion did not hold" in result["reasoning"]


async def test_judge_chatbot_success_calls_semantic_llm_pass(monkeypatch):
    async def _health_check(self, model):
        return True

    async def _generate(self, model, prompt, **kwargs):
        assert "Assistant: Paris is the capital of France." in prompt
        return '{"verdict": "pass", "reasoning": "relevant and coherent", "confidence": 0.9}'

    monkeypatch.setattr(OllamaClient, "health_check", _health_check)
    monkeypatch.setattr(OllamaClient, "generate", _generate)

    transcript = [
        {"role": "user", "text": "What is the capital of France?"},
        {"role": "assistant", "text": "Paris is the capital of France."},
    ]
    result = await judging.judge_scenario(
        _chatbot_scenario(), _execution_result("success", transcript=transcript)
    )
    assert result["verdict"] == "pass"
    assert result["deterministic_veto"] is False
    assert result["reasoning"] == "relevant and coherent"
    assert result["confidence"] == 0.9


async def test_judge_chatbot_success_can_fail_on_bad_reply(monkeypatch):
    async def _health_check(self, model):
        return True

    async def _generate(self, model, prompt, **kwargs):
        return '{"verdict": "fail", "reasoning": "off-topic reply", "confidence": 0.7}'

    monkeypatch.setattr(OllamaClient, "health_check", _health_check)
    monkeypatch.setattr(OllamaClient, "generate", _generate)

    transcript = [
        {"role": "user", "text": "What is the capital of France?"},
        {"role": "assistant", "text": "I like pizza."},
    ]
    result = await judging.judge_scenario(
        _chatbot_scenario(), _execution_result("success", transcript=transcript)
    )
    assert result["verdict"] == "fail"
    assert result["deterministic_veto"] is False


async def test_judge_chatbot_degrades_when_llm_echoes_placeholder_text(monkeypatch):
    async def _health_check(self, model):
        return True

    async def _generate(self, model, prompt, **kwargs):
        return '{"verdict": "pass", "reasoning": "one short sentence", "confidence": 0.8}'

    monkeypatch.setattr(OllamaClient, "health_check", _health_check)
    monkeypatch.setattr(OllamaClient, "generate", _generate)

    transcript = [
        {"role": "user", "text": "What is the capital of France?"},
        {"role": "assistant", "text": "Paris is the capital of France."},
    ]
    result = await judging.judge_scenario(
        _chatbot_scenario(), _execution_result("success", transcript=transcript)
    )
    assert result["deterministic_veto"] is False
    assert result["confidence"] == 0.3
    assert "placeholder" in result["reasoning"]


async def test_judge_chatbot_degrades_when_llm_unavailable(monkeypatch):
    async def _health_check(self, model):
        return False

    monkeypatch.setattr(OllamaClient, "health_check", _health_check)

    result = await judging.judge_scenario(
        _chatbot_scenario(), _execution_result("success", transcript=[{"role": "user", "text": "hi"}])
    )
    assert result["verdict"] == "pass"
    assert result["deterministic_veto"] is False
    assert result["confidence"] == 0.3
    assert "unavailable" in result["reasoning"]


async def test_judge_web_app_scenario_still_uses_deterministic_assert_pass():
    scenario = Scenario(
        scenario_id="scn-3",
        page_url="https://shop.example.com",
        title="t",
        description="d",
        steps=[
            ScenarioStep(action="click", target_selector="#go", value=None),
            ScenarioStep(action="assert", target_selector="#result", value=None),
        ],
        expect_failure=False,
        priority=1,
    )
    execution_result = ExecutionResult(
        scenario_id="scn-3",
        status="success",
        evidence=EvidenceCapture(
            url_before="https://shop.example.com",
            url_after="https://shop.example.com",
            deterministic_signals={},
        ),
        error_message=None,
    )
    result = await judging.judge_scenario(scenario, execution_result)
    assert result["verdict"] == "pass"
    assert result["deterministic_veto"] is True
    assert result["reasoning"] == "all assertions in the scenario held"

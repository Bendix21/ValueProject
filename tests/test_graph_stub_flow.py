import copy

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.clients.agent_client import AgentUnavailableError
from app.graph.build import build_graph
from app.graph.nodes import discovery, executor, generator, judge, validator, vision
from app.graph.state import new_qa_state

NOW = "2026-01-01T00:00:00+00:00"


async def fake_discovery(url: str, payload: dict, **_kwargs) -> dict:
    return {
        "status": "vision",
        "pages": [
            {
                "target_url": payload["target_url"],
                "viewports": [],
                "dom_snapshot_path": None,
            }
        ],
        "updated_at": NOW,
    }


async def fake_vision(url: str, payload: dict, **_kwargs) -> dict:
    return {
        "status": "generating",
        "vision": {"page_summary": "stub", "vision_mode": "full", "enriched_elements": []},
        "updated_at": NOW,
    }


async def fake_generator(url: str, payload: dict, **_kwargs) -> dict:
    page_url = payload["target_url"]
    return {
        "status": "selecting",
        "scenarios": [
            {
                "scenario_id": "scn-1",
                "page_url": page_url,
                "title": "s1",
                "description": "d",
                "steps": [],
                "expect_failure": False,
                "priority": 1,
            },
            {
                "scenario_id": "scn-2",
                "page_url": page_url,
                "title": "s2",
                "description": "d",
                "steps": [],
                "expect_failure": False,
                "priority": 2,
            },
        ],
        "current_scenario_index": 0,
        "updated_at": NOW,
    }


VALIDATOR_TEMPLATE = {
    "status": "executing",
    "validation_result": {
        "scenario_id": None,
        "deterministic_checks_passed": True,
        "deterministic_errors": [],
        "llm_review_passed": True,
        "llm_review_notes": "ok",
        "approved": True,
    },
    "updated_at": NOW,
}


async def fake_validator(url: str, payload: dict, **_kwargs) -> dict:
    response = copy.deepcopy(VALIDATOR_TEMPLATE)
    response["validation_result"]["scenario_id"] = payload["scenario"]["scenario_id"]
    return response


EXECUTOR_TEMPLATE = {
    "status": "judging",
    "execution_result": {
        "scenario_id": None,
        "status": "success",
        "evidence": {
            "screenshots": [],
            "dom_diffs": [],
            "console_logs": [],
            "network_errors": [],
            "url_before": "https://example.com",
            "url_after": "https://example.com",
            "cookies_before": {},
            "cookies_after": {},
            "deterministic_signals": {},
        },
        "error_message": None,
    },
    "updated_at": NOW,
}


async def fake_executor(url: str, payload: dict, **_kwargs) -> dict:
    response = copy.deepcopy(EXECUTOR_TEMPLATE)
    response["execution_result"]["scenario_id"] = payload["scenario"]["scenario_id"]
    return response


JUDGE_TEMPLATE = {
    "status": "advancing",
    "judge_verdict": {
        "scenario_id": None,
        "verdict": "pass",
        "deterministic_veto": False,
        "reasoning": "ok",
        "confidence": 1.0,
    },
    "updated_at": NOW,
}


async def fake_judge(url: str, payload: dict, **_kwargs) -> dict:
    response = copy.deepcopy(JUDGE_TEMPLATE)
    response["judge_verdict"]["scenario_id"] = payload["scenario"]["scenario_id"]
    return response


@pytest.fixture(autouse=True)
def patch_agent_calls(monkeypatch):
    monkeypatch.setattr(discovery, "call_agent", fake_discovery)
    monkeypatch.setattr(vision, "call_agent", fake_vision)
    monkeypatch.setattr(generator, "call_agent", fake_generator)
    monkeypatch.setattr(validator, "call_agent", fake_validator)
    monkeypatch.setattr(executor, "call_agent", fake_executor)
    monkeypatch.setattr(judge, "call_agent", fake_judge)


@pytest.mark.asyncio
async def test_stub_pipeline_reaches_completed():
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(target_url="https://example.com", job_id="test-job")
    config = {"configurable": {"thread_id": "test-job"}}

    result = await graph.ainvoke(state, config)

    assert result["status"] == "completed"
    assert len(result["pages"]) == 1
    assert len(result["scenarios"]) == 2
    assert result["current_scenario_index"] == len(result["scenarios"])
    assert all(v["approved"] for v in result["validation_results"].values())
    assert all(r["status"] == "success" for r in result["execution_results"].values())
    assert all(j["verdict"] == "pass" for j in result["judge_verdicts"].values())
    assert result["final_report"]["passed"] == 2
    assert result["final_report"]["failed"] == 0
    assert result["final_report"]["pages_tested"] == 1


@pytest.mark.asyncio
async def test_state_resumable_via_checkpoint():
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(target_url="https://example.com", job_id="resume-job")
    config = {"configurable": {"thread_id": "resume-job"}}

    await graph.ainvoke(state, config)
    snapshot = await graph.aget_state(config)

    assert snapshot.values["status"] == "completed"
    assert snapshot.values["job_id"] == "resume-job"


async def fake_discovery_failing(url: str, payload: dict, **_kwargs) -> dict:
    raise AgentUnavailableError("simulated discovery outage")


@pytest.mark.asyncio
async def test_single_shot_agent_failure_short_circuits_to_failed(monkeypatch):
    monkeypatch.setattr(discovery, "call_agent", fake_discovery_failing)
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(target_url="https://example.com", job_id="discovery-fail-job")
    config = {"configurable": {"thread_id": "discovery-fail-job"}}

    result = await graph.ainvoke(state, config)

    assert result["status"] == "failed"
    assert result["pages"] == {}
    assert result["vision_results"] == {}
    assert result["scenarios"] == []
    assert "discovery" in result["failure_states"]
    assert result["failure_states"]["discovery"]["consecutive_failures"] == 1
    assert result["final_report"]["error"] is not None


async def fake_generator_three_scenarios(url: str, payload: dict, **_kwargs) -> dict:
    page_url = payload["target_url"]
    return {
        "status": "selecting",
        "scenarios": [
            {
                "scenario_id": f"scn-{i}",
                "page_url": page_url,
                "title": f"s{i}",
                "description": "d",
                "steps": [],
                "expect_failure": False,
                "priority": i,
            }
            for i in range(1, 4)
        ],
        "current_scenario_index": 0,
        "updated_at": NOW,
    }


async def fake_validator_failing(url: str, payload: dict, **_kwargs) -> dict:
    raise AgentUnavailableError("simulated validator outage")


@pytest.mark.asyncio
async def test_max_scenarios_is_forwarded_to_generator_agent(monkeypatch):
    captured_payload = {}

    async def capturing_generator(url: str, payload: dict, **_kwargs) -> dict:
        captured_payload.update(payload)
        return await fake_generator(url, payload)

    monkeypatch.setattr(generator, "call_agent", capturing_generator)
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(
        target_url="https://example.com", job_id="max-scenarios-job", max_scenarios=5
    )
    config = {"configurable": {"thread_id": "max-scenarios-job"}}

    await graph.ainvoke(state, config)

    assert captured_payload["max_scenarios"] == 5


@pytest.mark.asyncio
async def test_max_pages_is_forwarded_to_discovery_agent(monkeypatch):
    captured_payload = {}

    async def capturing_discovery(url: str, payload: dict, **_kwargs) -> dict:
        captured_payload.update(payload)
        return await fake_discovery(url, payload)

    monkeypatch.setattr(discovery, "call_agent", capturing_discovery)
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(target_url="https://example.com", job_id="max-pages-job", max_pages=7)
    config = {"configurable": {"thread_id": "max-pages-job"}}

    await graph.ainvoke(state, config)

    assert captured_payload["max_pages"] == 7


@pytest.mark.asyncio
async def test_scenarios_from_multiple_pages_are_aggregated(monkeypatch):
    async def fake_discovery_two_pages(url: str, payload: dict, **_kwargs) -> dict:
        return {
            "status": "vision",
            "pages": [
                {
                    "target_url": "https://example.com/",
                    "viewports": [],
                    "dom_snapshot_path": None,
                },
                {
                    "target_url": "https://example.com/about",
                    "viewports": [],
                    "dom_snapshot_path": None,
                },
            ],
            "updated_at": NOW,
        }

    async def fake_generator_unique_per_page(url: str, payload: dict, **_kwargs) -> dict:
        # scenario_id must be unique across pages even though pages are generated
        # concurrently and independently - mirrors the real generator-agent's use
        # of a random suffix (see agents/generator-agent generation.py) rather than
        # a per-call sequential counter, which would collide across parallel pages.
        page_url = payload["target_url"]
        suffix = page_url.rsplit("/", 1)[-1] or "home"
        return {
            "status": "selecting",
            "scenarios": [
                {
                    "scenario_id": f"scn-{suffix}-1",
                    "page_url": page_url,
                    "title": "s1",
                    "description": "d",
                    "steps": [],
                    "expect_failure": False,
                    "priority": 1,
                },
                {
                    "scenario_id": f"scn-{suffix}-2",
                    "page_url": page_url,
                    "title": "s2",
                    "description": "d",
                    "steps": [],
                    "expect_failure": False,
                    "priority": 2,
                },
            ],
            "current_scenario_index": 0,
            "updated_at": NOW,
        }

    monkeypatch.setattr(discovery, "call_agent", fake_discovery_two_pages)
    monkeypatch.setattr(generator, "call_agent", fake_generator_unique_per_page)
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(target_url="https://example.com/", job_id="multi-page-job")
    config = {"configurable": {"thread_id": "multi-page-job"}}

    result = await graph.ainvoke(state, config)

    assert result["status"] == "completed"
    assert len(result["pages"]) == 2
    # 2 scenarios per page x 2 pages, each with a unique scenario_id (no collisions)
    assert len(result["scenarios"]) == 4
    scenario_ids = {scenario["scenario_id"] for scenario in result["scenarios"]}
    assert len(scenario_ids) == 4
    page_urls = {scenario["page_url"] for scenario in result["scenarios"]}
    assert page_urls == {"https://example.com/", "https://example.com/about"}


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_consecutive_failures(monkeypatch):
    monkeypatch.setattr(generator, "call_agent", fake_generator_three_scenarios)
    monkeypatch.setattr(validator, "call_agent", fake_validator_failing)
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer)
    state = new_qa_state(target_url="https://example.com", job_id="breaker-job")
    config = {"configurable": {"thread_id": "breaker-job"}}

    result = await graph.ainvoke(state, config)

    assert result["status"] == "circuit_broken"
    assert result["circuit_breaker_tripped"] is True
    assert len(result["validation_results"]) == 3
    assert all(not v["approved"] for v in result["validation_results"].values())
    assert all(
        v["llm_review_notes"].startswith("validator agent unavailable")
        for v in result["validation_results"].values()
    )
    # all 3 scenarios still ran validator -> executor -> judge in parallel (fan-out),
    # since the batch-level breaker check only happens once, at the fan-in in advance
    assert len(result["execution_results"]) == 3
    assert len(result["judge_verdicts"]) == 3
    # regression: failure_states must count every concurrent branch's failure,
    # not just the last one merged in (see merge_failure_states in resilience.py)
    assert result["failure_states"]["validator"]["consecutive_failures"] == 3

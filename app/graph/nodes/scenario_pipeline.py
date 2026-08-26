from app.graph.nodes.executor import run_executor
from app.graph.nodes.judge import run_judge
from app.graph.nodes.validator import run_validator
from app.graph.state import QAState
from app.observability import traced_span


async def run_scenario_node(state: QAState) -> dict:
    scenario = state["selected_scenario"]
    scenario_id = scenario["scenario_id"]
    job_id = state["job_id"]
    page_url = scenario["page_url"]
    vision = state["vision_results"][page_url]
    failure_states = state["failure_states"]

    with traced_span(f"run_scenario:{scenario_id}", session_id=job_id):
        validation_result, failure_states = await run_validator(
            job_id, scenario, vision, failure_states
        )
        execution_result, failure_states = await run_executor(
            job_id, page_url, scenario, validation_result, failure_states
        )
        judge_verdict, failure_states = await run_judge(
            job_id, scenario, execution_result, failure_states
        )

    return {
        "validation_results": {scenario_id: validation_result},
        "execution_results": {scenario_id: execution_result},
        "judge_verdicts": {scenario_id: judge_verdict},
        "failure_states": failure_states,
    }

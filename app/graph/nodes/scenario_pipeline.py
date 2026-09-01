from app.graph.nodes.executor import run_executor
from app.graph.nodes.judge import run_judge
from app.graph.nodes.validator import run_validator
from app.graph.resilience import merge_failure_states
from app.graph.state import QAState
from app.observability import traced_span


async def run_scenario_node(state: QAState) -> dict:
    scenario = state["selected_scenario"]
    scenario_id = scenario["scenario_id"]
    job_id = state["job_id"]
    page_url = scenario["page_url"]
    vision = state["vision_results"][page_url]
    # Local accumulator for this branch's own failures only (validator,
    # executor, judge run sequentially within one scenario, so no race here).
    # It's returned as this branch's single contribution to the
    # failure_states channel, where LangGraph's own merge_failure_states
    # reducer folds it together with every other concurrent scenario
    # branch's contribution — see merge_failure_states' docstring.
    failure_states: dict = {}

    with traced_span(f"run_scenario:{scenario_id}", session_id=job_id):
        validation_result, delta = await run_validator(job_id, scenario, vision)
        failure_states = merge_failure_states(failure_states, delta)
        execution_result, delta = await run_executor(
            job_id, page_url, scenario, validation_result
        )
        failure_states = merge_failure_states(failure_states, delta)
        judge_verdict, delta = await run_judge(job_id, scenario, execution_result)
        failure_states = merge_failure_states(failure_states, delta)

    return {
        "validation_results": {scenario_id: validation_result},
        "execution_results": {scenario_id: execution_result},
        "judge_verdicts": {scenario_id: judge_verdict},
        "failure_states": failure_states,
    }

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import jobs_repo
from app.graph.state import new_qa_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

TERMINAL_STATUSES = {"completed", "failed", "circuit_broken", "cancelled"}


class CreateJobRequest(BaseModel):
    target_url: str
    max_scenarios: int | None = Field(default=None, ge=1, le=10)
    max_pages: int | None = Field(default=None, ge=1, le=20)


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("job pipeline failed with an unhandled exception", exc_info=exc)


def _screenshot_url(path: str | None) -> str | None:
    if not path:
        return None
    root = get_settings().screenshot_root.rstrip("/")
    if path.startswith(root):
        return "/screenshots" + path[len(root) :]
    return path


def _rewrite_execution_screenshots(execution_results: dict) -> dict:
    rewritten = {}
    for scenario_id, result in execution_results.items():
        result = dict(result)
        evidence = dict(result["evidence"])
        evidence["screenshots"] = [_screenshot_url(path) for path in evidence["screenshots"]]
        result["evidence"] = evidence
        rewritten[scenario_id] = result
    return rewritten


def _discovery_screenshots(pages: dict) -> list[dict]:
    return [
        {
            "page_url": page_url,
            "viewport_name": viewport["viewport_name"],
            "url": _screenshot_url(viewport["screenshot_path"]),
        }
        for page_url, discovery in pages.items()
        for viewport in discovery["viewports"]
    ]


@router.post("")
async def create_job(payload: CreateJobRequest, request: Request):
    state = new_qa_state(
        target_url=payload.target_url,
        max_scenarios=payload.max_scenarios,
        max_pages=payload.max_pages,
    )
    config = {
        "configurable": {"thread_id": state["job_id"]},
        "max_concurrency": get_settings().max_concurrency,
    }
    graph = request.app.state.graph
    task = asyncio.create_task(graph.ainvoke(state, config))
    request.app.state.running_tasks[state["job_id"]] = task

    def _cleanup(finished_task: asyncio.Task) -> None:
        request.app.state.running_tasks.pop(state["job_id"], None)
        _log_task_exception(finished_task)

    task.add_done_callback(_cleanup)

    await jobs_repo.insert_job(
        get_settings().db_url,
        state["job_id"],
        payload.target_url,
        payload.max_scenarios,
        payload.max_pages,
    )
    return {"job_id": state["job_id"], "status": "pending"}


@router.get("")
async def list_jobs(request: Request):
    jobs = await jobs_repo.list_jobs(get_settings().db_url)
    graph = request.app.state.graph

    async def _with_status(job: dict) -> dict:
        config = {"configurable": {"thread_id": job["job_id"]}}
        snapshot = await graph.aget_state(config)
        return {**job, "status": snapshot.values.get("status") if snapshot.values else "pending"}

    return await asyncio.gather(*[_with_status(job) for job in jobs])


@router.post("/{job_id}/resume")
async def resume_job(job_id: str, request: Request):
    graph = request.app.state.graph
    config = {
        "configurable": {"thread_id": job_id},
        "max_concurrency": get_settings().max_concurrency,
    }
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="job not found")

    status = snapshot.values.get("status")
    if status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"job already in terminal status '{status}'")

    task = asyncio.create_task(graph.ainvoke(None, config))
    request.app.state.running_tasks[job_id] = task

    def _cleanup(finished_task: asyncio.Task) -> None:
        request.app.state.running_tasks.pop(job_id, None)
        _log_task_exception(finished_task)

    task.add_done_callback(_cleanup)
    return {"job_id": job_id, "status": status, "resumed": True}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": job_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="job not found")

    status = snapshot.values.get("status")
    if status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"job already in terminal status '{status}'")

    task = request.app.state.running_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    await graph.aupdate_state(
        config, {"status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}
    )
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/{job_id}")
async def get_job(job_id: str, request: Request):
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": job_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="job not found")

    state = snapshot.values
    return {
        "job_id": job_id,
        "target_url": state.get("target_url"),
        "status": state.get("status"),
        "max_scenarios": state.get("max_scenarios"),
        "max_pages": state.get("max_pages"),
        "pages_tested": len(state.get("pages", {})),
        "current_scenario_index": state.get("current_scenario_index"),
        "scenario_count": len(state.get("scenarios", [])),
        "scenarios": state.get("scenarios", []),
        "discovery_screenshots": _discovery_screenshots(state.get("pages", {})),
        "validation_results": state.get("validation_results", {}),
        "execution_results": _rewrite_execution_screenshots(state.get("execution_results", {})),
        "judge_verdicts": state.get("judge_verdicts", {}),
        "failure_states": state.get("failure_states", {}),
        "circuit_breaker_tripped": state.get("circuit_breaker_tripped", False),
        "final_report": state.get("final_report"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
    }

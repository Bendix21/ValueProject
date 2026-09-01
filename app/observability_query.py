import logging
import uuid

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

LMNR_SQL_URL = "https://api.lmnr.ai/v1/sql/query"


async def _run_sql(client: httpx.AsyncClient, headers: dict, query: str) -> list[dict]:
    response = await client.post(LMNR_SQL_URL, headers=headers, json={"query": query})
    response.raise_for_status()
    return response.json()["data"]


async def fetch_trace_spans(job_id: str, client: httpx.AsyncClient) -> list[dict] | None:
    """Best-effort fetch of this job's spans from Laminar (session_id == job_id).

    Returns None when tracing isn't configured or the query fails for any
    reason (network, auth, schema drift on Laminar's side) — mirrors how the
    rest of the app treats Laminar as strictly optional (see
    app/observability.py). Every `traced_span()` call starts its own root
    span, so Laminar files each one under its own trace and only groups them
    by session_id at the trace level — spans themselves carry no session_id
    column, hence the two-query fetch (traces, then their spans) instead of a
    join, per Laminar's own SQL editor guidance that ClickHouse joins are
    slow and app-side combination is preferred.

    `client` must be a long-lived, shared AsyncClient (app.state.http_client)
    rather than one created per call — a fresh client pays a full DNS/TLS
    handshake before its first request, which was observed to occasionally
    exceed even a 20s timeout and silently degrade this to "no trace data".
    """
    settings = get_settings()
    if not settings.lmnr_project_api_key:
        return None
    try:
        uuid.UUID(job_id)
    except ValueError:
        return None

    headers = {"Authorization": f"Bearer {settings.lmnr_project_api_key}"}
    try:
        traces = await _run_sql(
            client,
            headers,
            f"SELECT id FROM traces WHERE session_id = '{job_id}' "
            "ORDER BY start_time ASC LIMIT 500",
        )
        trace_ids = [row["id"] for row in traces if _is_uuid(row.get("id"))]
        if not trace_ids:
            return []

        ids_list = ", ".join(f"'{trace_id}'" for trace_id in trace_ids)
        return await _run_sql(
            client,
            headers,
            "SELECT span_id, name, start_time, end_time, duration, status, "
            f"trace_id, parent_span_id FROM spans WHERE trace_id IN ({ids_list}) "
            "ORDER BY start_time ASC LIMIT 1000",
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        logger.warning("fetch_trace_spans failed for job %s: %r", job_id, exc)
        return None


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False

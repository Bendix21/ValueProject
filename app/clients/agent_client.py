import asyncio

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5

TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


class AgentUnavailableError(Exception):
    pass


async def call_agent(
    url: str,
    payload: dict,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        except TRANSIENT_EXCEPTIONS as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last_error = exc

        if attempt < retries:
            await asyncio.sleep(backoff_seconds * (2**attempt))

    raise AgentUnavailableError(
        f"{url} unreachable after {retries + 1} attempt(s): {last_error}"
    ) from last_error

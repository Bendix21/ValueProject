import httpx


class OllamaClient:
    def __init__(self, host: str, timeout: float = 60.0):
        self._host = host.rstrip("/")
        self._timeout = httpx.Timeout(timeout)

    async def health_check(self, model: str) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{self._host}/api/tags")
            except httpx.HTTPError:
                return False
        if response.status_code != 200:
            return False
        names = [entry.get("name", "") for entry in response.json().get("models", [])]
        return any(model in name for name in names)

    async def generate(
        self, model: str, prompt: str, images: list[str] | None = None, **kwargs
    ) -> str:
        payload = {"model": model, "prompt": prompt, "stream": False, **kwargs}
        if images:
            payload["images"] = images
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._host}/api/generate", json=payload)
            response.raise_for_status()
            return response.json()["response"]

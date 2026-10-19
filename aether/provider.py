from dataclasses import dataclass
import httpx


class ProviderNotConfigured(RuntimeError):
    pass


@dataclass
class ModelProvider:
    base_url: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float = 60.0

    async def chat(self, message: str) -> str:
        if not (self.base_url and self.api_key and self.model):
            raise ProviderNotConfigured(
                "Set AETHER_MODEL_BASE_URL, AETHER_MODEL_API_KEY, and AETHER_MODEL_NAME."
            )
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": [
                    {"role": "system", "content": "You are Project Aether, a helpful assistant. Never claim a tool was run unless execution results confirm it."},
                    {"role": "user", "content": message},
                ], "temperature": 0.2},
            )
            response.raise_for_status()
            data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not text")
            return content
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Provider returned an unexpected response") from exc

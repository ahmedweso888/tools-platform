from __future__ import annotations

import os
from dataclasses import dataclass


ALLOWED_MODELS = {
    "openai/gpt-5.6-luna": "gpt-5.6-luna",
    "openai/gpt-5.6-terra": "gpt-5.6-terra",
    "openai/gpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-luna": "gpt-5.6-luna",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-sol": "gpt-5.6-sol",
}

REASONING = {
    "gpt-5.6-luna": "none",
    "gpt-5.6-terra": "low",
    "gpt-5.6-sol": "high",
}


@dataclass(frozen=True)
class Settings:
    agent_secret: str
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    request_timeout_seconds: float = 75.0
    max_batch_size: int = 5
    max_output_tokens: int = 8192

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            agent_secret=os.getenv("WISO_AGENT_SECRET", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            request_timeout_seconds=float(os.getenv("WISO_AGENT_TIMEOUT_SECONDS", "75")),
            max_batch_size=int(os.getenv("WISO_AGENT_MAX_BATCH", "5")),
            max_output_tokens=int(os.getenv("WISO_AGENT_MAX_OUTPUT_TOKENS", "8192")),
        )

    def require_runtime_credentials(self) -> None:
        if not self.agent_secret:
            raise RuntimeError("WISO_AGENT_SECRET is not configured")
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

"""Configuration loaded from environment."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv():
    """Load .env file if it exists (minimal implementation, no dependency)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    gateway_url: str = os.getenv("AGENTCORE_GATEWAY_URL", "")
    region: str = os.getenv("AWS_REGION", "us-east-1")
    planner_mode: str = os.getenv("PLANNER_MODE", "sop_first")  # sop_first | authoritative
    planner_model_id: str = os.getenv(
        "PLANNER_MODEL_ID", "anthropic.claude-sonnet-5"
    )

    def validate(self) -> None:
        if self.planner_mode not in {"sop_first", "authoritative"}:
            raise ValueError(f"Invalid PLANNER_MODE: {self.planner_mode}")


settings = Settings()

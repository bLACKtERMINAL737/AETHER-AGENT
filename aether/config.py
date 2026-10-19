from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    workspace: Path
    model_base_url: str | None
    model_api_key: str | None
    model_name: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.getenv("AETHER_DB_PATH", "./data/aether.sqlite3")).expanduser(),
            workspace=Path(os.getenv("AETHER_WORKSPACE", "./workspace")).expanduser(),
            model_base_url=os.getenv("AETHER_MODEL_BASE_URL") or None,
            model_api_key=os.getenv("AETHER_MODEL_API_KEY") or None,
            model_name=os.getenv("AETHER_MODEL_NAME") or None,
        )

import os
from pathlib import Path
from typing import Any, Callable
from pydantic import BaseModel, Field, ValidationError


class ListFilesInput(BaseModel):
    path: str = Field(default=".", description="Relative path inside configured workspace")


class SearchTextInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    path: str = Field(default=".", description="Relative directory inside configured workspace")
    max_results: int = Field(default=50, ge=1, le=200)


class ToolError(Exception):
    pass


class ToolRegistry:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, tuple[type[BaseModel], Callable[..., Any], str]] = {
            "workspace.list_files": (ListFilesInput, self.list_files, "List files within the approved workspace."),
            "workspace.search_text": (SearchTextInput, self.search_text, "Search text files within the approved workspace."),
        }

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": n, "description": d, "input_schema": s.model_json_schema()}
                for n, (s, _, d) in self._tools.items()]

    def _safe_path(self, raw_path: str) -> Path:
        target = (self.workspace / raw_path).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ToolError("Path escapes the configured workspace") from exc
        return target

    def execute(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        schema, fn, _ = self._tools[name]
        try:
            args = schema.model_validate(payload)
        except ValidationError as exc:
            raise ToolError(f"Invalid tool input: {exc.errors(include_url=False)}") from exc
        return fn(**args.model_dump())

    def list_files(self, path: str = ".") -> dict[str, Any]:
        target = self._safe_path(path)
        if not target.exists():
            raise ToolError("Path does not exist")
        if not target.is_dir():
            raise ToolError("Path must be a directory")
        entries = [{"name": p.name, "type": "directory" if p.is_dir() else "file"}
                   for p in sorted(target.iterdir(), key=lambda p: p.name.casefold())]
        return {"path": str(target.relative_to(self.workspace)), "entries": entries[:500]}

    def search_text(self, query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
        target = self._safe_path(path)
        if not target.exists() or not target.is_dir():
            raise ToolError("Search path must be an existing directory")
        matches = []
        allowed = {".py", ".txt", ".md", ".json", ".toml", ".yaml", ".yml", ".js", ".ts", ".html", ".css", ".c", ".cpp", ".h"}
        for root, dirs, names in os.walk(target):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "node_modules", "__pycache__"} and not (Path(root) / d).is_symlink()]
            for name in names:
                file_path = Path(root) / name
                if file_path.suffix.lower() not in allowed:
                    continue
                try:
                    # Never read through symlinks: they can point outside the workspace.
                    if file_path.is_symlink():
                        continue
                    resolved_file = file_path.resolve()
                    resolved_file.relative_to(self.workspace)
                    if resolved_file.stat().st_size > 1_000_000:
                        continue
                    lines = resolved_file.read_text(encoding="utf-8", errors="replace").splitlines()
                except (OSError, ValueError):
                    continue
                for line_number, line in enumerate(lines, 1):
                    if query.casefold() in line.casefold():
                        matches.append({"file": str(file_path.relative_to(self.workspace)), "line": line_number, "text": line[:500]})
                        if len(matches) >= max_results:
                            return {"query": query, "matches": matches, "truncated": True}
        return {"query": query, "matches": matches, "truncated": False}

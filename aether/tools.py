import os
import stat
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

    def _read_workspace_file(self, file_path: Path) -> list[str] | None:
        """Read a workspace file without following symlinks in any path component."""
        try:
            relative = file_path.relative_to(self.workspace)
            if not relative.parts:
                return None
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
            file_flags = os.O_RDONLY | os.O_NOFOLLOW
            directory_fd = os.open(self.workspace, directory_flags)
            try:
                for part in relative.parts[:-1]:
                    next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = next_fd
                file_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fd)
            finally:
                os.close(directory_fd)

            try:
                file_stat = os.fstat(file_fd)
                if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > 1_000_000:
                    return None
                with os.fdopen(file_fd, "r", encoding="utf-8", errors="replace") as stream:
                    file_fd = -1
                    return stream.read().splitlines()
            finally:
                if file_fd >= 0:
                    os.close(file_fd)
        except (OSError, ValueError, NotImplementedError):
            return None

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
        for root, dirs, names in os.walk(target, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "node_modules", "__pycache__"} and not (Path(root) / d).is_symlink()]
            for name in names:
                file_path = Path(root) / name
                if file_path.suffix.lower() not in allowed:
                    continue
                lines = self._read_workspace_file(file_path)
                if lines is None:
                    continue
                for line_number, line in enumerate(lines, 1):
                    if query.casefold() in line.casefold():
                        matches.append({"file": str(file_path.relative_to(self.workspace)), "line": line_number, "text": line[:500]})
                        if len(matches) >= max_results:
                            return {"query": query, "matches": matches, "truncated": True}
        return {"query": query, "matches": matches, "truncated": False}

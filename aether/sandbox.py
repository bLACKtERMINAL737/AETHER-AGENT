import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class SandboxError(RuntimeError):
    pass


class DockerTestSandbox:
    """Run pytest in a disposable, network-isolated Docker container.

    The image must be built locally ahead of time. No image pulls occur at run time.
    This reduces exposure but is not a substitute for a patched host/container runtime.
    """
    EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "data"}

    def __init__(self, workspace: Path, image: str = "aether-sandbox:latest",
                 timeout_seconds: int = 60, memory_limit: str = "512m",
                 cpu_limit: str = "1", pids_limit: int = 128):
        self.workspace = workspace.resolve()
        self.image = image
        self.timeout_seconds = max(5, min(timeout_seconds, 120))
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.pids_limit = max(16, min(pids_limit, 256))

    def _snapshot(self, destination: Path) -> None:
        if not self.workspace.is_dir():
            raise SandboxError("Workspace directory does not exist")
        total_bytes = 0
        file_count = 0
        for root, dirs, files in os.walk(self.workspace, followlinks=False):
            root_path = Path(root)
            dirs[:] = [name for name in dirs
                       if name not in self.EXCLUDED_DIRS and not (root_path / name).is_symlink()]
            relative_root = root_path.relative_to(self.workspace)
            target_root = destination / relative_root
            target_root.mkdir(parents=True, exist_ok=True)
            for name in files:
                source = root_path / name
                if source.is_symlink():
                    raise SandboxError(f"Workspace contains a symlink; remove it before sandbox execution: {source.relative_to(self.workspace)}")
                if not source.is_file():
                    continue
                file_count += 1
                total_bytes += source.stat().st_size
                if file_count > 5000 or total_bytes > 50_000_000:
                    raise SandboxError("Workspace snapshot exceeds limits (5,000 files / 50 MB)")
                target = target_root / name
                shutil.copyfile(source, target)
                target.chmod(0o666)
            target_root.chmod(0o777)
        # Ensure nested directories are writable by the unprivileged container UID.
        for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.chmod(0o777)
            elif path.is_file():
                path.chmod(0o666)

    def run_pytest(self) -> dict[str, Any]:
        if not shutil.which("docker"):
            raise SandboxError("Docker CLI not found. Install Docker and build the local sandbox image first.")
        if not self.image or any(char.isspace() for char in self.image):
            raise SandboxError("Invalid sandbox image name")
        with tempfile.TemporaryDirectory(prefix="aether-sandbox-") as temp:
            snapshot = Path(temp) / "workspace"
            snapshot.mkdir(mode=0o777)
            self._snapshot(snapshot)
            command = [
                "docker", "run", "--rm", "--pull=never",
                "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit", str(self.pids_limit),
                "--memory", self.memory_limit, "--cpus", self.cpu_limit,
                "--user", "65534:65534",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "-v", f"{snapshot}:/workspace:rw",
                "-w", "/workspace", self.image,
                "python", "-m", "pytest", "-q",
            ]
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=self.timeout_seconds,
                    check=False, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                )
                return {
                    "command": command,
                    "returncode": result.returncode,
                    "passed": result.returncode == 0,
                    "stdout": result.stdout[-12000:],
                    "stderr": result.stderr[-12000:],
                    "timeout_seconds": self.timeout_seconds,
                    "sandboxed": True,
                    "network": "disabled",
                    "workspace_mode": "disposable-copy",
                }
            except subprocess.TimeoutExpired as exc:
                return {
                    "command": command, "returncode": None, "passed": False,
                    "stdout": str(exc.stdout or "")[-12000:],
                    "stderr": str(exc.stderr or "")[-12000:],
                    "timeout_seconds": self.timeout_seconds, "timed_out": True,
                    "sandboxed": True, "network": "disabled",
                    "workspace_mode": "disposable-copy",
                }
            except OSError as exc:
                raise SandboxError(f"Could not start Docker: {exc}") from exc

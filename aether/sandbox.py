import os
import re
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
    EXCLUDED_DIRS = {
        ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "data",
        ".ssh", ".aws", ".azure", ".gnupg",
    }
    EXCLUDED_FILES = {".env", ".env.local", ".env.production", ".env.development",
                      "id_rsa", "id_ed25519", "credentials", "credentials.json"}
    EXCLUDED_SUFFIXES = {
        ".pem", ".key", ".p12", ".pfx", ".p7b", ".p7c",
        ".p8", ".p10", ".p12", ".pfx", ".der", ".crt",
    }
    EXCLUDED_SECRET_NAMES = {
        ".netrc", ".npmrc", ".pypirc", ".dockercfg",
        "id_rsa", "id_ed25519", "known_hosts",
        "credentials", "credentials.json",
    }

    def __init__(self, workspace: Path, image: str = "aether-sandbox:latest",
                 timeout_seconds: int = 60, memory_limit: str = "512m",
                 cpu_limit: str = "1", pids_limit: int = 128):
        self.workspace = workspace.resolve()
        self.image = image
        self.timeout_seconds = max(5, min(timeout_seconds, 120))
        if not isinstance(memory_limit, str) or not re.fullmatch(r"[1-9][0-9]*[bBkKmMgG]?", memory_limit):
            raise SandboxError("Invalid sandbox memory limit")
        if (
            not isinstance(cpu_limit, str)
            or cpu_limit.count(".") > 1
            or not cpu_limit.replace(".", "", 1).isdigit()
            or float(cpu_limit) <= 0
        ):
            raise SandboxError("Invalid sandbox CPU limit")
        if isinstance(pids_limit, bool) or not isinstance(pids_limit, int):
            raise SandboxError("Invalid sandbox PID limit")
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.pids_limit = max(16, min(pids_limit, 256))

    def _snapshot(self, destination: Path) -> None:
        if not self.workspace.is_dir():
            raise SandboxError("Workspace directory does not exist")
        total_bytes = 0
        file_count = 0
        excluded_dirs = {name.casefold() for name in self.EXCLUDED_DIRS}
        for root, dirs, files in os.walk(self.workspace, followlinks=False):
            root_path = Path(root)
            for name in dirs:
                directory = root_path / name
                if name.casefold() not in excluded_dirs and directory.is_symlink():
                    relative = directory.relative_to(self.workspace)
                    raise SandboxError(
                        f"Workspace contains a symlink directory; remove it before sandbox execution: {relative}"
                    )
            dirs[:] = [name for name in dirs if name.casefold() not in excluded_dirs]
            relative_root = root_path.relative_to(self.workspace)
            target_root = destination / relative_root
            target_root.mkdir(parents=True, exist_ok=True)
            for name in files:
                source = root_path / name
                if source.is_symlink():
                    raise SandboxError(f"Workspace contains a symlink; remove it before sandbox execution: {source.relative_to(self.workspace)}")
                lower_name = name.lower()
                if (
                    name in self.EXCLUDED_FILES
                    or lower_name in self.EXCLUDED_SECRET_NAMES
                    or lower_name == ".env"
                    or lower_name.startswith(".env.")
                    or source.suffix.lower() in self.EXCLUDED_SUFFIXES
                    or "credential" in lower_name
                    or "secret" in lower_name
                ):
                    continue
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
        if (
            not isinstance(self.image, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}", self.image)
        ):
            raise SandboxError("Invalid sandbox image reference")
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

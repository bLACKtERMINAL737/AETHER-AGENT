from pathlib import Path
import subprocess

import pytest

from aether.sandbox import DockerTestSandbox, SandboxError


def test_snapshot_excludes_environment_and_secret_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('safe')\n", encoding="utf-8")
    (workspace / ".env").write_text("API_KEY=hidden\n", encoding="utf-8")
    (workspace / ".env.test").write_text("TOKEN=hidden\n", encoding="utf-8")
    (workspace / "client_secret.txt").write_text("hidden", encoding="utf-8")
    (workspace / "credentials.json").write_text('{"token":"hidden"}', encoding="utf-8")
    (workspace / "private.pem").write_text("private key", encoding="utf-8")

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    DockerTestSandbox(workspace)._snapshot(snapshot)

    assert (snapshot / "app.py").read_text(encoding="utf-8") == "print('safe')\n"
    assert not (snapshot / ".env").exists()
    assert not (snapshot / ".env.test").exists()
    assert not (snapshot / "client_secret.txt").exists()
    assert not (snapshot / "credentials.json").exists()
    assert not (snapshot / "private.pem").exists()


def test_snapshot_rejects_file_symlinks(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "target.py"
    target.write_text("print('safe')\n", encoding="utf-8")
    linked = workspace / "linked.py"
    try:
        linked.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable in this environment")

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with pytest.raises(SandboxError, match="symlink"):
        DockerTestSandbox(workspace)._snapshot(snapshot)


def test_snapshot_rejects_directory_symlinks(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_dir = workspace / "real"
    real_dir.mkdir()
    (real_dir / "test_example.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    linked = workspace / "linked"
    try:
        linked.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable in this environment")

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with pytest.raises(SandboxError, match="symlink directory"):
        DockerTestSandbox(workspace)._snapshot(snapshot)


def test_run_pytest_timeout_is_reported_as_failure(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    sandbox = DockerTestSandbox(workspace, timeout_seconds=5)
    monkeypatch.setattr("aether.sandbox.shutil.which", lambda _: "/usr/bin/docker")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="partial output")

    monkeypatch.setattr("aether.sandbox.subprocess.run", timeout)
    result = sandbox.run_pytest()

    assert result["passed"] is False
    assert result["returncode"] is None
    assert result["timed_out"] is True
    assert result["sandboxed"] is True
    assert result["network"] == "disabled"
    assert "partial output" in result["stdout"]


def test_run_pytest_wraps_docker_launch_oserror(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    sandbox = DockerTestSandbox(workspace)
    monkeypatch.setattr("aether.sandbox.shutil.which", lambda _: "/usr/bin/docker")

    def launch_error(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("aether.sandbox.subprocess.run", launch_error)
    with pytest.raises(SandboxError, match="Could not start Docker"):
        sandbox.run_pytest()


def test_run_pytest_requires_docker_cli(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerTestSandbox(workspace)
    monkeypatch.setattr("aether.sandbox.shutil.which", lambda _: None)

    with pytest.raises(SandboxError, match="Docker CLI not found"):
        sandbox.run_pytest()

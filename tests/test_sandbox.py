from pathlib import Path
import pytest

from aether.sandbox import DockerTestSandbox, SandboxError


def test_snapshot_copies_workspace_and_skips_excluded_dirs(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("print('hello')\n", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "secret").write_text("ignore me", encoding="utf-8")
    (workspace / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (workspace / "private.pem").write_text("private key", encoding="utf-8")
    destination = tmp_path / "snapshot"
    destination.mkdir()

    sandbox = DockerTestSandbox(workspace)
    sandbox._snapshot(destination)

    assert (destination / "sample.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert not (destination / ".git").exists()
    assert not (destination / ".env").exists()
    assert not (destination / "private.pem").exists()


def test_snapshot_rejects_symlinks(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (workspace / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    destination = tmp_path / "snapshot"
    destination.mkdir()

    with pytest.raises(SandboxError, match="symlink"):
        DockerTestSandbox(workspace)._snapshot(destination)


def test_test_runner_has_network_disabled_and_read_only_flags(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tests").mkdir()
    sandbox = DockerTestSandbox(workspace)
    captured = {}

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_which(name):
        return "/usr/bin/docker"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr("aether.sandbox.shutil.which", fake_which)
    monkeypatch.setattr("aether.sandbox.subprocess.run", fake_run)
    result = sandbox.run_pytest()

    assert result["passed"] is True
    assert "--network=none" in captured["command"]
    assert "--read-only" in captured["command"]
    assert "--cap-drop=ALL" in captured["command"]
    assert result["sandboxed"] is True


def test_snapshot_skips_common_secret_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".netrc").write_text("secret", encoding="utf-8")
    (workspace / "credentials.json").write_text('{"token":"secret"}', encoding="utf-8")
    (workspace / "service-secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "config.py").write_text("SAFE = True", encoding="utf-8")
    destination = tmp_path / "snapshot"
    destination.mkdir()

    DockerTestSandbox(workspace)._snapshot(destination)

    assert not (destination / ".netrc").exists()
    assert not (destination / "credentials.json").exists()
    assert not (destination / "service-secret.txt").exists()
    assert (destination / "config.py").exists()

"""The server warns at boot when core.hooksPath is not .githooks (owner order
2026-09-25, 1.3). Real throwaway git repositories, no mocks of git."""
import logging
import subprocess

from app import hooks_check, main


def _repo(path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    return path


def _hooks(path, value):
    subprocess.run(["git", "config", "core.hooksPath", value], cwd=path, check=True)


def test_unset_hooks_path_is_warned(tmp_path):
    """THE MUTATION TARGET (M534)."""
    message = hooks_check.hooks_path_warning(_repo(tmp_path))
    assert message is not None and "NOT SET" in message and "OFF" in message


def test_relative_githooks_is_fine(tmp_path):
    _hooks(_repo(tmp_path), ".githooks")
    assert hooks_check.hooks_path_warning(tmp_path) is None


def test_absolute_path_to_this_repos_githooks_is_fine(tmp_path):
    """The live checkout has it set this way (absolute)."""
    _hooks(_repo(tmp_path), str(tmp_path / ".githooks"))
    assert hooks_check.hooks_path_warning(tmp_path) is None


def test_a_different_hooks_folder_is_warned(tmp_path):
    _hooks(_repo(tmp_path), "other-hooks")
    message = hooks_check.hooks_path_warning(tmp_path)
    assert message is not None and "other-hooks" in message


def test_a_folder_that_is_not_a_git_checkout_is_silent(tmp_path):
    assert hooks_check.hooks_path_warning(tmp_path) is None


def test_boot_logs_the_warning(tmp_path, monkeypatch, caplog):
    """THE MUTATION TARGET (M535): the boot step itself logs it."""
    monkeypatch.setattr(hooks_check, "REPO_ROOT", _repo(tmp_path))
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        main._log_hooks_path()
    assert any("core.hooksPath" in r.getMessage() for r in caplog.records)


def test_real_app_startup_logs_the_warning(tmp_path, monkeypatch, caplog):
    """THE MUTATION TARGET (M536): the lifespan really runs the check."""
    from fastapi.testclient import TestClient

    from app import access, db
    from app.config import settings

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(hooks_check, "REPO_ROOT", _repo(repo))
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "boot.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    try:
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            with TestClient(main.app):
                pass
    finally:
        access.set_user_resolver(None)
        db.reset_connection()
    assert any("core.hooksPath is NOT SET" in r.getMessage() for r in caplog.records)


def test_boot_never_crashes_when_the_check_fails(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("git exploded")
    monkeypatch.setattr(hooks_check, "hooks_path_warning", boom)
    main._log_hooks_path()  # no raise

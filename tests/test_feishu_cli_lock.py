from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.feishu_cli_lock import credential_lock, lock_path
from app.services.feishu_service import FeishuError


@pytest.fixture
def paths(tmp_path, monkeypatch):
    shared, private = tmp_path / "shared", tmp_path / "private"
    monkeypatch.setenv("LARKSUITE_CLI_CONFIG_DIR", str(shared))
    return shared, private, {"app_id": "cli_synthetic", "open_id": "ou_synthetic"}


def test_uses_exact_official_refresh_name_and_never_secrets(paths):
    shared, _, identity = paths
    assert lock_path(identity) == shared / "locks/refresh_cli_synthetic_ou_synthetic.lock"
    with pytest.raises(FeishuError):
        lock_path({"app_id": "../other", "open_id": "ou_synthetic"})


def test_default_cli_lock_contends_across_independent_handles_then_releases(paths):
    _, private, identity = paths

    def another_handle():
        with pytest.raises(FeishuError) as caught:
            with credential_lock(identity, private, timeout=0):
                raise AssertionError("Must not enter another credential-bearing process")
        return caught.value.code

    with credential_lock(identity, private):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(another_handle).result(timeout=2) == "credential_busy"
    with credential_lock(identity, private, timeout=0):
        assert lock_path(identity).exists()


def test_same_inner_and_outer_path_fails_before_self_deadlock(paths):
    shared, _, identity = paths
    with pytest.raises(FeishuError):
        with credential_lock(identity, shared):
            raise AssertionError("Self-lock must be rejected")

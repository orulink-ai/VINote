"""Byte-preserving Nginx patch and rollback tests, no host/service operations."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/content/enable-upload-route.py"
spec = importlib.util.spec_from_file_location("content_upload_patch", SCRIPT)
patch = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = patch
spec.loader.exec_module(patch)

PREFIX = b''' location ^~ /vinote-api/ {
  client_max_body_size 6m;
  limit_req zone=vinote_workspace burst=60 nodelay;
  set $workspace_api vinote-workspace-api:8900;
  rewrite ^/vinote-api/(.*)$ /$1 break;
  proxy_pass http://$workspace_api;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header Authorization $http_authorization;
  proxy_set_header X-Forwarded-Proto https;
  proxy_read_timeout 190s;
  proxy_buffering off;
 }
'''
ORIGINAL = b'''# Unicode comments are retained byte-for-byte: \xe4\xb8\xad\xe6\x96\x87
server {
 client_max_body_size 50m;
 location /auth/ { proxy_pass http://auth; }
''' + PREFIX + b''' location / { proxy_pass http://web; }
}
'''


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = (tmp_path / "host.conf").resolve()
    path.write_bytes(ORIGINAL)
    binary = (tmp_path / "nginx").resolve()
    binary.write_bytes(b"offline fake binary; never executed")
    monkeypatch.setattr(patch, "config_lock", lambda _: nullcontext())
    return path, binary


class Nginx:
    def __init__(self, path, failure=None):
        self.path, self.failure, self.failed = path, failure, False
        self.calls = []

    def __call__(self, argv):
        args = argv[1:]
        self.calls.append((args, self.path.read_bytes()))
        if self.failure == args and not self.failed:
            self.failed = True
            raise patch.PatchError("offline command rejection")
        if args == ["-T"]:
            return b"# configuration file /main.conf:\nhttp {}\n# configuration file " + str(self.path).encode() + b":\n" + self.path.read_bytes() + b"\n"
        assert args in (["-t"], ["-s", "reload"])
        return b""


@pytest.mark.parametrize("crlf", [False, True])
def test_clone_changes_only_exact_route_and_preserves_prefix_other_routes_and_bytes(crlf):
    original = ORIGINAL.replace(b"\n", b"\r\n") if crlf else ORIGINAL
    candidate, report = patch.plan_config(original)
    assert report["action"] == "add_exact"
    assert report["original_sha256"] == patch.sha(original)
    nodes = list(patch.flatten(patch.parse(candidate)))
    target = next(n for n in nodes if n.values == [b"location", b"=", patch.UPLOAD])
    start = patch.block_start(candidate, target)
    end = target.end + (2 if crlf else 1)
    assert candidate[:start] + candidate[end:] == original
    assert PREFIX.replace(b"\n", b"\r\n") in candidate if crlf else PREFIX in candidate
    assert patch.effective_size(target) == 129 * 1024 * 1024
    assert patch.one(target, b"proxy_request_buffering").values == [b"proxy_request_buffering", b"off"]
    assert patch.signature(target) == patch.signature(next(n for n in nodes if n.values == [b"location", b"^~", patch.PREFIX]))
    assert patch.plan_config(candidate)[0] == candidate
    assert patch.plan_config(candidate)[1]["action"] == "noop"


def test_quoted_and_comment_braces_not_locations():
    source = ORIGINAL.replace(b"server {", b'''# location ^~ /vinote-api/ { broken comment }
server {
 set $brace "}";
 set $quoted "location ^~ /vinote-api/ {";
 set $variable ${request_uri};''')
    assert patch.plan_config(source)[1]["action"] == "add_exact"


@pytest.mark.parametrize("limit", [b"129m", b"256M", b"1g", b"135266304", b"0"])
def test_sufficient_or_unlimited_current_prefix_is_noop(limit):
    source = ORIGINAL.replace(b"client_max_body_size 6m", b"client_max_body_size " + limit)
    candidate, report = patch.plan_config(source)
    assert candidate == source and report["action"] == "noop"


def test_existing_exact_low_limit_upgraded_without_touching_prefix():
    source = patch.plan_config(ORIGINAL)[0].replace(b"129m", b"64m").replace(b"proxy_request_buffering off", b"proxy_request_buffering on")
    candidate, report = patch.plan_config(source)
    assert report["action"] == "update_exact"
    assert b"client_max_body_size 129m" in candidate
    assert b"proxy_request_buffering on" not in candidate
    assert PREFIX in candidate


@pytest.mark.parametrize("source", [
    ORIGINAL.replace(b"client_max_body_size 6m", b"client_max_body_size $limit"),
    ORIGINAL.replace(b"client_max_body_size 6m;", b"client_max_body_size 6m; client_max_body_size 8m;"),
    ORIGINAL + PREFIX,
    ORIGINAL.replace(b"rewrite ^/vinote-api/(.*)$ /$1 break;", b"rewrite ^/wrong/(.*)$ /$1 break;"),
    ORIGINAL.replace(b"proxy_pass http://$workspace_api;", b"proxy_pass http://$workspace_api/api/;"),
    ORIGINAL.replace(b"proxy_set_header Authorization $http_authorization;", b"proxy_set_header Authorization fixed-token;"),
    ORIGINAL.replace(b"proxy_buffering off;", b"if ($request_method) { return 403; }"),
    ORIGINAL[:-2],
    ORIGINAL.replace(b"proxy_buffering off;", b"set $bad \"unterminated;"),
])
def test_ambiguous_or_unsupported_boundary_fails_closed(source):
    with pytest.raises(patch.PatchError):
        patch.plan_config(source)


def test_inherited_server_limit_supported_but_external_inheritance_refused():
    source = ORIGINAL.replace(b"  client_max_body_size 6m;\n", b"")
    assert patch.plan_config(source)[1]["effective_body_limit_bytes"] == 50 * 1024 * 1024
    with pytest.raises(patch.PatchError, match="inheritance"):
        patch.plan_config(source.replace(b" client_max_body_size 50m;\n", b""))


def test_existing_exact_different_forwarding_or_server_refused():
    source = patch.plan_config(ORIGINAL)[0]
    exact_only = source[:source.index(PREFIX)]
    changed = exact_only.replace(b"proxy_pass http://$workspace_api", b"proxy_pass http://different") + source[source.index(PREFIX):]
    with pytest.raises(patch.PatchError, match="differs"):
        patch.plan_config(changed)


def test_execute_backup_is_original_bytes_sha_and_repeated_run_is_noop(config):
    path, binary = config
    nginx = Nginx(path)
    report = patch.apply(path, binary, patch.sha(ORIGINAL), nginx)
    assert report["executed"] and report["runtime_verified"]
    assert Path(report["backup"]).read_bytes() == ORIGINAL
    assert report["backup_sha256"] == patch.sha(ORIGINAL)
    assert nginx.calls[-1][0] == ["-s", "reload"]
    current = path.read_bytes()
    before = len(nginx.calls)
    assert patch.apply(path, binary, patch.sha(current), nginx)["action"] == "noop"
    assert len(nginx.calls) == before
    assert len(list(path.parent.glob("*.bak"))) == 1


@pytest.mark.parametrize("failure", [["-t"], ["-s", "reload"]])
def test_test_or_reload_failure_restores_original_and_reloads_original(config, failure):
    path, binary = config
    nginx = Nginx(path, failure)
    with pytest.raises(patch.ApplyError) as result:
        patch.apply(path, binary, patch.sha(ORIGINAL), nginx)
    assert path.read_bytes() == ORIGINAL
    assert result.value.receipt["rolled_back"] is True
    assert result.value.receipt["bytes_restored"] is True
    assert Path(result.value.receipt["backup"]).read_bytes() == ORIGINAL
    assert nginx.calls[-1] == (["-s", "reload"], ORIGINAL)


def test_mismatched_sha_or_unloaded_file_never_writes(config):
    path, binary = config
    nginx = Nginx(path)
    with pytest.raises(patch.PatchError, match="SHA256"):
        patch.apply(path, binary, "0" * 64, nginx)
    assert not nginx.calls and path.read_bytes() == ORIGINAL
    with pytest.raises(patch.PatchError, match="loaded"):
        patch.apply(path, binary, patch.sha(ORIGINAL), lambda argv: b"# another config only")
    assert not list(path.parent.glob("*.bak"))


def test_concurrent_edit_during_test_is_not_overwritten(config):
    path, binary = config
    nginx = Nginx(path)
    external = ORIGINAL + b"# external concurrent edit\n"
    def run(argv):
        if argv[1:] == ["-t"]:
            path.write_bytes(external)
        return nginx(argv)
    with pytest.raises(patch.ApplyError) as result:
        patch.apply(path, binary, patch.sha(ORIGINAL), run)
    assert path.read_bytes() == external
    assert result.value.receipt["rolled_back"] is False
    assert result.value.receipt["rollback_requires_attention"] is True


def test_failed_rollback_reload_reports_manual_attention_but_restores_bytes(config):
    path, binary = config
    nginx = Nginx(path)
    def run(argv):
        if argv[1:] == ["-s", "reload"]:
            raise patch.PatchError("all reloads fail")
        return nginx(argv)
    with pytest.raises(patch.ApplyError) as result:
        patch.apply(path, binary, patch.sha(ORIGINAL), run)
    assert path.read_bytes() == ORIGINAL
    assert result.value.receipt["bytes_restored"] is True
    assert result.value.receipt["rolled_back"] is False
    assert result.value.receipt["rollback_requires_attention"] is True


def test_cli_default_dryrun_has_no_commands_writes_or_backups(config, monkeypatch, capsys):
    path, binary = config
    monkeypatch.setattr(patch, "command", lambda *_: pytest.fail("dryrun must not invoke nginx"))
    assert patch.main(["--config", str(path), "--nginx-bin", str(binary)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["executed"] is False and report["runtime_verified"] is False
    assert path.read_bytes() == ORIGINAL and not list(path.parent.glob("*.bak"))
    assert patch.main(["--config", str(path), "--nginx-bin", str(binary), "--execute"]) == 1
    assert path.read_bytes() == ORIGINAL


def test_existing_nonexact_upload_restriction_is_not_overridden():
    source = ORIGINAL.replace(b" location / {", b" location /vinote-api/api/generate_from_upload { deny all; }\n location / {")
    with pytest.raises(patch.PatchError, match="non-exact"):
        patch.plan_config(source)


def test_io_failure_after_atomic_replace_still_restores_original(config, monkeypatch):
    path, binary = config
    write = patch.atomic_write
    failed = False
    def interrupted(*args):
        nonlocal failed
        write(*args)
        if not failed:
            failed = True
            raise OSError("simulated post-replace fsync failure")
    monkeypatch.setattr(patch, "atomic_write", interrupted)
    with pytest.raises(patch.ApplyError) as error:
        patch.apply(path, binary, patch.sha(ORIGINAL), Nginx(path))
    assert error.value.receipt["rolled_back"] is True
    assert path.read_bytes() == ORIGINAL

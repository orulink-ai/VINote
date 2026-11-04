from pathlib import Path
from types import SimpleNamespace

from app.services import feishu_cli


def test_qr_output_is_outside_protected_config(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(feishu_cli, "directory", lambda owner: config)
    monkeypatch.setattr(feishu_cli, "executable", lambda: "lark-cli")

    def run(*, args, cwd, **kwargs):
        output = Path(cwd) / args[args.index("--output") + 1]
        if output.is_relative_to(config):
            return SimpleNamespace(returncode=2)
        output.write_bytes(b"\x89PNG\r\n\x1a\nexample")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(feishu_cli.subprocess, "run", run)
    assert feishu_cli.qr("owner", "https://open.feishu.cn/test").startswith("data:image/png;base64,")

"""Direct backend startup must not restore the retired origin override."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('override', ['', 'http://192.168.1.143:9876',
                                      'https://api.orulink.ai', 'https://external.invalid'])
@pytest.mark.parametrize('source', ['environment', 'dotenv'])
def test_backend_uses_public_origin_despite_legacy_override(tmp_path, override, source):
    config = Path(__file__).resolve().parents[1] / 'app' / 'config.py'
    env = {key: value for key, value in os.environ.items() if key != 'VILAB_SERVER_URL'}
    env.update(VINOTE_WORKSPACE_CLOUD='false', VINOTE_CONTENT_CLOUD='false',
               DATA_DIR=str(tmp_path / 'data'), OUTPUT_DIR=str(tmp_path / 'output'))
    if source == 'environment':
        env['VILAB_SERVER_URL'] = override
    else:
        (tmp_path / '.env').write_text(f'VILAB_SERVER_URL={override}\n', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, '-c',
         'from dotenv import load_dotenv; load_dotenv(".env"); '
         'import runpy, sys; print(runpy.run_path(sys.argv[1])["settings"].vilab_server_url)',
         str(config)], cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == 'https://api-hk.orulink.ai'

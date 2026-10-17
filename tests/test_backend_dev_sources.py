import importlib.util
from pathlib import Path


def test_source_reloader_excludes_media_models_and_frontend_build_trees():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('vinote_backend_dev', root / 'scripts/backend-dev.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    watched = module.source_paths()
    assert root not in watched
    assert root / 'app' in watched
    assert root / 'main.py' in watched
    assert all(path.exists() for path in watched)
    for unrelated in ['data', 'output', 'frontend', 'VINote-app', '.venv']:
        assert all(path != root / unrelated and path not in (root / unrelated).parents for path in watched)

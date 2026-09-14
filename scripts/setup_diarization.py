"""Install VINote's local speaker models; no account or model API key needed."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def download(url: str, destination: Path) -> None:
    import httpx

    for attempt in range(3):
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=120, headers={"Accept": "application/octet-stream"}) as response:
                response.raise_for_status()
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        output.write(chunk)
            return
        except (httpx.HTTPError, OSError):
            if attempt == 2:
                raise
            time.sleep(2)


def setup(destination: Path, *, install_runtime: bool = True, cache: Path | None = None) -> None:
    if install_runtime:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.diarization.txt")], check=True)
    destination.mkdir(parents=True, exist_ok=True)
    if cache and cache.resolve() != destination.resolve():
        for name in ("segmentation.onnx", "embedding.onnx"):
            source = cache / name
            if source.is_file() and source.stat().st_size and not (destination / name).exists():
                shutil.copyfile(source, destination / name)
    base = "https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/assets"
    with tempfile.TemporaryDirectory(prefix="setup-", dir=destination) as folder:
        temp = Path(folder)
        if not (destination / "segmentation.onnx").is_file():
            archive = temp / "segmentation.tar.bz2"
            download(f"{base}/197666131", archive)
            with tarfile.open(archive) as bundle:
                member = bundle.getmember("sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
                if not member.isfile():
                    raise ValueError("Invalid model archive")
                with bundle.extractfile(member) as source, (temp / "segmentation.onnx").open("wb") as target:
                    shutil.copyfileobj(source, target)
            (temp / "segmentation.onnx").replace(destination / "segmentation.onnx")
        if not (destination / "embedding.onnx").is_file():
            download(f"{base}/198893098", temp / "embedding.onnx")
            (temp / "embedding.onnx").replace(destination / "embedding.onnx")
    print(f"Speaker models ready: {destination}")


if __name__ == "__main__":
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=settings.diarization_model_dir)
    parser.add_argument("--models-only", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check installed runtime and model files without downloading")
    args = parser.parse_args()
    if args.check:
        import sherpa_onnx
        import numpy

        for name in ("segmentation.onnx", "embedding.onnx"):
            path = args.models_dir / name
            if not path.is_file() or path.stat().st_size == 0:
                raise SystemExit(1)
    else:
        setup(args.models_dir, install_runtime=not args.models_only, cache=settings.diarization_model_dir)

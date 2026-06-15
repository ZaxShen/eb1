"""Deterministic E2E fixture builder for the annotation app.

Builds a fresh, self-contained ``datasets/`` tree the Playwright harness points
the backend at via ``EB1_DATASETS_DIR``. Everything here is offline and stable:

- a tiny committed JSONL sample per dataset (``samples/<ds>.jsonl``);
- the dataset's metadata DB via ``pipeline.metadata.seed_<ds>`` (config + taxonomy);
- machine segments via ``pipeline.run_dataset.run(..., analyzer="mock")`` — the
  mock analyzer emits one deterministic segment per user-engaged chunk, so no
  network or LLM is touched and the segment counts are reproducible.

Result per dataset ``<ds>``::

    <fixture>/<ds>/sample.jsonl     (copied committed sample)
    <fixture>/<ds>/metadata.db      (seed_<ds>)
    <fixture>/<ds>/output.db        (run_dataset --analyzer mock)
    <fixture>/<ds>/gold.db          (created lazily by the backend on first write)

Run standalone::

    uv run python annotation/frontend/e2e/fixtures/seed_e2e.py --out /tmp/e2e-datasets
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Allow ``python <path>/seed_e2e.py`` (script dir, not cwd, is sys.path[0]) to
# import the repo's ``pipeline`` package regardless of the launch directory.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.metadata.seed_superdialseg import seed as seed_superdialseg  # noqa: E402
from pipeline.metadata.seed_wildchat import seed as seed_wildchat  # noqa: E402
from pipeline.run_dataset import run  # noqa: E402

SAMPLES_DIR = Path(__file__).parent / "samples"

DATASETS: dict[str, object] = {
    "wildchat": seed_wildchat,
    "superdialseg": seed_superdialseg,
}


def build_dataset(name: str, seed_fn, out_root: Path) -> dict:
    """Build one fixture dataset under ``<out_root>/<name>`` and return its summary."""
    ds_dir = out_root / name
    ds_dir.mkdir(parents=True, exist_ok=True)

    sample = ds_dir / "sample.jsonl"
    shutil.copyfile(SAMPLES_DIR / f"{name}.jsonl", sample)

    metadata_db = ds_dir / "metadata.db"
    seed_fn(metadata_db)

    return run(
        dataset=name,
        sample=sample,
        analyzer="mock",
        metadata_db=metadata_db,
        output_db=ds_dir / "output.db",
    )


def build(out_root: str | Path) -> Path:
    """Build the full E2E fixture tree fresh under ``out_root`` and return it."""
    root = Path(out_root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    for name, seed_fn in DATASETS.items():
        summary = build_dataset(name, seed_fn, root)
        print(
            f"[seed_e2e] {name}: "
            f"{summary['conversations']} conversations, "
            f"{summary['segments']} segments"
        )
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the E2E fixture datasets tree.")
    parser.add_argument(
        "--out",
        required=True,
        help="Output datasets root (rebuilt fresh each run).",
    )
    args = parser.parse_args()
    root = build(args.out)
    print(f"[seed_e2e] fixture datasets ready at {root}")


if __name__ == "__main__":
    main()

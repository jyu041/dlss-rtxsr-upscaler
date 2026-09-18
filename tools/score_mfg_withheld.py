"""Score generated MFG frames against withheld real-frame references.

Input is an explicit JSON manifest so capture/generation and scoring remain
separate.  This tool performs no GPU work and does not start a DLSS-G worker.

Manifest schema:
{
  "multiplier": 4,
  "samples": [
    {
      "group": 0,
      "generated_index": 1,
      "reference": "references/g000_i1.png",
      "generated": "generated/g000_i1.png"
    }
  ]
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.mfg_quality import frame_metrics, summarize_samples  # noqa: E402


def _load_image(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to score image manifests") from exc
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def score_manifest(manifest_path: Path) -> dict[str, object]:
    path = manifest_path.expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    multiplier = int(data["multiplier"])
    if multiplier not in (2, 3, 4):
        raise ValueError("manifest multiplier must be 2, 3, or 4")
    raw_samples = data.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise ValueError("manifest samples must be a non-empty list")

    rows = []
    for ordinal, sample in enumerate(raw_samples):
        if not isinstance(sample, dict):
            raise ValueError(f"sample {ordinal} must be an object")
        index = int(sample["generated_index"])
        if not 1 <= index < multiplier:
            raise ValueError(
                f"sample {ordinal} generated_index={index} is invalid for {multiplier}X"
            )
        reference_path = (path.parent / str(sample["reference"])).resolve()
        generated_path = (path.parent / str(sample["generated"])).resolve()
        reference = _load_image(reference_path)
        generated = _load_image(generated_path)
        metrics = frame_metrics(reference, generated)
        rows.append(
            {
                "group": int(sample.get("group", ordinal)),
                "generated_index": index,
                "reference": str(reference_path),
                "generated": str(generated_path),
                "width": int(reference.shape[1]),
                "height": int(reference.shape[0]),
                **metrics,
            }
        )

    return {
        "schema_version": 2,
        "metric_contract": {
            "rgb_only": True,
            "psnr_identical_is_null": True,
            "ssim": "global per-channel RGB SSIM averaged across channels",
            "edge_mae": "RGB MAE over reference-only Rec.709 luma edges with >=20-code one-pixel gradient",
        },
        "multiplier": multiplier,
        "samples": rows,
        "summary": summarize_samples(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = score_manifest(args.manifest)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

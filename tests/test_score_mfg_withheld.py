import json

import numpy as np
from PIL import Image

from tools.score_mfg_withheld import score_manifest


def _png(path, value):
    frame = np.zeros((4, 4, 4), dtype=np.uint8)
    frame[..., :3] = value
    frame[..., 3] = 255
    Image.fromarray(frame, mode="RGBA").save(path)


def test_score_manifest_reads_relative_pngs_and_groups_indices(tmp_path):
    references = tmp_path / "references"
    generated = tmp_path / "generated"
    references.mkdir()
    generated.mkdir()

    _png(references / "g0_i1.png", 10)
    _png(generated / "g0_i1.png", 10)
    _png(references / "g0_i2.png", 20)
    _png(generated / "g0_i2.png", 18)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "multiplier": 3,
                "samples": [
                    {
                        "group": 0,
                        "generated_index": 1,
                        "reference": "references/g0_i1.png",
                        "generated": "generated/g0_i1.png",
                    },
                    {
                        "group": 0,
                        "generated_index": 2,
                        "reference": "references/g0_i2.png",
                        "generated": "generated/g0_i2.png",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = score_manifest(manifest)
    assert report["multiplier"] == 3
    assert report["summary"]["count"] == 2
    assert report["samples"][0]["identical"] is True
    assert report["samples"][1]["identical"] is False
    assert report["summary"]["by_generated_index"]["1"]["count"] == 1
    assert report["summary"]["by_generated_index"]["2"]["count"] == 1
    assert report["metric_contract"]["rgb_only"] is True

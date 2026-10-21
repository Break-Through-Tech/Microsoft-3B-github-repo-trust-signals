"""Add inspected charts, report and replay verification to a new review ZIP."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from validate_temporal_bundle import validate


def main(folder, replay):
    root = Path(__file__).parents[0]
    shutil.copy2(root / "validate_temporal_bundle.py", folder / "validate_temporal_bundle.py")
    shutil.copy2(root / "TEMPORAL_INTEGRATION_HANDOFF.md", folder / "INTEGRATION_HANDOFF.md")
    names = [
        "temporal_features_long.csv",
        "temporal_features_staging.csv",
        "base166_merge_preview.csv",
        "identity_registry.csv",
        "feature_dictionary.csv",
    ]
    checks = []
    for name in names:
        a = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        b = hashlib.sha256((replay / name).read_bytes()).hexdigest()
        if a != b:
            raise ValueError("Replay differs: " + name)
        checks.append({"file": name, "sha256": a, "offline_replay_matches": True})
    (folder / "offline_replay_verification.json").write_text(json.dumps(checks, indent=2))
    items = [
        {
            "path": str(p.relative_to(folder)).replace("\\", "/"),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in folder.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    ]
    (folder / "manifest.json").write_text(json.dumps(items, indent=2))
    validate(folder)
    archive = folder.with_name(folder.name + "_review.zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path in folder.rglob("*"):
            if path.is_file():
                z.write(path, str(path.relative_to(folder)))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP integrity error")
    print("Validated review ZIP:", archive, "bytes:", archive.stat().st_size)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--replay", type=Path, required=True)
    a = p.parse_args()
    main(a.bundle, a.replay)

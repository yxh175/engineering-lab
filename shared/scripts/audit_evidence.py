"""Verify sealed artifacts and source linkage. A hash is not proof of execution."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(manifest_path):
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_dir = manifest_path.parent
    lab = run_dir.parent.parent
    errors = []
    for name, expected in manifest["artifact_sha256"].items():
        path = (run_dir / name).resolve()
        if not path.is_relative_to(run_dir) or not path.is_file() or sha(path) != expected:
            errors.append(f"artifact mismatch: {name}")
    for name, expected in manifest["source_sha256"].items():
        path = (lab / name).resolve()
        if not path.is_relative_to(lab) or not path.is_file() or sha(path) != expected:
            errors.append(f"source mismatch: {name}")
    project = lab.parents[1]
    for name, expected in manifest.get("shared_source_sha256", {}).items():
        path = (project / name).resolve()
        if not path.is_relative_to(project) or not path.is_file() or sha(path) != expected:
            errors.append(f"shared source mismatch: {name}")
    if not manifest["all_passed"]:
        errors.append("run was not all_passed")
    print(f"{manifest_path.name} ({run_dir.name}): {len(manifest['artifact_sha256'])} artifacts, {len(manifest['source_sha256'])} sources, {'PASS' if not errors else 'FAIL'}")
    for error in errors:
        print(error)
    return not errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="+", type=Path)
    args = parser.parse_args()
    outcomes = [audit(p) for p in args.manifests]
    raise SystemExit(0 if all(outcomes) else 1)

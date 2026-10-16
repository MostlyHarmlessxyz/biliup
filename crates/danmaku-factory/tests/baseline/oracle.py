#!/usr/bin/env python3
"""Rebuild the frozen C oracle without modifying the working tree or golden files.

capture is only for the initial Gate 0 freeze. check/prepare are repeatable and
remain usable after the production converter changes. All source comes from
the recorded local Git object, never from the new Rust implementation.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MANIFEST = HERE / "source.json"
PREFIXES = (
    "crates/danmaku-factory-sys/",
    "crates/danmaku-factory/",
    "crates/biliup-cli/src/danmaku_worker.rs",
    "crates/biliup-cli/src/server/workbench/renders/danmaku",
    "crates/biliup-cli/tests/danmaku_worker.rs",
)
EXACT = ("Cargo.toml", "Cargo.lock", ".github/workflows/test.yml")


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def capture():
    if MANIFEST.exists():
        raise SystemExit("baseline already frozen; refusing to overwrite")
    revision = git("rev-parse", "HEAD").decode().strip()
    paths = git("ls-tree", "-r", "--name-only", revision).decode().splitlines()
    paths = [p for p in paths if p in EXACT or p.startswith(PREFIXES)]
    files = {p: digest(git("show", f"{revision}:{p}")) for p in paths}
    tools = {}
    for name, args in {
        "rustc": ["rustc", "-Vv"],
        "cargo": ["cargo", "-V"],
        "cc": ["cc", "--version"],
        "clang": ["clang", "--version"],
        "locale": ["locale"],
        "locales": ["locale", "-a"],
    }.items():
        tools[name] = subprocess.check_output(args).decode().strip()
    value = {
        "schema": 1,
        "project_commit": revision,
        "danmaku_factory_commit": "3813e93b13b087e95901d1822baf9c3540e3f3f6",
        "pcre2_commit": "6f9d7c1373262c541324a16a358785b33ef116cf",
        "c_flags": ["-O2", "-std=gnu11", "-fsigned-char", "-ffp-contract=off", "-fvisibility=hidden"],
        "rust_profile": "release (workspace LTO, codegen-units=1)",
        "tools": tools,
        "sha256": files,
    }
    MANIFEST.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def check(manifest, source):
    for path, expected in manifest["sha256"].items():
        data = (source / path).read_bytes()
        if digest(data) != expected:
            raise SystemExit(f"frozen source mismatch: {path}")


def prepare(manifest, destination):
    source = destination / "source"
    destination.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        archive = git("archive", manifest["project_commit"])
        source.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter="data")
    check(manifest, source)
    build = destination / "build"
    subprocess.run(
        ["cargo", "build", "--locked", "--release", "-p", "danmaku-factory",
         "--example", "convert", "--target-dir", str(build)],
        cwd=source, check=True,
    )
    binary = build / "release" / "examples" / ("convert.exe" if os.name == "nt" else "convert")
    print(binary)


def golden(manifest, destination):
    binary = destination / "build/release/examples" / ("convert.exe" if os.name == "nt" else "convert")
    corpus = ROOT / "crates/danmaku-factory/tests/golden"
    for path, expected in manifest["sha256"].items():
        if path.startswith("crates/danmaku-factory/tests/golden/"):
            if digest((ROOT / path).read_bytes()) != expected:
                raise SystemExit(f"immutable legacy asset changed: {path}")
    report = []
    with tempfile.TemporaryDirectory(prefix="df-oracle-") as work:
        for case in json.loads((corpus / "cases.json").read_text()):
            output = Path(work) / f"{case['name']}.ass"
            proc = subprocess.run(
                [str(binary), str(corpus / "inputs" / case["input"]),
                 str(output), json.dumps(case["options"])],
                capture_output=True, check=True, timeout=120,
            )
            actual = output.read_bytes()
            if os.name == "nt":
                actual = actual.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
            expected = (corpus / "expected" / f"{case['name']}.ass").read_bytes()
            if actual != expected:
                at = next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b), min(len(actual), len(expected)))
                raise SystemExit(f"{case['name']}: first difference byte={at}, line={expected[:at].count(bytes([10])) + 1}")
            report.append({"case": case["name"], "sha256": digest(actual), "stats": proc.stdout.decode().strip()})
    result = {"project_commit": manifest["project_commit"], "cases": report}
    (destination / "golden-result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"C oracle: {len(report)} golden cases byte-identical")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "check", "prepare", "golden"])
    parser.add_argument("--destination", type=Path, default=ROOT / "target/danmaku-oracle")
    args = parser.parse_args()
    if args.action == "capture":
        capture()
        return
    manifest = json.loads(MANIFEST.read_text())
    if args.action == "prepare":
        prepare(manifest, args.destination.resolve())
    elif args.action == "golden":
        golden(manifest, args.destination.resolve())
    else:
        for path, expected in manifest["sha256"].items():
            if digest(git("show", f"{manifest['project_commit']}:{path}")) != expected:
                raise SystemExit(f"Git baseline mismatch: {path}")
        print(f"verified {len(manifest['sha256'])} frozen files")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare and run the Gate 5 same-machine C/Rust benchmark.

    python3 benchmark.py prepare
    # Run only when builds/tests/other conversion work have stopped:
    python3 benchmark.py smoke
    python3 benchmark.py run --warmups 2 --repeats 5

All generated files live under target/danmaku-oracle/benchmark by default.
This Linux/macOS harness does not modify production code or frozen assets.
It builds one release executable with two engines. Rust uses current production
path modules; C calls the frozen readXml/blockByType/normFontSize/sortList/
writeAss and retains its list until cleanup. Both engines use the same Rust
NamedTempFile/sync_all/persist_noclobber wrapper, and both exclude destruction
from core time. C's native writeAss still reopens and closes the temporary path;
that original I/O path is included in C core time, rather than rewritten.

Core means input open/read, parse, normalize/filter/sort, layout and serialize,
including checked buffered writes/flush, without fsync. End-to-end adds unique
temporary creation, sync_all and no-clobber publication. Cleanup memory/handles
and external output deletion are reported separately. Process startup, JSON
parsing/reporting and SHA256 verification are outside instrumented core/E2E.
Per-stage CPU user/system times come from getrusage; Linux peak RSS uses this
process image's /proc/self/status VmHWM and also records getrusage separately
because the latter can retain the launcher high-water floor. Other platforms
use getrusage. Neither is a hard budget or an incremental allocation.
The common executable includes both engines; no process is reused across runs.

Warmups are discarded; measured trials alternate C/native order. The script
does not drop OS caches or pin CPU frequency, and records those limits. IC-03
long text is explicitly unequal work: raw measurements are retained but no
speed/RSS ratio is emitted. Compatible cases require identical output SHA256
and statistics, repeated-run output determinism, and no cleanup residue.

The public convert examples have different sync guarantees and are therefore
recorded as provenance only, never used as the equal-sync timing comparison.
Preparation/build/smoke results do not constitute Gate 5 performance acceptance.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib

import oracle
import workloads

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DEFAULT_DESTINATION = ROOT / "target/danmaku-oracle/benchmark"
NATIVE = ROOT / "crates/danmaku-factory/src"
PHASES = (
    "temporary_setup", "core", "sync", "publish", "end_to_end",
    "cleanup_memory_and_handles", "cleanup_output",
)
METRICS = ("wall_ms", "cpu_user_ms", "cpu_system_ms")


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def source_hashes():
    paths = [NATIVE / name for name in ["api.rs", "lib.rs", "limits.rs"]]
    paths.extend(sorted((NATIVE / "native").glob("*.rs")))
    paths.extend(HERE / name for name in ["benchmark.py", "benchmark_native.rs", "benchmark_c.c"])
    paths.extend(ROOT / name for name in ["Cargo.toml", "Cargo.lock"])
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def command_output(command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return {"command": command, "exit_code": result.returncode,
            "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def frozen_paths(oracle_root, explicit_libraries):
    manifest = json.loads((HERE / "source.json").read_text())
    source = oracle_root / "source"
    oracle.check(manifest, source)
    libraries = explicit_libraries
    if libraries is None:
        matches = list((oracle_root / "build/release/build").glob("danmaku-factory-sys-*/out/libbiliup_df_core.a"))
        if len(matches) != 1:
            raise SystemExit("need one frozen release core archive; run oracle.py prepare or pass --c-libraries")
        libraries = matches[0].parent
    for name in ["libbiliup_df_core.a", "libbiliup_df_pcre2.a"]:
        if not (libraries / name).is_file():
            raise SystemExit(f"missing frozen C archive: {libraries / name}")
    return manifest, source, libraries.resolve()


def prepare(args):
    if sys.platform not in {"linux", "darwin"}:
        raise SystemExit("stage counters/build flags currently support Linux and macOS only")
    destination = args.destination
    destination.mkdir(parents=True, exist_ok=True)
    manifest, frozen, libraries = frozen_paths(args.oracle_root, args.c_libraries)
    workspace = destination / "driver"
    workspace.mkdir(exist_ok=True)
    croot = frozen / "crates/danmaku-factory-sys"
    flags = ["-O2", "-std=gnu11", "-fsigned-char", "-ffp-contract=off", "-fvisibility=hidden", "-fPIC"]
    compile_command = [args.cc, *flags, "-include", str(croot / "csrc/df_namespace.h"),
                       "-I", str(croot / "csrc"), "-I", str(croot / "vendor/DanmakuFactory/src"),
                       "-c", str(HERE / "benchmark_c.c"), "-o", str(workspace / "benchmark_c.o")]
    commands = [compile_command,
                [args.ar, "rcs", str(workspace / "libbiliup_benchmark_bridge.a"), str(workspace / "benchmark_c.o")]]
    root_lock = tomllib.loads((ROOT / "Cargo.lock").read_text())
    versions = {}
    for name, prefix in [("serde", "1."), ("serde_json", "1."), ("quick-xml", "0.37."), ("tempfile", "3.")]:
        found = [package["version"] for package in root_lock["package"] if package["name"] == name and package["version"].startswith(prefix)]
        if len(found) != 1:
            raise SystemExit(f"cannot choose exact workspace version for {name}: {found}")
        versions[name] = found[0]
    dependencies = "\n".join(f'{name} = {{ version = "={version}"' + (', features = ["derive"]' if name == "serde" else "") + " }"
                             for name, version in versions.items())
    (workspace / "Cargo.toml").write_text(
        '[package]\nname = "biliup-danmaku-benchmark"\nversion = "0.0.0"\nedition = "2024"\n'
        '[workspace]\n[dependencies]\n' + dependencies + '\n'
        '[[bin]]\nname = "benchmark-driver"\npath = "main.rs"\n'
        '[profile.release]\nlto = true\ncodegen-units = 1\nstrip = true\nopt-level = 3\n')
    module_paths = {"api": NATIVE / "api.rs", "limits": NATIVE / "limits.rs", "native": NATIVE / "native/mod.rs",
                    "frozen_sys": croot / "src/lib.rs"}
    declarations = "\n".join(f"#[path = {json.dumps(str(path))}]\nmod {name};" for name, path in module_paths.items())
    (workspace / "main.rs").write_text(
        '#![allow(dead_code)]\n' + declarations + '\n'
        'pub use api::{ConvertError, ConvertOptions, ConvertStats, ErrorKind, block};\n'
        f'include!({json.dumps(str(HERE / "benchmark_native.rs"))});\n')
    (workspace / "build.rs").write_text(
        'fn main() {\n'
        f'    println!("cargo:rustc-link-search=native={{}}", {json.dumps(str(workspace))});\n'
        '    println!("cargo:rustc-link-lib=static=biliup_benchmark_bridge");\n'
        f'    println!("cargo:rustc-link-search=native={{}}", {json.dumps(str(libraries))});\n'
        '    println!("cargo:rustc-link-lib=static=biliup_df_core");\n'
        '    println!("cargo:rustc-link-lib=static=biliup_df_pcre2");\n'
        '}\n')
    # Resolve only in the isolated benchmark workspace. Exact direct versions
    # come from the real lock; its starting lock also pins transitive choices.
    shutil.copyfile(ROOT / "Cargo.lock", workspace / "Cargo.lock")
    commands.extend([
        ["cargo", "build", "--offline", "--release", "--manifest-path", str(workspace / "Cargo.toml")],
        ["cargo", "build", "--locked", "--offline", "--release", "--manifest-path", str(workspace / "Cargo.toml")],
    ])
    before = source_hashes()
    with (destination / "build.log").open("w") as log:
        for command in commands:
            log.write(json.dumps(command) + "\n")
            log.flush()
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
            if result.returncode:
                raise SystemExit(f"benchmark preparation failed ({result.returncode}); see {destination / 'build.log'}")
    if before != source_hashes():
        raise SystemExit("native/tooling sources changed during build; rerun prepare after integration stops")
    binary = workspace / "target/release/benchmark-driver"
    references = {"native_public_example": ROOT / "target/release/examples/convert",
                  "frozen_c_public_example": args.oracle_root / "build/release/examples/convert"}
    result = {
        "schema": 1, "prepared_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_sha256": before, "frozen_project_commit": manifest["project_commit"],
        "frozen_source_manifest_sha256": digest(HERE / "source.json"),
        "binary": str(binary), "binary_sha256": digest(binary),
        "isolated_lock_sha256": digest(workspace / "Cargo.lock"),
        "c_archive_sha256": {str(libraries / name): digest(libraries / name) for name in ["libbiliup_df_core.a", "libbiliup_df_pcre2.a"]},
        "commands": commands, "c_flags": flags,
        "rust_profile": {"opt_level": 3, "lto": True, "codegen_units": 1, "strip": True},
        "tools": [command_output(command) for command in [["rustc", "-Vv"], ["cargo", "-V"], [args.cc, "--version"]]],
        "public_examples_provenance_only": {name: {"path": str(path), "sha256": digest(path) if path.is_file() else None}
                                             for name, path in references.items()},
    }
    write_json(destination / "build.json", result)
    print(f"prepared {binary}; no timing measurements executed")


def check_build(destination):
    build = json.loads((destination / "build.json").read_text())
    if build["source_sha256"] != source_hashes():
        raise SystemExit("native/tooling source hashes changed; rerun benchmark.py prepare")
    if digest(build["binary"]) != build["binary_sha256"]:
        raise SystemExit("benchmark binary changed; rerun prepare")
    for path, expected in build["c_archive_sha256"].items():
        if digest(path) != expected:
            raise SystemExit(f"frozen archive changed: {path}")
    return build


def options_value(args):
    if args.options:
        return json.loads(args.options.read_text())
    cases = json.loads((HERE.parent / "golden/cases.json").read_text())
    return next(case["options"] for case in cases if case["name"] == "basic_cn-biliup")


def machine(destination):
    cpu = None
    if Path("/proc/cpuinfo").exists():
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), None)
    governors = sorted({path.read_text().strip() for path in Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor")})
    return {
        "platform": platform.platform(), "uname": list(platform.uname()), "cpu": cpu,
        "logical_cpus": os.cpu_count(), "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cpu_governors": governors, "load_average": list(os.getloadavg()),
        "output_filesystem": command_output(["df", "-T", str(destination)]) if sys.platform == "linux" else command_output(["df", str(destination)]),
        "python": sys.version, "environment": {key: os.environ.get(key) for key in ["LC_ALL", "LC_NUMERIC", "LANG", "RUSTFLAGS", "CFLAGS", "CC"]},
        "cache_policy": "warmups; no cache drop; repeated filesystem cache state not forced",
        "frequency_policy": "recorded only, no pinning or frequency changes",
        "concurrency_policy": "run sequentially after all builds/tests/other conversion workloads stop",
    }


def sample(binary, engine, source, output, options, timeout):
    before = time.perf_counter()
    try:
        process = subprocess.run([binary, engine, str(source), str(output), str(options)], capture_output=True, text=True,
                                 timeout=timeout, check=False, env={**os.environ, "LC_ALL": "C", "LC_NUMERIC": "C"})
    except subprocess.TimeoutExpired as failure:
        return {"engine": engine, "error": "timeout", "timeout_seconds": timeout,
                "process_wall_ms": (time.perf_counter() - before) * 1000,
                "stderr": (failure.stderr or b"").decode(errors="replace") if isinstance(failure.stderr, bytes) else failure.stderr}
    wall_ms = (time.perf_counter() - before) * 1000
    if process.returncode:
        return {"engine": engine, "error": "driver failed", "exit_code": process.returncode,
                "process_wall_ms": wall_ms, "stderr": process.stderr, "stdout": process.stdout}
    value = json.loads(process.stdout)
    value["process_wall_ms"] = wall_ms
    value["output_sha256"] = digest(output)
    before_cpu = resource.getrusage(resource.RUSAGE_SELF)
    before_cleanup = time.perf_counter()
    output.unlink()
    residue = list(output.parent.iterdir())
    after_cleanup = time.perf_counter()
    after_cpu = resource.getrusage(resource.RUSAGE_SELF)
    value["phases"]["cleanup_output"] = {
        "wall_ms": (after_cleanup - before_cleanup) * 1000,
        "cpu_user_ms": (after_cpu.ru_utime - before_cpu.ru_utime) * 1000,
        "cpu_system_ms": (after_cpu.ru_stime - before_cpu.ru_stime) * 1000,
    }
    value["cleanup_residue"] = [path.name for path in residue]
    if residue:
        value["error"] = "cleanup residue"
    return value


def summary(samples):
    clean = [sample for sample in samples if "error" not in sample]
    if len(clean) != len(samples) or not clean:
        return {"successful_trials": len(clean), "failed_trials": len(samples) - len(clean)}
    output = {"successful_trials": len(clean), "failed_trials": 0, "phases": {}}
    for phase in PHASES:
        output["phases"][phase] = {}
        for metric in METRICS:
            values = [sample["phases"][phase][metric] for sample in clean]
            output["phases"][phase][metric] = {"median": statistics.median(values), "min": min(values), "max": max(values),
                                               "stdev": statistics.stdev(values) if len(values) > 1 else 0.0}
    rss = [sample["peak_rss_bytes"] for sample in clean]
    output["peak_rss_bytes"] = {"median": statistics.median(rss), "min": min(rss), "max": max(rss)}
    output["output_bytes"] = clean[0]["output_bytes"]
    output["output_sha256"] = clean[0]["output_sha256"]
    output["deterministic_output"] = len({(sample["output_sha256"], sample["output_bytes"], json.dumps(sample["stats"], sort_keys=True)) for sample in clean}) == 1
    return output


def ratios(native, reference):
    result = {}
    for phase in ["core", "end_to_end", "cleanup_memory_and_handles", "cleanup_output"]:
        baseline = reference["phases"][phase]["wall_ms"]["median"]
        result[f"{phase}_wall_native_over_c"] = native["phases"][phase]["wall_ms"]["median"] / baseline if baseline else None
    baseline = reference["peak_rss_bytes"]["median"]
    result["peak_rss_native_over_c"] = native["peak_rss_bytes"]["median"] / baseline if baseline else None
    return result


def run(args, smoke=False):
    build = check_build(args.destination)
    names = args.names or (["small"] if smoke else list(workloads.WORKLOADS))
    inputs = args.destination / "inputs"
    workloads.generate(inputs, names)
    records = json.loads((inputs / "workloads.json").read_text())
    options = options_value(args)
    options_path = args.destination / "options.json"
    write_json(options_path, options)
    result = {
        "schema": 1, "mode": "functional_smoke_no_performance_claim" if smoke else "measurement",
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "build": build, "machine_start": machine(args.destination), "options": options,
        "options_sha256": digest(options_path), "warmups": 0 if smoke else args.warmups,
        "repeats": 1 if smoke else args.repeats, "timeout_seconds": args.timeout,
        "stage_contract": {"core": "actual read/parse/normalize/filter/sort/layout/serialize+flush, no sync, no list destruction",
                           "end_to_end": "same temporary creation+core+sync_all+persist_noclobber for C and native",
                           "cleanup_memory_and_handles": "drop native events / frozen freeList and published file handle",
                           "cleanup_output": "parent unlinks verified output and inspects residue; hashing excluded",
                           "cpu": "per-process getrusage user/system deltas per stage; peak RSS high-water bytes"},
        "workloads": [], "passed": True,
    }
    report = args.destination / ("smoke.json" if smoke else "results.json")
    for workload in records:
        source = inputs / f"{workload['name']}.xml"
        if digest(source) != workload["sha256"]:
            raise SystemExit(f"input changed: {source}")
        trials = []
        rounds = result["warmups"] + result["repeats"]
        for iteration in range(rounds):
            for engine in (["c", "native"] if iteration % 2 == 0 else ["native", "c"]):
                with tempfile.TemporaryDirectory(prefix=f"{workload['name']}-{engine}-", dir=args.destination) as work:
                    value = sample(build["binary"], engine, source, Path(work) / "output.ass", options_path, args.timeout)
                value.update({"iteration": iteration, "warmup": iteration < result["warmups"]})
                trials.append(value)
                print(f"{workload['name']} {engine} {'warmup' if value['warmup'] else 'trial'} {iteration}: {'FAILED' if 'error' in value else 'ok'}", flush=True)
        summaries = {engine: summary([trial for trial in trials if trial["engine"] == engine and not trial["warmup"]])
                     for engine in ["c", "native"]}
        successful = all("error" not in trial for trial in trials) and all(value.get("deterministic_output", False) for value in summaries.values())
        compatible = workload["intentional_change"] is None
        equal = successful and summaries["native"]["output_sha256"] == summaries["c"]["output_sha256"]
        if successful:
            stats = [trial["stats"] for trial in trials if not trial["warmup"]]
            equal = equal and all(stats[0] == item for item in stats[1:])
        passed = successful and (equal or not compatible)
        record = {**workload, "comparison": "equal-output-required" if compatible else "intentional-change-unequal-work-no-ratio",
                  "trials": trials, "summary": summaries, "output_and_stats_equal": equal, "passed": passed}
        if compatible and equal and not smoke:
            record["ratios"] = ratios(summaries["native"], summaries["c"])
        result["workloads"].append(record)
        result["passed"] &= passed
        write_json(report, result)
    result["machine_end"] = machine(args.destination)
    result["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_json(report, result)
    print(report)
    if not result["passed"]:
        raise SystemExit("benchmark validation failed; results retained, no acceptance claim")


def self_test():
    def trial(wall, rss=4096):
        return {"phases": {phase: {metric: wall for metric in METRICS} for phase in PHASES},
                "peak_rss_bytes": rss, "output_bytes": 10, "output_sha256": "hash", "stats": {"danmaku_count": 1}}
    value = summary([trial(1), trial(3), trial(2)])
    assert value["phases"]["core"]["wall_ms"]["median"] == 2
    assert value["deterministic_output"]
    assert summary([trial(1), {**trial(2), "output_sha256": "different"}])["deterministic_output"] is False
    assert summary([{"error": "failed"}])["failed_trials"] == 1
    assert ratios(value, value)["core_wall_native_over_c"] == 1
    assert not {path.name for path in HERE.glob("benchmark*") if path.is_dir()}
    print("benchmark summary/determinism/ratio self-tests passed; no conversions or timings executed")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["prepare", "smoke", "run", "self-test"])
    parser.add_argument("names", nargs="*", metavar="WORKLOAD")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--oracle-root", type=Path, default=ROOT / "target/danmaku-oracle")
    parser.add_argument("--c-libraries", type=Path)
    parser.add_argument("--options", type=Path)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--ar", default=os.environ.get("AR", "ar"))
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.warmups < 0 or args.repeats < 1 or args.timeout <= 0:
        parser.error("need warmups>=0, repeats>=1, timeout>0")
    if any(name not in workloads.WORKLOADS for name in args.names):
        parser.error(f"workloads must be among {list(workloads.WORKLOADS)}")
    for name in ["destination", "oracle_root", "c_libraries", "options"]:
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    if args.action == "prepare":
        prepare(args)
    elif args.action == "self-test":
        self_test()
    else:
        run(args, smoke=args.action == "smoke")


if __name__ == "__main__":
    main()

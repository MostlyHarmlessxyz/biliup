#!/usr/bin/env python3
"""Deterministic Gate 0/5 workloads, generated outside the source tree.

Prints sizes and SHA256 for replay; does not generate ASS expectations.
Long text deliberately exercises IC-03 and is not an equal-output benchmark.
"""

import argparse
import hashlib
import json
from pathlib import Path

WORKLOADS = {
    "small": (20, 250, 20, 1),
    "normal": (10_000, 200, 40, 1),
    "dense": (20_000, 10, 60, 1),
    "same_time": (10_000, 0, 30, 1),
    "long_text_ic03": (2_000, 100, 4096, 1),
    "special": (10_000, 100, 20, 7),
    # 127 MiB, <=1M comments, <=1023 bytes per body: equal-output baseline.
    "near_limit": (180_000, 100, 689, 1),
    # The independent count budget, with empty bodies and no event emission.
    # One million read nodes are still counted and processed by both engines.
    "near_count": (1_000_000, 0, 0, 0),
}


def generate(destination, names):
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for name in names:
        count, step_ms, text_bytes, mode = WORKLOADS[name]
        path = destination / f"{name}.xml"
        sha = hashlib.sha256()
        with path.open("wb") as file:
            def write(text):
                data = text.encode()
                sha.update(data)
                file.write(data)
            write('<?xml version="1.0" encoding="UTF-8"?><i>\n')
            for i in range(count):
                # ASCII length and stable input order are independent of Python RNG versions.
                text = (f"{i:08x}-" + "a" * text_bytes)[:text_bytes]
                if mode == 7:
                    text = f'[0.1,0.2,"1-0.5",4.5,"{text}",0,30,0.8,0.9,1500,200,true,"",1]'
                at = i * step_ms
                write(f'<d p="{at // 1000}.{at % 1000:03},{mode},25,16777215,0,0,0,0">{text}</d>\n')
            write('</i>\n')
        size = path.stat().st_size
        assert size <= 128 * 1024 * 1024
        records.append({"name": name, "count": count, "step_ms": step_ms, "text_bytes": text_bytes,
                        "mode": mode, "xml_bytes": size, "sha256": sha.hexdigest(),
                        "intentional_change": "IC-03" if name == "long_text_ic03" else None})
    (destination / "workloads.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("names", nargs="*", choices=WORKLOADS)
    args = parser.parse_args()
    generate(args.destination, args.names or list(WORKLOADS))

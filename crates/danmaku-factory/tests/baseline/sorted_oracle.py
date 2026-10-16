#!/usr/bin/env python3
"""IC-01/02 independent expectation: reorder XML, then run frozen C unchanged.

C's sorted fast path leaves equal-time input in order. Thus a stable input
permutation isolates the approved sort change while retaining C's real layout
and ASS serialization for every downstream event. Never rewrites Legacy assets.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
GOLDEN=HERE.parent/'golden'
DEST=HERE/'intentional'


def f32(value):
    return struct.unpack('f',struct.pack('f',value))[0]


def main():
    DEST.mkdir(exist_ok=True)
    expected=DEST/'unsorted-stable.ass'
    if expected.exists():
        raise SystemExit('independent expectation already frozen; refusing to overwrite')
    case=next(c for c in json.loads((GOLDEN/'cases.json').read_text()) if c['name']=='unsorted-biliup')
    document=ET.fromstring((GOLDEN/'inputs/unsorted.xml').read_bytes())
    def source_ms(element):
        seconds=f32(float(element.attrib['p'].split(',')[0]))
        return int(f32(f32(seconds*1000.)+0.5))
    original=list(document)
    indexed=sorted(enumerate(original),key=lambda pair:(source_ms(pair[1]),pair[0]))
    document[:]=[element for _,element in indexed]
    with tempfile.TemporaryDirectory() as work:
        input=Path(work)/'sorted.xml'
        output=Path(work)/'out.ass'
        ET.ElementTree(document).write(input,encoding='utf-8',xml_declaration=True)
        binary=ROOT/'target/danmaku-oracle/build/release/examples/convert'
        proc=subprocess.run([str(binary),str(input),str(output),json.dumps(case['options'])],capture_output=True,check=True)
        data=output.read_bytes()
        expected.write_bytes(data)
        record={'reference_project_commit':'76d03061053733d0c298677bf8ec22dac82263b8','method':__doc__,'sha256':hashlib.sha256(data).hexdigest(),'input_sequence':[i for i,_ in indexed],'source_time_ms':[source_ms(element) for _,element in indexed],'oracle_report':proc.stdout.decode().strip()}
        (DEST/'unsorted-stable.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()

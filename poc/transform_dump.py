#!/usr/bin/env python3
"""Transform `promtool tsdb dump` / `thanos-kit dump` output into NDJSON documents
for load_samples.py --input (or piping straight into it via stdin/stdout).

Input format (one sample per line, timestamp in epoch milliseconds):

  {__name__="node_cpu_seconds_total", cpu="0", instance="host-1:9100", job="node"} 12345.67 1759276800000

Output: one Elasticsearch document per line:

  {"@timestamp":"2025-10-01T00:00:00.000Z",
   "labels":{"cpu":"0","instance":"host-1:9100","job":"node"},
   "prometheus":{"node_cpu_seconds_total":12345.67}}

Behavior:
  - `__name__` becomes the metric field under --metric-root (default `prometheus`).
  - All other labels go under `labels.*` (the TSDS dimension namespace).
  - Non-finite values (NaN / staleness markers, +/-Inf) are skipped and counted.
  - Unparseable lines are skipped and counted; exit code 1 if any, so a broken
    dump never silently loses data.
  - --min-time / --max-time (ISO8601) let you clip a block's samples to the
    slice window you are migrating (blocks straddle month boundaries).
  - --drop-label can be repeated to remove Thanos-added external labels
    (e.g. replica/prometheus_replica) that would otherwise inflate cardinality.

Usage:
  promtool tsdb dump ./blocks/01H... | \
      transform_dump.py --drop-label prometheus_replica > out.ndjson
  transform_dump.py --input dump.txt --min-time 2025-10-01T00:00:00Z \
      --max-time 2025-11-01T00:00:00Z --output oct.ndjson
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone

LINE_RE = re.compile(r'^\{(?P<labels>.*)\}\s+(?P<value>\S+)\s+(?P<ts>\d+)\s*$')
LABEL_RE = re.compile(r'(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>(?:[^"\\]|\\.)*)"')


def unescape(v):
    return v.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="dump file (default: stdin)")
    ap.add_argument("--output", help="NDJSON file (default: stdout)")
    ap.add_argument("--metric-root", default="prometheus",
                    help="object the metric field is nested under "
                         "(use 'metrics' to match ES native remote_write schema)")
    ap.add_argument("--keep-name-label", action="store_true",
                    help="also keep __name__ under labels (matches ES native "
                         "remote_write documents)")
    ap.add_argument("--drop-label", action="append", default=[],
                    help="label to remove (repeatable), e.g. prometheus_replica")
    ap.add_argument("--min-time", help="ISO8601 inclusive lower bound")
    ap.add_argument("--max-time", help="ISO8601 exclusive upper bound")
    args = ap.parse_args()

    def to_ms(s):
        return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)

    min_ms = to_ms(args.min_time) if args.min_time else None
    max_ms = to_ms(args.max_time) if args.max_time else None
    drop = set(args.drop_label)

    src = open(args.input) if args.input else sys.stdin
    dst = open(args.output, "w") if args.output else sys.stdout

    stats = {"emitted": 0, "skipped_nonfinite": 0, "skipped_time": 0,
             "skipped_unparseable": 0, "skipped_no_name": 0}

    for line in src:
        line = line.strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        if not m:
            stats["skipped_unparseable"] += 1
            if stats["skipped_unparseable"] <= 5:
                print(f"unparseable: {line[:120]}", file=sys.stderr)
            continue

        ts = int(m.group("ts"))
        if (min_ms is not None and ts < min_ms) or (max_ms is not None and ts >= max_ms):
            stats["skipped_time"] += 1
            continue

        try:
            value = float(m.group("value"))
        except ValueError:
            stats["skipped_unparseable"] += 1
            continue
        if not math.isfinite(value):
            stats["skipped_nonfinite"] += 1
            continue

        labels, name = {}, None
        for lm in LABEL_RE.finditer(m.group("labels")):
            k, v = lm.group("name"), unescape(lm.group("value"))
            if k == "__name__":
                name = v
                if args.keep_name_label:
                    labels[k] = v
            elif k not in drop:
                labels[k] = v
        if not name:
            stats["skipped_no_name"] += 1
            continue

        iso = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)\
            .strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts % 1000:03d}Z"
        dst.write(json.dumps(
            {"@timestamp": iso, "labels": labels, args.metric_root: {name: value}},
            separators=(",", ":")) + "\n")
        stats["emitted"] += 1

    if args.output:
        dst.close()
    print(f"transform: {json.dumps(stats)}", file=sys.stderr)
    failures = stats["skipped_unparseable"] + stats["skipped_no_name"]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

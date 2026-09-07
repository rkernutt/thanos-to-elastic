#!/usr/bin/env python3
"""Bulk-load historical Prometheus-style samples into a TSDS via the data stream name.

Two modes:
  --synthetic : generate samples (N series x scrape interval x time range) to prove
                the pipeline at scale.
  --input F   : read NDJSON docs (one ES document per line) — this is the adapter
                point for real data: pipe the output of `promtool tsdb dump` /
                `thanos-kit dump` through a small transform into this shape.

All docs are sent with op_type=create against the data stream; TSDS routes each
doc to the backing slice covering its @timestamp. 409 (version conflict) means
"already ingested" — counted separately and treated as success, which makes
re-runs after a crash safely idempotent.

Usage:
  load_samples.py --es http://localhost:9200 --stream metrics-promtest.node \
      --synthetic --series 8 --interval 900 \
      --from 2025-09-01T00:00:00Z --to 2026-09-01T00:00:00Z
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BATCH = 5000


def bulk(es, stream, lines):
    body = "\n".join(lines) + "\n"
    h = {"Content-Type": "application/x-ndjson"}
    if os.environ.get("ES_API_KEY"):
        h["Authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
    r = urllib.request.Request(
        es.rstrip("/") + f"/{stream}/_bulk", data=body.encode(),
        method="POST", headers=h)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read())


def flush(es, stream, buf, stats):
    if not buf:
        return
    res = bulk(es, stream, buf)
    for item in res["items"]:
        st = item["create"]["status"]
        if st == 201:
            stats["created"] += 1
        elif st == 409:
            stats["duplicate"] += 1
        else:
            stats["failed"] += 1
            if stats["failed"] <= 5:
                print("  ERROR:", json.dumps(item["create"].get("error"))[:200], file=sys.stderr)
    buf.clear()


def synthetic_docs(n_series, interval, t_from, t_to):
    counters = [0.0] * n_series
    t = t_from
    while t < t_to:
        ts = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for s in range(n_series):
            counters[s] += (s + 1) * 0.7 * interval / 60
            yield {
                "@timestamp": ts,
                "labels": {"job": "node", "instance": f"host-{s}:9100"},
                "prometheus": {
                    "test_gauge": round(0.1 + (s * 7 + t // interval) % 90 / 100, 3),
                    "node_cpu_seconds_total": round(counters[s], 2),
                },
            }
        t += interval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--es", default="http://localhost:9200")
    ap.add_argument("--stream", required=True)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--input", help="NDJSON file of ES docs")
    ap.add_argument("--series", type=int, default=8)
    ap.add_argument("--interval", type=int, default=900, help="seconds between samples")
    ap.add_argument("--from", dest="t_from", help="ISO8601 start")
    ap.add_argument("--to", dest="t_to", help="ISO8601 end")
    args = ap.parse_args()

    if args.synthetic:
        t_from = int(datetime.strptime(args.t_from, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
        t_to = int(datetime.strptime(args.t_to, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
        docs = synthetic_docs(args.series, args.interval, t_from, t_to)
    elif args.input:
        docs = (json.loads(line) for line in open(args.input) if line.strip())
    else:
        sys.exit("need --synthetic or --input")

    stats = {"created": 0, "duplicate": 0, "failed": 0}
    buf = []
    start = time.time()
    for doc in docs:
        buf.append('{"create":{}}')
        buf.append(json.dumps(doc, separators=(",", ":")))
        if len(buf) >= BATCH * 2:
            flush(args.es, args.stream, buf, stats)
    flush(args.es, args.stream, buf, stats)

    dur = time.time() - start
    total = sum(stats.values())
    print(f"done: {total} docs in {dur:.1f}s ({total/dur:,.0f} docs/s) -> "
          f"created={stats['created']} duplicate={stats['duplicate']} failed={stats['failed']}")
    sys.exit(1 if stats["failed"] else 0)


if __name__ == "__main__":
    main()

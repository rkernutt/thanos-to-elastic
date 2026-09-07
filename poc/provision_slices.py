#!/usr/bin/env python3
"""Provision historical backfill slice indices for a TSDS and attach them to the data stream.

For each calendar month in [--start, --end) this script:
  1. Creates an index `backfill-<stream>-YYYY.MM` with index.mode=time_series,
     explicit index.time_series.start_time/end_time, and mappings cloned from the
     data stream's current write index.
  2. Attaches it to the data stream via _data_stream/_modify add_backing_index.

After that, historical documents can be bulk-indexed *via the data stream name*
and TSDS routes each doc to the correct slice by @timestamp.

The final slice's end_time is clamped so it never overlaps the live backing
indices (Elasticsearch rejects overlapping backing index time ranges).

Idempotent: existing indices and already-attached slices are skipped.

Usage:
  provision_slices.py --es http://localhost:9200 --stream metrics-promtest.node \
      --start 2025-09 --end 2026-09
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone


def headers():
    h = {"Content-Type": "application/json"}
    if os.environ.get("ES_API_KEY"):
        h["Authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
    return h


def req(es, method, path, body=None):
    url = es.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers())
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def month_iter(start, end):
    """Yield (slice_start, slice_end) datetimes for each month in [start, end)."""
    y, m = start
    while (y, m) < end:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield (datetime(y, m, 1, tzinfo=timezone.utc),
               datetime(ny, nm, 1, tzinfo=timezone.utc))
        y, m = ny, nm


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--es", default="http://localhost:9200")
    ap.add_argument("--stream", required=True)
    ap.add_argument("--start", required=True, help="first month, YYYY-MM")
    ap.add_argument("--end", required=True, help="end month (exclusive), YYYY-MM")
    ap.add_argument("--routing-path", default="labels.*",
                    help="comma-separated index.routing_path (must cover the dimension fields)")
    args = ap.parse_args()

    start = tuple(int(x) for x in args.start.split("-"))
    end = tuple(int(x) for x in args.end.split("-"))

    # Discover the data stream, its write index, and current backing indices
    status, ds = req(args.es, "GET", f"/_data_stream/{args.stream}")
    if status != 200:
        sys.exit(f"data stream {args.stream} not found: {ds}")
    ds = ds["data_streams"][0]
    backing = [i["index_name"] for i in ds["indices"]]
    write_index = backing[-1]

    # Clone mappings from the write index so dimensions/metrics match exactly
    _, m = req(args.es, "GET", f"/{write_index}/_mapping")
    mappings = m[write_index]["mappings"]

    # Find the earliest start_time among live (.ds-*) backing indices, to clamp against
    live_floor = None
    for idx in backing:
        _, s = req(args.es, "GET", f"/{idx}/_settings/index.time_series.start_time")
        st = s.get(idx, {}).get("settings", {}).get("index", {}).get("time_series", {}).get("start_time")
        if st and idx.startswith(".ds-"):
            dt = datetime.strptime(st, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) \
                if "." in st else datetime.strptime(st, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            live_floor = dt if live_floor is None or dt < live_floor else live_floor

    for slice_start, slice_end in month_iter(start, end):
        if live_floor and slice_start >= live_floor:
            print(f"skip {slice_start:%Y.%m}: at/after live data start ({iso(live_floor)})")
            continue
        if live_floor and slice_end > live_floor:
            print(f"clamp {slice_start:%Y.%m}: end_time {iso(slice_end)} -> {iso(live_floor)}")
            slice_end = live_floor

        name = f"backfill-{args.stream}-{slice_start:%Y.%m}"
        status, _ = req(args.es, "HEAD", f"/{name}")
        if status == 200:
            print(f"exists {name}")
        else:
            status, r = req(args.es, "PUT", f"/{name}", {
                "settings": {
                    "index.mode": "time_series",
                    "index.routing_path": args.routing_path.split(","),
                    "index.time_series.start_time": iso(slice_start),
                    "index.time_series.end_time": iso(slice_end),
                    "index.number_of_replicas": 0,
                },
                "mappings": mappings,
            })
            if status != 200:
                sys.exit(f"create {name} failed: {r}")
            print(f"created {name} [{iso(slice_start)} .. {iso(slice_end)})")

        if name in backing:
            print(f"attached already: {name}")
            continue
        status, r = req(args.es, "POST", "/_data_stream/_modify", {
            "actions": [{"add_backing_index": {"data_stream": args.stream, "index": name}}]
        })
        if status != 200:
            sys.exit(f"attach {name} failed: {r}")
        print(f"attached {name} -> {args.stream}")


if __name__ == "__main__":
    main()

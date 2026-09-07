#!/usr/bin/env python3
"""Probe Elasticsearch's native Prometheus remote_write endpoint (9.5+) —
including with HISTORICAL timestamps, to test the backfill-over-remote-write path.

Speaks the Prometheus remote write 1.0 wire format (protobuf WriteRequest)
hand-encoded with stdlib only. Elasticsearch accepts uncompressed protobuf
(snappy is optional on this endpoint), so no external libraries are needed.

Endpoints (ES 9.5):
  POST /_prometheus/api/v1/write                      -> metrics-generic.default
  POST /_prometheus/metrics/{dataset}/api/v1/write
  POST /_prometheus/metrics/{dataset}/{namespace}/api/v1/write

Usage:
  remote_write_probe.py --es http://localhost:9200 \
      --metric node_cpu_seconds_total --value 123.4 \
      --timestamp 2025-09-04T12:00:00Z \
      --label job=node --label instance=host-1:9100
"""
import argparse
import json
import os
import struct
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def ld(tag, payload):  # length-delimited field
    return varint((tag << 3) | 2) + varint(len(payload)) + payload


def label(name, value):
    return ld(1, name.encode()) + ld(2, value.encode())


def sample(value, ts_ms):
    # field 1: double (wire type 1), field 2: int64 varint
    return bytes([0x09]) + struct.pack("<d", value) + bytes([0x10]) + varint(ts_ms)


def write_request(series):
    """series: list of (labels_dict, [(value, ts_ms), ...]) — labels must be
    sorted by name and include __name__, per the remote write spec."""
    body = b""
    for labels, samples in series:
        ts = b""
        for k in sorted(labels):
            ts += ld(1, label(k, labels[k]))
        for v, t in samples:
            ts += ld(2, sample(v, t))
        body += ld(1, ts)
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--es", default="http://localhost:9200")
    ap.add_argument("--dataset", help="optional dataset (URL path routing)")
    ap.add_argument("--namespace", help="optional namespace (requires --dataset)")
    ap.add_argument("--metric", required=True)
    ap.add_argument("--value", type=float, required=True)
    ap.add_argument("--timestamp", required=True, help="ISO8601, e.g. 2025-09-04T12:00:00Z")
    ap.add_argument("--label", action="append", default=[], help="k=v, repeatable")
    args = ap.parse_args()

    ts_ms = int(datetime.strptime(args.timestamp, "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc).timestamp() * 1000)
    labels = {"__name__": args.metric}
    for kv in args.label:
        k, _, v = kv.partition("=")
        labels[k] = v

    path = "/_prometheus/api/v1/write"
    if args.dataset and args.namespace:
        path = f"/_prometheus/metrics/{args.dataset}/{args.namespace}/api/v1/write"
    elif args.dataset:
        path = f"/_prometheus/metrics/{args.dataset}/api/v1/write"

    body = write_request([(labels, [(args.value, ts_ms)])])
    headers = {
        "Content-Type": "application/x-protobuf",
        "X-Prometheus-Remote-Write-Version": "0.1.0",
    }
    if os.environ.get("ES_API_KEY"):
        headers["Authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"

    req = urllib.request.Request(args.es.rstrip("/") + path, data=body,
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"HTTP {resp.status} — accepted ({len(body)} bytes protobuf, ts={args.timestamp})")
            payload = resp.read()
            if payload:
                print(payload.decode(errors="replace")[:300])
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} — rejected")
        print(e.read().decode(errors="replace")[:500])
        sys.exit(1)


if __name__ == "__main__":
    main()

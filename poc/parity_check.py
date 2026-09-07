#!/usr/bin/env python3
"""Compare query results for a migrated metric between a Prometheus-compatible
endpoint (Prometheus, Thanos Query) and Elasticsearch ES|QL time series functions.

For each aligned time bucket it compares, per series:
  counter: PromQL  rate(metric[<bucket>])   evaluated at bucket END
           ES|QL   TS <stream> | STATS SUM(RATE(field)) BY label, TBUCKET(<bucket>)
  gauge:   PromQL  avg_over_time(metric[<bucket>])
           ES|QL   AVG(AVG_OVER_TIME(field)) BY label, TBUCKET(<bucket>)

NOTE: inside the TS command a bare AVG(gauge) is NOT a window average — TS
applies an implicit last_over_time per series per bucket. The explicit
*_OVER_TIME function is required for PromQL-equivalent semantics (verified:
bare AVG returned the bucket's last sample, a ~3-6% systematic error on a
smooth signal).

Alignment: an ES bucket [t, t+w) corresponds to the PromQL evaluation at t+w
with lookback window w.

Reports per-bucket relative error and a summary (median/p95/max). Expect small
differences on counters: PromQL rate() extrapolates to window boundaries,
ES|QL RATE() does not. Large errors flag real problems (missing samples,
wrong counter mapping, reset mishandling).

Usage (local harness):
  parity_check.py --prom http://localhost:9090 --es http://localhost:9202 \
      --stream metrics-parity.check --metric parity_requests_total \
      --es-field prometheus.parity_requests_total --kind counter \
      --start 2025-10-01T00:00:00Z --end 2025-10-03T00:00:00Z --bucket 3600

Against a real Thanos: point --prom at the Thanos Query frontend and add
ES_API_KEY to the environment for the Elasticsearch side.
"""
import argparse
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def iso_to_epoch(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def http_json(url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h)) as r:
        return json.loads(r.read())


def prom_series(args, start, end):
    """{(group_label_value, bucket_start_epoch): value} from query_range."""
    w = f"{args.bucket}s"
    q = (f"rate({args.metric}[{w}])" if args.kind == "counter"
         else f"avg_over_time({args.metric}[{w}])")
    # evaluate at bucket ENDs; PromQL window (t-w, t] maps to ES bucket [t-w, t)
    params = urllib.parse.urlencode({
        "query": q, "start": start + args.bucket, "end": end, "step": args.bucket})
    r = http_json(f"{args.prom.rstrip('/')}/api/v1/query_range?{params}")
    out = {}
    for series in r["data"]["result"]:
        key = series["metric"].get(args.by, "?")
        for ts, val in series["values"]:
            out[(key, int(ts) - args.bucket)] = float(val)
    return out


def es_series(args, start, end):
    agg = (f"SUM(RATE({args.es_field}))" if args.kind == "counter"
           else f"AVG(AVG_OVER_TIME({args.es_field}))")
    q = (f'TS {args.stream} '
         f'| WHERE @timestamp >= "{datetime.fromtimestamp(start, tz=timezone.utc):%Y-%m-%dT%H:%M:%SZ}" '
         f'AND @timestamp < "{datetime.fromtimestamp(end, tz=timezone.utc):%Y-%m-%dT%H:%M:%SZ}" '
         f'AND labels.__name__ == "{args.metric}" '
         f'| STATS v = {agg} BY g = labels.{args.by}, b = TBUCKET({args.bucket} seconds) '
         f'| SORT g, b | LIMIT 10000')
    headers = {}
    if os.environ.get("ES_API_KEY"):
        headers["Authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
    r = http_json(f"{args.es.rstrip('/')}/_query", {"query": q}, headers)
    cols = [c["name"] for c in r["columns"]]
    vi, gi, bi = cols.index("v"), cols.index("g"), cols.index("b")
    out = {}
    for row in r["values"]:
        if row[vi] is None:
            continue
        ts = int(datetime.strptime(row[bi], "%Y-%m-%dT%H:%M:%S.%fZ")
                 .replace(tzinfo=timezone.utc).timestamp())
        out[(row[gi], ts)] = float(row[vi])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", required=True, help="Prometheus/Thanos Query base URL")
    ap.add_argument("--es", required=True)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--metric", required=True, help="Prometheus metric name")
    ap.add_argument("--es-field", required=True, help="ES field, e.g. prometheus.<metric>")
    ap.add_argument("--kind", choices=["counter", "gauge"], required=True)
    ap.add_argument("--by", default="instance", help="label to group/compare by")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--bucket", type=int, default=3600, help="seconds")
    ap.add_argument("--verbose", action="store_true", help="print every bucket")
    args = ap.parse_args()

    start, end = iso_to_epoch(args.start), iso_to_epoch(args.end)
    prom = prom_series(args, start, end)
    es = es_series(args, start, end)

    common = sorted(set(prom) & set(es))
    if not common:
        sys.exit(f"no overlapping buckets (prom={len(prom)}, es={len(es)})")

    errors = []
    print(f"{'series':<12} {'bucket (UTC)':<22} {'prometheus':>14} {'elasticsearch':>14} {'rel_err':>9}")
    for key in common:
        p, e = prom[key], es[key]
        rel = abs(p - e) / max(abs(p), abs(e), 1e-12)
        errors.append(rel)
        if args.verbose or rel > 0.02:
            ts = datetime.fromtimestamp(key[1], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            flag = "  <-- >2%" if rel > 0.02 else ""
            print(f"{key[0]:<12} {ts:<22} {p:>14.6f} {e:>14.6f} {rel:>8.4%}{flag}")

    only_prom, only_es = len(set(prom) - set(es)), len(set(es) - set(prom))
    errors.sort()
    print(f"\ncompared {len(common)} buckets "
          f"(prom-only: {only_prom}, es-only: {only_es})")
    print(f"relative error: median={statistics.median(errors):.4%} "
          f"p95={errors[int(len(errors)*0.95)]:.4%} max={errors[-1]:.4%}")
    sys.exit(0 if errors[-1] <= 0.05 else 1)


if __name__ == "__main__":
    main()

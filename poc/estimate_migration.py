#!/usr/bin/env python3
"""Predict wall-clock duration (and ES storage) for a Thanos-to-Elastic backfill.

Feed it the sample counts from `thanos tools bucket inspect` (per resolution,
AFTER you have chosen the raw/5m/1h windows to migrate) and it applies
measured per-stage rates to estimate duration and identify the bottleneck.

Default rates were measured on this kit's 4.6M-sample benchmark
(2026-09-08, laptop-class hardware, single worker; see FINDINGS.md):
  promtool tsdb dump   ~620k samples/s per core
  transform_dump.py    ~128k samples/s per process   <- per-worker bottleneck
  load_samples.py      ~53k docs/s per client (single-node ES, Path A)
  TSDB block size      ~2.8 B/sample (synthetic; real-world 1.3-3 B/sample)
  ES store (merged)    ~38 B/sample

The stages stream (dump | transform | load), so a worker moves at the rate of
its slowest stage. Workers process independent blocks in parallel and scale
linearly until the Elasticsearch ingest ceiling is reached — measure/raise
that with the cluster team; 150k docs/s is a conservative hot-tier default.

Example:
  estimate_migration.py --samples 20e9 --workers 8 --es-ceiling 200000
"""
import argparse


def human(seconds):
    if seconds < 3600:
        return f"{seconds/60:.0f} min"
    if seconds < 172800:
        return f"{seconds/3600:.1f} h"
    return f"{seconds/86400:.1f} days"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=float, required=True,
                    help="total samples to migrate (e.g. 20e9), summed over "
                         "the chosen raw/5m/1h windows")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel export workers (each runs dump|transform|load)")
    ap.add_argument("--dump-rate", type=float, default=620_000)
    ap.add_argument("--transform-rate", type=float, default=128_000)
    ap.add_argument("--load-rate", type=float, default=53_000,
                    help="per-client bulk rate (docs/s)")
    ap.add_argument("--es-ceiling", type=float, default=150_000,
                    help="aggregate cluster ingest ceiling (docs/s)")
    ap.add_argument("--download-mbps", type=float, default=200,
                    help="sustained object-store download MB/s per worker")
    ap.add_argument("--bytes-per-sample-block", type=float, default=2.0,
                    help="TSDB block bytes per sample (bucket inspect: size/samples)")
    ap.add_argument("--bytes-per-sample-es", type=float, default=38,
                    help="ES store bytes per sample after force-merge")
    args = ap.parse_args()

    n = args.samples
    per_worker = min(args.dump_rate, args.transform_rate, args.load_rate)
    stages = {"dump": args.dump_rate, "transform": args.transform_rate,
              "load": args.load_rate}
    bottleneck = min(stages, key=stages.get)

    fleet = per_worker * args.workers
    effective = min(fleet, args.es_ceiling)
    limited_by = "ES ingest ceiling" if fleet > args.es_ceiling else \
        f"worker pipeline ({bottleneck} stage)"

    dl_seconds = n * args.bytes_per_sample_block / (args.download_mbps * 1e6 * args.workers)
    wall = n / effective  # download overlaps the pipeline; report separately

    print(f"samples to migrate:      {n:,.0f}")
    print(f"block download:          {n*args.bytes_per_sample_block/1e9:,.1f} GB "
          f"(~{human(dl_seconds)} across {args.workers} workers — overlaps processing)")
    print(f"per-worker pipeline:     {per_worker:,.0f} samples/s (bottleneck: {bottleneck})")
    print(f"{args.workers} workers combined:      {fleet:,.0f} samples/s")
    print(f"effective rate:          {effective:,.0f} samples/s (limited by {limited_by})")
    print(f"estimated wall clock:    {human(wall)}")
    print(f"ES storage (pre-tier):   ~{n*args.bytes_per_sample_es/1e9:,.0f} GB "
          f"(force-merged, before cold/frozen tiering)")
    if fleet > args.es_ceiling * 1.5:
        print("note: workers are heavily over-provisioned vs the ES ceiling — "
              "fewer workers reach the same wall clock")
    elif fleet < args.es_ceiling * 0.7:
        print(f"note: adding workers helps until ~{args.es_ceiling/per_worker:.0f} "
              f"workers saturate the ES ceiling")


if __name__ == "__main__":
    main()

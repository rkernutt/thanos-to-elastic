# thanos-to-elastic

Migration kit for moving long-term Prometheus metrics history out of Thanos
(S3-backed, AWS) and into Elastic time series data streams (TSDS), so Thanos
and its infrastructure can be retired while Elastic holds ≥12 months of
metrics retention alongside logs and APM.

## Where to start

| Doc | What it is |
|-----|-----------|
| [RUNBOOK.md](RUNBOOK.md) | The end-to-end procedure: AWS + Elastic prerequisites, IAM policy, script input reference, per-block export loop, validation, ILM, decommission and rollback |
| [FINDINGS.md](FINDINGS.md) | The verified evidence: why naive backfill fails, the slice recipe, every gotcha hit during trial-and-error, and the 9.1.3 vs 9.5.3 version matrix |

## The scripts (`poc/`)

All Python 3 stdlib only — nothing to install. Auth via `ES_API_KEY` env var.

- **`provision_slices.py`** — creates monthly `time_series` backfill indices
  (explicit `start_time`/`end_time`, mappings cloned from the live write
  index) and attaches them to the live data stream. Clamps against live data
  automatically. Idempotent.
- **`transform_dump.py`** — converts `promtool tsdb dump` / `thanos-kit dump`
  text output into ES documents: labels → dimensions, `__name__` → metric
  field, drops Thanos replica labels, clips to a time window, skips
  staleness markers.
- **`load_samples.py`** — bulk-loads NDJSON docs through the data stream
  name (TSDS routes by timestamp to the right slice). Treats 409 as
  "already ingested", so crashed runs are resumed by re-running. Also has a
  `--synthetic` generator used for the scale tests.

## Verified

- Elasticsearch **9.1.3** and **9.5.3** (Docker, fresh runs on each)
- 280,320 samples across 12 monthly slices at ~60k docs/s single-threaded;
  exact per-slice routing; full-replay idempotency (`created=0 failed=0`)
- One ES|QL query spans backfilled + live data seamlessly; on 9.5.3,
  `TS … RATE()` returns numerically exact rates from backfilled counters

## Local reproduction

```bash
docker run -d --name es-tsds-poc -p 9200:9200 \
  -e discovery.type=single-node -e xpack.security.enabled=false \
  -e ES_JAVA_OPTS="-Xms1g -Xmx1g" \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.3

# create a Prometheus-style TSDS template + live stream (see FINDINGS.md), then:
python3 poc/provision_slices.py --stream metrics-promtest.node \
    --start 2025-09 --end 2026-09
python3 poc/load_samples.py --stream metrics-promtest.node --synthetic \
    --series 8 --interval 900 \
    --from 2025-09-01T00:00:00Z --to 2026-09-01T00:00:00Z
```

## Status / open items

- Serverless compatibility unvalidated (index-setting restrictions) —
  confirm the customer's target platform.
- `rate()` parity spot-checked on synthetic counters (exact); definitive
  check is side-by-side vs Thanos on one real migrated month.
- ILM policy for `backfill-*` slices must be applied explicitly (attached
  slices don't roll over).

# Runbook: migrating 12 months of Thanos (S3) history into Elastic

End-to-end procedure for exporting Prometheus TSDB blocks from a Thanos S3
bucket and backfilling them into Elastic time series data streams (TSDS), so
Thanos and its infrastructure can be retired. The backfill mechanics in this
runbook are verified against Elasticsearch 9.1.3 and 9.5.3 — see
[FINDINGS.md](FINDINGS.md) for the evidence and gotchas.

## Pipeline overview

```
Thanos S3 bucket (TSDB blocks: raw / 5m / 1h resolutions)
  │  aws s3 sync (per block, in-region EC2 worker)
  ▼
Local block dirs ──► promtool tsdb dump / thanos-kit dump   (text samples)
  │
  ▼
poc/transform_dump.py      labels → dimensions, __name__ → metric field,
  │                        drop replica labels, clip to window, skip NaN
  ▼
poc/load_samples.py        bulk via DATA STREAM name, 409 = already loaded
  │
  ▼
Elastic data stream ◄── poc/provision_slices.py   (monthly time_series slices
                         with explicit start/end, attached BEFORE loading)
```

Order matters: **live Prometheus remote_write shipping to Elastic must be
running before the backfill starts.** Historical slices must butt up exactly
against the live data's start time; a gap can never be filled later
(Elasticsearch rejects overlapping slices and refuses writes into uncovered
time ranges).

---

## Prerequisites

### AWS

- **Read-only access to the Thanos bucket.** Get the bucket/prefix from the
  Thanos `objstore.yml` (the config given to store gateway/compactor). Minimum
  IAM policy for the migration worker:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      { "Effect": "Allow", "Action": ["s3:ListBucket"],
        "Resource": "arn:aws:s3:::THANOS_BUCKET" },
      { "Effect": "Allow", "Action": ["s3:GetObject"],
        "Resource": "arn:aws:s3:::THANOS_BUCKET/*" }
    ]
  }
  ```

- **Run the worker in the same region as the bucket** (EC2 or container).
  Blocks can total TBs; same-region S3 reads are free of transfer charges,
  cross-region/egress is not. A c/m-family instance with fast local disk
  (enough for the largest single block, typically tens of GB) is sufficient —
  blocks are processed one at a time and deleted after loading.
- **Freeze the compactor before starting.** Compaction rewrites/deletes
  blocks mid-migration and will invalidate your block inventory. Stopping
  Thanos ingest (sidecars/receive) first also fixes the upper time bound.

### Elastic

- **Elastic Cloud Hosted or self-managed, 9.x** (9.5+ recommended: `TS` +
  `RATE()` in ES|QL verified against backfilled data). **Serverless is not
  yet validated** for this recipe — it restricts index-level settings; check
  before committing.
- **Prometheus integration installed and live remote_write flowing** — the
  provisioner clones mappings from the live write index, so the live stream
  defines the schema the history inherits.
- **Mappings must dimension-map dynamic labels** (verified gotcha #7): the
  index template needs a `dynamic_templates` rule mapping `labels.*` (or the
  integration's label path) to `keyword` + `time_series_dimension: true`.
  The official Prometheus integration ships this; verify before loading.
- **API key privileges** for the migration user/key:
  - cluster: `monitor`
  - `backfill-*` indices: `create_index`, `manage`
  - target data stream + backing indices: `manage`, `create_doc`, `read`
    (`_data_stream/_modify` requires manage on the stream)
- **Capacity**: the backfill lands on whatever tier the slices sit on until
  you move them. Plan ILM up front (see step 7) so 12 months of history goes
  to cold/frozen, not hot.

### Migration worker tooling

| Tool | Purpose | Notes |
|------|---------|-------|
| `aws` CLI v2 | sync blocks from S3 | or any S3 client |
| `thanos` CLI | `thanos tools bucket inspect/ls` for block inventory | same version as their Thanos |
| `promtool` (Prometheus ≥2.40) or [`thanos-kit`](https://github.com/sepich/thanos-kit) | dump block samples to text | thanos-kit understands Thanos block metadata/labels natively |
| Python 3.9+ | runs the three `poc/` scripts | stdlib only, no pip installs |
| jq (optional) | block meta.json filtering | |

---

## Script input reference

All scripts read `ES_API_KEY` from the environment and send it as an
`Authorization: ApiKey …` header. Unset = unauthenticated (local PoC).

### `poc/provision_slices.py` — create + attach historical slices

| Input | Required | Meaning |
|-------|----------|---------|
| `--es URL` | no (default `http://localhost:9200`) | Elasticsearch endpoint |
| `--stream NAME` | yes | target data stream (must already exist with a live write index) |
| `--start YYYY-MM` | yes | first month of history (inclusive) |
| `--end YYYY-MM` | yes | end month (exclusive) — use the month containing the live-shipping start; the script clamps the last slice to the live index's `start_time` automatically |
| `--routing-path CSV` | no (default `labels.*`) | must cover every dimension field in the schema |

Idempotent — re-run freely. Creates `backfill-<stream>-YYYY.MM` indices and
attaches them via `_data_stream/_modify`.

### `poc/transform_dump.py` — dump text → NDJSON docs

| Input | Required | Meaning |
|-------|----------|---------|
| `--input FILE` / stdin | yes | `promtool tsdb dump` / `thanos-kit dump` output |
| `--output FILE` / stdout | yes | NDJSON, one ES doc per line |
| `--metric-root NAME` | no (default `prometheus`) | object the metric field nests under — match the live integration's schema |
| `--drop-label L` (repeatable) | recommended | strip Thanos external labels (`prometheus_replica`, `replica`, …) that would explode cardinality |
| `--min-time` / `--max-time` ISO8601 | recommended | clip block samples to the window being migrated (blocks straddle boundaries) |

Skips NaN/staleness markers and counts everything; nonzero exit if any line
was unparseable (never silently loses data).

### `poc/load_samples.py` — bulk load via the data stream

| Input | Required | Meaning |
|-------|----------|---------|
| `--es URL` | no | Elasticsearch endpoint |
| `--stream NAME` | yes | data stream (NOT a backing index — direct backing-index writes are rejected) |
| `--input FILE` | yes (prod) | NDJSON from transform_dump.py |
| `--synthetic --series N --interval S --from ISO --to ISO` | testing only | generator used for the PoC scale runs |

409s are counted as `duplicate` and treated as success → any failed/killed
run is resumed by simply re-running the same command.

---

## Procedure

### 0. Decisions and sizing (before touching anything)

1. Inventory the bucket:
   ```bash
   thanos tools bucket inspect --objstore.config-file=objstore.yml
   ```
   Capture per-resolution totals: block count, series, samples, size.
   Resolution is in each block's `meta.json` → `thanos.downsample.resolution`
   (`0` = raw, `300000` = 5m, `3600000` = 1h).
2. **Choose resolution windows** — do not migrate raw for all 12 months.
   Mirror what Thanos serves today, e.g. raw for the newest 30–90 days, 5m
   for the mid range, 1h for the oldest. This cuts volume 20–50×.
   **Never load two resolutions for the same series+time range** — first
   write wins silently (gotcha #6); partition strictly by time window.
3. Agree the label-drop list (`prometheus_replica` etc.) and confirm the
   metric field schema of the live integration (`--metric-root`).
4. Estimate: `samples ≈ Σ (series × window_seconds / resolution_seconds)`,
   docs ≈ samples (one metric per doc with this transform). Verified loader
   throughput: ~60k docs/s per worker process, so ingest capacity on the
   Elastic side is the real limit — plan hot-tier headroom for the load.

### 1. Freeze Thanos writes

Stop compactor; stop sidecar uploads/receive once live remote_write to
Elastic is confirmed flowing. Record `T_live` = timestamp live Elastic
ingestion started. The bucket is now immutable — snapshot the block list.

### 2. Provision slices

```bash
export ES_API_KEY=...
python3 poc/provision_slices.py --es https://CLUSTER:9243 \
    --stream metrics-<dataset>.<namespace> \
    --start 2025-09 --end 2026-09
```

Repeat per target data stream if metrics are split across datasets. Verify:
`GET _data_stream/<stream>` lists all backfill indices, in time order.

### 3. Export → transform → load, per block

Work **oldest first** (1h-resolution blocks: smallest, proves the pipeline
end-to-end before the big raw blocks). Per block:

```bash
B=01H0000000000000000000000000   # block ULID from the inventory
aws s3 sync s3://THANOS_BUCKET/$B ./work/$B --only-show-errors

promtool tsdb dump ./work/$B \
  | python3 poc/transform_dump.py \
      --drop-label prometheus_replica --drop-label replica \
      --min-time 2025-10-01T00:00:00Z --max-time 2025-11-01T00:00:00Z \
  | python3 poc/load_samples.py --es https://CLUSTER:9243 \
      --stream metrics-<dataset>.<namespace> --input /dev/stdin

rm -rf ./work/$B    # only after load reports failed=0
```

Parallelize by running one such loop per block on N workers — blocks are
independent, and 409-idempotency makes any crash/rerun safe. Track completed
block ULIDs in a simple manifest file; a re-run of a completed block is
harmless (all 409s) but wasted time.

### 4. Verify each month before moving on

```bash
# per-slice counts (backing indices are hidden — gotcha #4)
GET _cat/indices/backfill-*?h=index,docs.count&s=index&expand_wildcards=all

# continuity + gauge sanity via ES|QL
POST _query { "query": "FROM <stream> | STATS c=COUNT(*) BY month=DATE_TRUNC(1 month, @timestamp) | SORT month" }

# counter/rate parity (9.5+): same range, side-by-side vs Thanos Query
POST _query { "query": "TS <stream> | WHERE @timestamp >= \"...\" | STATS SUM(RATE(<counter>)) BY labels.instance, TBUCKET(1 hour)" }
```

Compare sample counts against the block inventory and run 3–5 dashboard
PromQL queries against Thanos and Elastic for the same window. Sign off one
month (ideally the oldest, 1h-resolution month) before bulk-running the rest.

### 5. Full run

Loop step 3 across the remaining inventory. Monitor: bulk rejections
(`_nodes/stats/thread_pool.write`), hot-tier disk, and the loader's
`failed=` count (nonzero → stop and inspect stderr; first 5 errors are
printed).

### 6. Boundary check

Confirm the newest slice ends exactly at the live data floor (the
provisioner clamps this automatically) and that queries spanning the
boundary return continuous results.

### 7. Lifecycle

Attached backfill slices do not roll over, so apply lifecycle explicitly:
set the ILM policy on `backfill-*` (or move them directly) so history lands
on cold/frozen (searchable snapshots) — this is what makes retiring Thanos
cost-neutral. Optionally downsample older slices in Elastic to match the
Thanos 5m/1h scheme going forward.

### 8. Decommission Thanos

1. Point Grafana datasources at Elastic (PromQL endpoint); burn-in period.
2. Retire queriers, store gateways, compactor, receive/sidecars, ruler.
3. **Keep the S3 bucket** (lifecycle it to Glacier if desired) for 6–12
   months as the rollback artifact — near-zero cost, total insurance.

## Rollback

Nothing in this procedure mutates Thanos data. At any point: repoint Grafana
back at Thanos Query, restart store gateways against the untouched bucket.
On the Elastic side, a bad backfill month is removed surgically:
`DELETE backfill-<stream>-YYYY.MM` detaches and drops just that slice.

## Known limits / open items

- **Serverless**: recipe unvalidated there (index-setting restrictions).
- Histograms: classic Prometheus histograms migrate as their component
  `_bucket`/`_sum`/`_count` counter series (this transform handles that
  naturally); native histograms would need mapping work.
- `_data_stream/_modify` and slice deletion are cluster-admin-ish
  operations — keep the migration API key separate from app keys and revoke
  it when done.

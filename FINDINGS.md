# Backfilling 12 months of Thanos/Prometheus history into an Elastic TSDS — verified findings

**Tested on:** Elasticsearch **9.1.3 and 9.5.3** (single-node Docker), 2026-09-04. Every test produced identical behavior on both versions; see [version matrix](#version-matrix-913-vs-953) for the one improvement 9.5 adds.
**PoC scripts:** [`poc/provision_slices.py`](poc/provision_slices.py), [`poc/load_samples.py`](poc/load_samples.py).
**Result:** 280,320 historical samples (8 series, 15-min resolution, Sep 2025 → Sep 2026) ingested into a live time series data stream at ~62k docs/s single-threaded, queryable as one continuous stream alongside live data, with fully idempotent re-runs.

## The problem (reproduced, not theoretical)

A TSDS only accepts writes inside a narrow window around *now*
(`look_back_time`, default 2h, max 7d + `look_ahead_time` 30m). Sending a
12-month-old sample at the data stream fails hard:

```
400 timestamp_error: the document timestamp [2025-09-04T12:00:00.000Z] is outside
of ranges of currently writable indices [[2026-09-04T07:15:25Z, 2026-09-04T09:45:25Z]]
```

So neither the Prometheus remote_write endpoint nor a naive bulk load can ever
backfill history. The writable window cannot be widened enough to matter.

## The recipe that works (all steps verified)

1. **Pre-create one `time_series`-mode index per historical time slice** (we
   used calendar months) with explicit bounds:
   `index.time_series.start_time` / `index.time_series.end_time`, plus
   `index.mode: time_series` and — **required for manually created indices,
   unlike template-created ones** — `index.routing_path` (e.g. `labels.*`).
   Clone mappings from the live data stream's write index so dimensions and
   metric types match exactly.

2. **Attach every slice to the live data stream** via
   `POST _data_stream/_modify` with `add_backing_index` — *before* loading
   data. Elasticsearch inserts each slice in correct time order automatically.

3. **Bulk-load everything through the data stream name** with
   `op_type: create`. TSDS routes each document to the slice covering its
   `@timestamp`. No per-index bookkeeping in the loader at all.

4. **Re-run on failure without dedup logic.** TSDS synthesizes `_id` from
   `_tsid` (dimensions hash) + `@timestamp`, so a resent sample returns
   `409 version conflict`. Treat 409 as success. Verified at full scale:
   replaying all 280,320 docs produced `created=0 duplicate=280320 failed=0`.

### Why attach-before-load (not load-then-attach)

Once an index becomes a backing index, direct `op_type=create` writes to it are
**rejected** (`index request with op_type=create targeting backing indices is
disallowed, target corresponding data stream`). But writes *via the data
stream* into attached historical slices work fine. So the simple, restartable
flow is: attach empty slices first, then fire all bulk traffic at the stream.

## Gotchas found during trial and error

| # | Finding | Consequence |
|---|---------|-------------|
| 1 | Manually created `time_series` indices fail without `index.routing_path` | Set it explicitly (`labels.*` for Prometheus-style label dimensions); templates infer it from mappings, manual creation does not |
| 2 | Overlapping backing-index time ranges are rejected at attach time | Slice bounds must be exactly contiguous: `[month-start, next-month-start)`. The provisioning script computes these; never hand-author them |
| 3 | The newest slice must not overlap the live write index's `start_time` | `provision_slices.py` clamps the last slice's `end_time` to the earliest live `.ds-*` `start_time`. Any gap between "history ends" and "live shipping began" is unrecoverable through the stream — **start live remote_write ingestion *before* running the backfill** so history can butt up against it |
| 4 | Backing indices are hidden | Use `expand_wildcards=all` for `_cat`/monitoring during migration |
| 5 | `counter_double` fields reject plain aggregations (`MAX`, etc.) in ES|QL — on both 9.1 and 9.5 | Expected TSDS semantics — counters are for rate-style queries. On 9.5, `TS <stream> \| STATS SUM(RATE(counter))` works over backfilled data and returns exact rates (verified against known synthetic slopes) |
| 6 | Duplicate detection is per `_tsid`+timestamp | Two *different* values for the same series+timestamp: first one wins silently (409). Don't load raw and downsampled data covering the same time range for the same series |
| 7 | Labels not in the static mappings are rejected: `All fields that match routing_path must be configured with [time_series_dimension: true]` | Real Prometheus data has per-metric label sets (`cpu`, `mode`, …). Mappings **must** include a `dynamic_templates` rule mapping `labels.*` → keyword + `time_series_dimension: true` (verified fix on 9.5.3; the official Prometheus integration does this out of the box). The provisioner clones mappings from the write index, so fixing the template propagates automatically |

## Verified end state

```
backfill-metrics-promtest.node-2025.09   23,041   ← Sep 2025 (12 months old)
backfill-metrics-promtest.node-2025.10   23,808
...  (one slice per month, counts = days × 96 samples/day × 8 series, exact)
backfill-metrics-promtest.node-2026.08   23,808
.ds-metrics-promtest.node-2026.09.04-000001   1   ← live write index
```

One ES|QL query over the data stream returns a continuous monthly histogram
across all 13 indices — the consumer (Kibana, Grafana, PromQL) never knows the
history was backfilled.

## Performance

280k docs in 4.5s (~62k docs/s) through a single-threaded Python loader with
stdlib HTTP against a 1 GB-heap laptop container. The loader parallelizes
trivially per Thanos block / per month; on a real cluster expect ingest
capacity, not the client, to be the limit. For sizing: 12 months at Thanos
downsampled resolutions (raw ≤90d, 5m/1h beyond) keeps sample counts tractable
— mirror what Thanos actually serves for old ranges today.

## Version matrix: 9.1.3 vs 9.5.3

The full suite was re-run from scratch against 9.5.3 (fresh container, port 9201):

| Test | 9.1.3 | 9.5.3 |
|------|-------|-------|
| Naive old-timestamp write → `timestamp_error` | ✅ rejected | ✅ identical |
| Manual `time_series` index requires `routing_path` | ✅ | ✅ identical |
| Slice provisioning + attach (`_data_stream/_modify`) | ✅ | ✅ identical |
| Overlapping slice rejected at attach | ✅ | ✅ identical |
| Old-timestamp write **via data stream** after attach → routed to slice | ✅ 201 | ✅ 201 |
| Duplicate sample → 409 (idempotent replay) | ✅ | ✅ |
| Direct `create` to attached backing index → disallowed | ✅ | ✅ |
| 280k scale load / full replay (`created=0 duplicate=280320 failed=0`) | ✅ ~62k docs/s | ✅ ~61k docs/s |
| Per-slice routing counts exact, ES|QL monthly continuity | ✅ | ✅ |
| Plain `MAX()` on `counter_double` | ❌ rejected | ❌ rejected (by design) |
| **`TS` command + `RATE()`/`TBUCKET()` over backfilled counters** | not tested | ✅ **works, rates numerically exact** |

Takeaway: the recipe is stable across the 9.x line, and 9.5's time-series
ES|QL (`TS` + `RATE`) correctly computes rates from *backfilled* counter data
— early evidence for `rate()` parity, though a real-data comparison against
Thanos results is still the definitive check.

## Elasticsearch 9.5+: automated backfill supersedes the manual recipe

**Verified 2026-09-07 on 9.5.3 (fresh container).** ES 9.5 ships a GA
automated-backfill feature ([PR #152716](https://github.com/elastic/elasticsearch/pull/152716))
that creates past backing indices on demand. Note: the
[announcement blog](https://www.elastic.co/search-labs/blog/time-series-data-backfill)
quotes a **wrong setting name** — the real ones (from source + official docs) are:

```jsonc
PUT _cluster/settings
{
  "persistent": {
    "data_stream.past_tsdb_index_creation_enabled": true,   // default false
    "data_streams.past_tsdb_index_interval": "7d"           // default 1d, range [1h, 7d]
  }
}
```

With this enabled, **the entire manual slice recipe becomes unnecessary**:

| Verified on 9.5.3 | Result |
|---|---|
| Naive 12-month-old write at the data stream | ✅ accepted; past backing index created + attached atomically |
| 280k-sample year, zero provisioning | ✅ `failed=0` at ~35k docs/s (vs ~60k with pre-provisioned slices — on-demand creation overhead) |
| Backing indices created (7d interval) | 56 weekly indices (vs 12 monthly manual slices — more shards, plan accordingly) |
| Full idempotent replay | ✅ `created=0 duplicate=280320 failed=0` — same 409 semantics |
| Monthly ES\|QL continuity | ✅ identical counts to the manual recipe |
| ILM | ✅ auto-created indices get `index.lifecycle.origination_date` = their `end_time`, so lifecycle ages history correctly — a manual-recipe caveat solved for free |
| Gotcha #7 (dynamic label dimensions) | ⚠️ still applies — the index template drives auto-created indices |

Per the official settings reference, both settings are **GA on Serverless**
— resolving the manual recipe's biggest open item (it relied on index-level
settings Serverless restricts).

**Decision rule: on 9.5+, use the automated path. Keep the manual slice
recipe (provision_slices.py) only for clusters that cannot upgrade past 9.4.**

## Prometheus remote_write endpoint accepts historical data too (verified)

ES 9.5's native remote_write endpoint (`POST /_prometheus/api/v1/write`,
enabled by default via `xpack.prometheus.enabled`) was probed with
[`poc/remote_write_probe.py`](poc/remote_write_probe.py) (hand-encoded
protobuf; snappy is optional on this endpoint, so stdlib-only works):

- Current-time sample → HTTP 204; data stream `metrics-generic.prometheus-default` auto-created
- **12-month-old sample → HTTP 204**; past backing index auto-created with correct 7d bounds
- Duplicate resend → **HTTP 400** "partially failed … CONFLICT" (no data
  corruption, count unchanged) — unlike the bulk path, remote_write replays
  are *reported as errors*, so a remote_write-based backfill replayer must
  tolerate partial-conflict 400s. **The bulk path remains the better loader.**

Native remote_write document schema (what live data will look like — the
backfill transform must match it so history and live data share one schema):

```json
{
  "@timestamp": 1756987200000,
  "data_stream": {"type": "metrics", "dataset": "generic.prometheus", "namespace": "default"},
  "labels": {"__name__": "test_rw_gauge", "instance": "host-9:9100", "job": "rwtest"},
  "metrics": {"test_rw_gauge": 0.77}
}
```

`metrics.*` is a `passthrough` object with metric fields auto-mapped
(`time_series_metric` typed); labels keep `__name__`. So for a customer using
native remote_write for live ingest, run `transform_dump.py --metric-root
metrics` and keep `__name__` as a label to mirror this schema exactly.

## Adapting from synthetic to real Thanos data

`load_samples.py --input file.ndjson` accepts one ES document per line. The
remaining work for production is the transform:

```
Thanos bucket (S3/GCS)
  └─ sync blocks per resolution (raw / 5m / 1h)
       └─ thanos-kit dump | promtool tsdb dump   → text samples
            └─ transform: labels → dimensions, metric → field, ts → @timestamp
                 └─ load_samples.py --input → data stream (slices pre-attached)
```

Keep slice provisioning aligned with the field schema of the **real** Elastic
Prometheus integration data streams (the PoC used a simplified schema; the
provisioner clones mappings from the live write index, so it adapts
automatically once the real integration is installed).

## Open items for the customer engagement

- Confirm the target is **Elastic Cloud Hosted / self-managed**. Serverless
  restricts index-level settings; this recipe's `_data_stream/_modify` +
  explicit `time_series.start_time` approach needs validation there.
- ILM: attached backfill slices don't inherit the stream's ILM policy
  automatically the same way rolled-over indices do — set the policy (or move
  them straight to cold/frozen) explicitly after attach.
- Validate `rate()`/`increase()` parity between Thanos and Elastic PromQL on a
  migrated month before bulk-running the remaining eleven (counter resets,
  staleness markers).
- Cardinality audit first: `thanos tools bucket inspect` — 12 months of series
  churn drives both slice mapping size and dimension limits.

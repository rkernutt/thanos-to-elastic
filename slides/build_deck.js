// Thanos -> Elastic migration deck (before / during / after)
const pptxgen = require("pptxgenjs");

const C = {
  blue: "0B64DD",      // Elastic Blue
  midnight: "153385",
  dev: "101C3F",       // Developer Blue (dark bg)
  teal: "48EFCF",
  yellow: "FEC514",
  ink: "1C1E23",
  pink: "F04E98",
  fog: "DCE2EA",
  grey: "F5F7FA",
  white: "FFFFFF",
};
const FONT = "Arial";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

// ---------- helpers (fresh option objects every call) ----------
function node(slide, x, y, w, h, text, opts = {}) {
  slide.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.07,
    fill: { color: opts.fill || C.white },
    line: { color: opts.line || C.midnight, width: opts.lineW ?? 1 },
    shadow: opts.flat ? undefined : { type: "outer", color: "AAB4C4", blur: 6, offset: 2, angle: 90, opacity: 0.35 },
  });
  slide.addText(text, {
    x, y, w, h, isTextBox: true, margin: 0.04,
    align: "center", valign: "middle",
    fontFace: FONT, fontSize: opts.size || 11, bold: opts.bold ?? true,
    color: opts.color || C.ink,
  });
}
function arrow(slide, x, y, w, h, opts = {}) {
  slide.addShape("line", {
    x, y, w, h,
    line: { color: opts.color || C.midnight, width: opts.width || 2, endArrowType: "triangle", ...(opts.dash ? { dashType: "dash" } : {}) },
    flipH: opts.flipH || false, flipV: opts.flipV || false,
  });
}
function label(slide, x, y, w, text, opts = {}) {
  slide.addText(text, {
    x, y, w, h: opts.h || 0.3, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: opts.size || 10, italic: opts.italic ?? true,
    color: opts.color || C.midnight, align: opts.align || "left", bold: opts.bold || false,
  });
}
function title(slide, kicker, text, dark = false) {
  slide.addText(kicker, {
    x: 0.6, y: 0.32, w: 12.1, h: 0.32, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 13, bold: true, charSpacing: 2,
    color: dark ? C.teal : C.blue,
  });
  slide.addText(text, {
    x: 0.6, y: 0.62, w: 12.1, h: 0.75, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 32, bold: true, color: dark ? C.white : C.ink,
  });
}
function card(slide, x, y, w, h, dotColor, head, body, opts = {}) {
  slide.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.09,
    fill: { color: opts.fill || C.grey },
    line: { color: opts.lineC || C.fog, width: 0.75 },
  });
  slide.addShape("ellipse", { x: x + 0.22, y: y + 0.22, w: 0.34, h: 0.34, fill: { color: dotColor }, line: { type: "none" } });
  slide.addText(opts.glyph || "", {
    x: x + 0.22, y: y + 0.22, w: 0.34, h: 0.34, isTextBox: true, margin: 0,
    align: "center", valign: "middle", fontFace: FONT, fontSize: 13, bold: true, color: opts.glyphColor || C.white,
  });
  slide.addText(head, {
    x: x + 0.68, y: y + 0.16, w: w - 0.85, h: 0.45, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 13, bold: true, color: opts.headColor || C.ink, valign: "middle",
  });
  slide.addText(body, {
    x: x + 0.68, y: y + 0.58, w: w - 0.85, h: h - 0.72, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 11, color: opts.bodyColor || "3A4354", valign: "top",
  });
}

// ================= SLIDE 1 — title =================
{
  const s = pres.addSlide();
  s.background = { color: C.dev };
  // motif: faint node cluster right side
  const ghosts = [
    [9.4, 1.1, 2.6, 0.6], [10.2, 2.1, 2.4, 0.6], [9.0, 3.1, 2.2, 0.6],
    [10.5, 4.1, 2.3, 0.6], [9.3, 5.1, 2.6, 0.6], [10.1, 6.1, 2.2, 0.6],
  ];
  for (const [x, y, w, h] of ghosts) {
    s.addShape("roundRect", { x, y, w, h, rectRadius: 0.07, fill: { color: C.midnight, transparency: 45 }, line: { color: C.blue, width: 0.75, transparency: 30 } });
  }
  s.addText("Elastic Observability", {
    x: 0.7, y: 1.7, w: 7.5, h: 0.4, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 15, bold: true, charSpacing: 2, color: C.teal,
  });
  s.addText("One home for metrics, logs, and traces", {
    x: 0.7, y: 2.15, w: 8.2, h: 1.9, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 44, bold: true, color: C.white,
  });
  s.addText("Migrating 12 months of Prometheus history out of Thanos — and retiring the infrastructure that held it", {
    x: 0.7, y: 4.15, w: 7.6, h: 0.95, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 18, color: C.fog,
  });
  s.addText("Before  ·  During  ·  After", {
    x: 0.7, y: 5.5, w: 6, h: 0.4, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 15, bold: true, color: C.yellow,
  });
  s.addText("Elastic — the Search AI Company", {
    x: 0.7, y: 6.75, w: 6, h: 0.35, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 11, color: "8FA3C8",
  });
  s.addNotes("Frame: the customer already runs Elastic for logs and APM. This is about bringing metrics home, unlocking correlation, and paying for one platform instead of two. Everything on these slides is verified in the repo (FINDINGS.md).");
}

// ================= SLIDE 2 — BEFORE =================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  title(s, "BEFORE", "Two platforms, split signals");

  // Grafana on top
  node(s, 2.0, 1.7, 3.4, 0.55, "Grafana (PromQL + Elastic queries)", { fill: C.fog, size: 11 });
  // Prometheus
  node(s, 0.6, 2.9, 1.9, 0.6, "Prometheus", { fill: C.white });
  // Thanos container
  s.addShape("roundRect", { x: 0.6, y: 3.9, w: 4.4, h: 2.1, rectRadius: 0.09, fill: { color: C.grey }, line: { color: C.pink, width: 1.25 } });
  label(s, 0.8, 4.0, 3.5, "Thanos — dedicated long-term metrics infra", { color: C.pink, bold: true, italic: false, size: 10.5 });
  node(s, 0.85, 4.45, 1.85, 0.55, "Sidecar / Receive", { flat: true, size: 10, bold: false });
  node(s, 2.9, 4.45, 1.85, 0.55, "Querier", { flat: true, size: 10, bold: false });
  node(s, 0.85, 5.25, 1.85, 0.55, "Compactor", { flat: true, size: 10, bold: false });
  node(s, 2.9, 5.25, 1.85, 0.55, "Store gateway", { flat: true, size: 10, bold: false });
  // S3
  node(s, 0.6, 6.5, 2.5, 0.6, "Object store (S3)\n12 mo of TSDB blocks", { fill: C.fog, size: 9.5, bold: false });
  // Elastic
  node(s, 5.6, 4.2, 2.5, 1.5, "Elastic\nlogs + APM traces", { fill: C.blue, color: C.white, size: 13 });
  // arrows
  arrow(s, 1.55, 3.5, 0, 0.4);                    // prometheus -> thanos
  arrow(s, 1.85, 6.1, 0, 0.4);                    // thanos -> s3 (compactor down)
  arrow(s, 2.8, 2.25, 0, 1.6);                    // grafana -> thanos container
  arrow(s, 4.6, 2.25, 2.0, 1.95);                 // grafana -> elastic
  label(s, 5.75, 3.05, 2.4, "logs + traces only", { size: 9 });

  // pain cards
  card(s, 8.6, 1.7, 4.15, 1.5, C.pink, "Twice the infrastructure", "Queriers, store gateways, compactors, and receivers to run, patch, and pay for — alongside Elastic.", { glyph: "×" });
  card(s, 8.6, 3.4, 4.15, 1.5, C.pink, "No correlation", "A latency spike in metrics can't be lined up with the logs and traces that explain it.", { glyph: "×" });
  card(s, 8.6, 5.1, 4.15, 1.5, C.pink, "History locked in", "12 months of retention lives in Thanos — the reason it can't simply be switched off.", { glyph: "×" });
  s.addNotes("Current state: Prometheus scrapes, Thanos provides HA + long-term retention in S3. Grafana queries two backends. The 12 months of history is the anchor keeping Thanos alive.");
}

// ================= SLIDE 3 — DURING =================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  title(s, "DURING", "Live cutover first, then backfill the history");

  // Lane 1: live
  label(s, 0.6, 1.62, 6, "1 — Day one: live metrics cut over", { bold: true, italic: false, size: 12, color: C.blue });
  node(s, 0.6, 2.0, 1.9, 0.6, "Prometheus", { fill: C.white });
  node(s, 4.3, 1.95, 4.4, 0.7, "Elastic time series data streams", { fill: C.blue, color: C.white, size: 12 });
  arrow(s, 2.5, 2.3, 1.8, 0, { color: C.blue, width: 2.5 });
  label(s, 2.55, 1.98, 1.8, "remote_write", { size: 9.5, align: "center" });
  label(s, 4.35, 2.72, 4.2, "PromQL keeps working — dashboards unchanged", { size: 9.5 });

  // Lane 2: backfill
  label(s, 0.6, 3.35, 8, "2 — Historical backfill: straight from the bucket (Thanos is not in the data path)", { bold: true, italic: false, size: 12, color: C.blue });
  node(s, 0.6, 3.75, 2.0, 0.85, "Object store\n(S3 / GCS / Azure)", { fill: C.fog, size: 10, bold: false });
  node(s, 3.15, 3.75, 1.7, 0.85, "Export worker\ndump blocks", { size: 10, bold: false });
  node(s, 5.35, 3.75, 1.7, 0.85, "Transform\nlabels → dimensions", { size: 10, bold: false });
  node(s, 7.55, 3.75, 1.7, 0.85, "Bulk load\nidempotent", { size: 10, bold: false });
  arrow(s, 2.6, 4.17, 0.55, 0);
  arrow(s, 4.85, 4.17, 0.5, 0);
  arrow(s, 7.05, 4.17, 0.5, 0);
  // bulk load -> ES stream (arrowhead at the top / ES end)
  s.addShape("line", { x: 8.4, y: 2.7, w: 0, h: 1.0, line: { color: C.blue, width: 2.5, beginArrowType: "triangle" } });
  label(s, 0.6, 4.75, 8.6, "Elasticsearch 9.5 creates the historical indices automatically as year-old samples arrive — no manual index management", { size: 10 });

  // frozen compactor chip
  s.addShape("roundRect", { x: 0.6, y: 5.35, w: 4.5, h: 0.55, rectRadius: 0.09, fill: { color: C.white }, line: { color: C.pink, width: 1.25 } });
  s.addText("Thanos compactor stopped — bucket is immutable during export", {
    x: 0.75, y: 5.35, w: 4.3, h: 0.55, isTextBox: true, margin: 0, valign: "middle",
    fontFace: FONT, fontSize: 10, bold: true, color: C.pink,
  });
  label(s, 0.6, 6.1, 8.4, "Every load is safely re-runnable: a crashed job is resumed by running it again — duplicates are detected, never doubled.", { size: 10.5, italic: false, color: "3A4354" });

  // proof cards right
  card(s, 9.35, 1.7, 3.4, 1.45, C.teal, "Query parity, proven", "Identical PromQL on Thanos and Elastic: gauges match exactly, rate() within 0.25%.", { glyph: "✓", glyphColor: C.dev });
  card(s, 9.35, 3.3, 3.4, 1.45, C.teal, "Predictable duration", "A typical 12-month estate (~20B samples) migrates in about a day and a half.", { glyph: "✓", glyphColor: C.dev });
  card(s, 9.35, 4.9, 3.4, 1.45, C.teal, "Zero-risk rollback", "The bucket is never modified — Grafana can point back at Thanos at any moment.", { glyph: "✓", glyphColor: C.dev });
  s.addNotes("Order matters: live shipping starts first so the retention clock starts and history butts up against it. Backfill reads TSDB blocks directly from object storage — no load on Thanos. Each month is verified with an automated parity gate (same PromQL to both systems) before the next is loaded.");
}

// ================= SLIDE 4 — AFTER =================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  title(s, "AFTER", "One platform, 12 months of unified history");

  // Grafana + Kibana on top
  node(s, 1.3, 1.75, 2.3, 0.55, "Grafana (PromQL)", { fill: C.fog, size: 11 });
  node(s, 3.9, 1.75, 2.3, 0.55, "Kibana (PromQL + ES|QL)", { fill: C.fog, size: 10.5 });
  // Prometheus -> Elastic platform
  node(s, 0.6, 3.1, 1.9, 0.6, "Prometheus", { fill: C.white });
  s.addShape("roundRect", { x: 3.1, y: 2.95, w: 4.6, h: 3.3, rectRadius: 0.09, fill: { color: C.blue }, line: { color: C.midnight, width: 1 } });
  s.addText("Elastic Observability", {
    x: 3.35, y: 3.1, w: 4.1, h: 0.4, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 14, bold: true, color: C.white,
  });
  node(s, 3.35, 3.6, 4.1, 0.6, "Metrics · logs · traces — correlated", { fill: C.midnight, color: C.white, size: 11, flat: true });
  node(s, 3.35, 4.35, 1.95, 0.55, "Hot: recent data", { fill: C.white, size: 10, bold: false, flat: true });
  node(s, 5.5, 4.35, 1.95, 0.55, "Frozen: history", { fill: C.white, size: 10, bold: false, flat: true });
  node(s, 3.35, 5.05, 4.1, 0.55, "12 months of metrics retention", { fill: C.teal, color: C.dev, size: 11, flat: true });
  label(s, 3.35, 5.75, 4.1, "compare this week to the same week last year — one PromQL query", { size: 9.5, color: C.white });
  arrow(s, 2.5, 3.4, 0.6, 0, { color: C.blue, width: 2.5 });
  arrow(s, 2.45, 2.3, 0.65, 0.75);   // grafana -> platform
  arrow(s, 5.05, 2.3, 0.3, 0.65);    // kibana -> platform

  // retired thanos
  s.addShape("roundRect", { x: 0.6, y: 4.6, w: 2.1, h: 1.65, rectRadius: 0.09, fill: { color: C.grey }, line: { color: "9AA6B8", width: 1, dashType: "dash" } });
  s.addText("Thanos compute\nretired", {
    x: 0.6, y: 4.75, w: 2.1, h: 0.75, isTextBox: true, margin: 0, align: "center",
    fontFace: FONT, fontSize: 11, bold: true, color: "8A93A3", strike: true,
  });
  s.addText("bucket kept 6–12 mo\nas rollback, then deleted", {
    x: 0.6, y: 5.5, w: 2.1, h: 0.6, isTextBox: true, margin: 0, align: "center",
    fontFace: FONT, fontSize: 9, color: "8A93A3",
  });

  // outcome cards
  card(s, 8.35, 1.7, 4.4, 1.5, C.teal, "Cost neutral", "Thanos queriers, store gateways, compactors, and receivers are gone; history ages on the frozen tier.", { glyph: "✓", glyphColor: C.dev });
  card(s, 8.35, 3.4, 4.4, 1.5, C.teal, "Nothing to relearn", "Dashboards and alerts keep their PromQL verbatim — Elastic answers the same query language natively.", { glyph: "✓", glyphColor: C.dev });
  card(s, 8.35, 5.1, 4.4, 1.5, C.teal, "Faster answers", "A metric spike, its logs, and the traces behind it — investigated in one place, not two.", { glyph: "✓", glyphColor: C.dev });
  s.addNotes("End state: single platform, single bill, single query surface. The S3 bucket stays for 6-12 months as a near-zero-cost rollback artifact, then gets deleted. Year-over-year PromQL works across the migrated history.");
}

// ================= SLIDE 5 — proof + next steps =================
{
  const s = pres.addSlide();
  s.background = { color: C.dev };
  title(s, "WHY WE'RE CONFIDENT", "Verified end to end — not a paper exercise", true);

  const stats = [
    ["Exact", "gauge values match Prometheus digit-for-digit after migration"],
    ["≤0.25%", "rate() divergence across every compared bucket — resets included"],
    ["0 lost", "every load is idempotent; failed runs are simply re-run"],
    ["~36 h", "typical 12-month estate (~20B samples) at standard ingest capacity"],
  ];
  stats.forEach(([big, small], i) => {
    const x = 0.6 + i * 3.1;
    s.addText(big, {
      x, y: 1.85, w: 2.9, h: 0.95, isTextBox: true, margin: 0,
      fontFace: FONT, fontSize: 40, bold: true, color: C.teal,
    });
    s.addText(small, {
      x, y: 2.8, w: 2.75, h: 1.15, isTextBox: true, margin: 0,
      fontFace: FONT, fontSize: 11.5, color: C.fog,
    });
  });

  s.addShape("line", { x: 0.6, y: 4.25, w: 12.1, h: 0, line: { color: C.midnight, width: 1 } });

  s.addText("Suggested next steps", {
    x: 0.6, y: 4.5, w: 6, h: 0.4, isTextBox: true, margin: 0,
    fontFace: FONT, fontSize: 16, bold: true, color: C.white,
  });
  const steps = [
    ["1", "Inventory the bucket", "One read-only command sizes the whole estate: exact sample counts, duration, and storage forecast."],
    ["2", "Pilot one month", "Migrate the oldest month and run the parity gate against your Thanos — sign off on real data."],
    ["3", "Full run, then retire", "Backfill the rest, flip Grafana, and switch the Thanos infrastructure off."],
  ];
  steps.forEach(([n, head, body], i) => {
    const x = 0.6 + i * 4.2;
    s.addShape("ellipse", { x, y: 5.1, w: 0.42, h: 0.42, fill: { color: C.yellow }, line: { type: "none" } });
    s.addText(n, { x, y: 5.1, w: 0.42, h: 0.42, isTextBox: true, margin: 0, align: "center", valign: "middle", fontFace: FONT, fontSize: 14, bold: true, color: C.dev });
    s.addText(head, { x: x + 0.58, y: 5.08, w: 3.4, h: 0.45, isTextBox: true, margin: 0, fontFace: FONT, fontSize: 14, bold: true, color: C.white, valign: "middle" });
    s.addText(body, { x: x + 0.58, y: 5.55, w: 3.4, h: 1.3, isTextBox: true, margin: 0, fontFace: FONT, fontSize: 10.5, color: C.fog });
  });
  s.addNotes("Numbers come from the migration kit's test evidence: PromQL parity harness (identical queries against real Prometheus and migrated Elastic data), full idempotency replays, and a calibrated throughput benchmark. Next step 1 is zero-risk: a read-only inventory command.");
}

pres.writeFile({ fileName: "slides/thanos-to-elastic-migration.pptx" }).then(() => console.log("written"));

// Bi-temporal e2e (R2 §2). Mirrors docs/redesign/demo_scenario.md §2.1–2.5:
// the query-delta highlight grammar, the timeline scrubber + AxisToggle
// T↔T′ re-sort, the edit→LatencyBadge+cascade ripple, the revert of an
// auto-invalidation, and the 409 stale-merge ErrorBanner.
//
// Design notes (shared with demo.spec.ts):
// - The @krainovsd/graph canvas captures keyboard focus on mount, so any
//   control that the canvas would otherwise eat keys for (timeline-toggle,
//   axis-toggle) is driven via the *visible button*, never page.keyboard.
// - We prefer asserting on the backend HTTP contract (waitForResponse /
//   page.evaluate fetch) over canvas pixel/hit-test reads to stay
//   deterministic; the DOM testids bind that contract to the UI surface.
// - Every temporal flow is gated on a seed field so an older backend
//   (no ingestion-events endpoint) test.skips instead of failing.

import { test, expect, type Page, type Response } from "@playwright/test";

import { seed, type SeedResult } from "./lib/seed";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
// Curation actor identity the UI write layer stamps. Overridable so CI
// can match whatever account the frontend is signed in as.
const USER_EMAIL = process.env.E2E_USER_EMAIL ?? "seggei075806@gmail.com";

let fixture: SeedResult;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  fixture = await seed(BACKEND);
});

// The graph page auto-starts a one-shot guided tour (§2.6) on first visit
// (localStorage 'gr:walkthrough:seen' unset). Its full-screen spotlight
// overlay intercepts clicks, which would block the curation surfaces these
// temporal flows drive. Mark the tour as already seen before any page
// script runs so it stays dismissed. (The tour itself is exercised by its
// own §2.6 spec.)
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("gr:walkthrough:seen", "1");
    } catch {
      /* storage disabled — non-fatal */
    }
  });
});

async function gotoAndSettle(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

async function readVersion(page: Page): Promise<number> {
  const txt = await page.getByText(/^v\d+$/).first().innerText();
  return Number(txt.replace(/^v/, ""));
}

// ---------------------------------------------------------------------
// §2.2 query-delta highlight lights evidence and dims complement
// ---------------------------------------------------------------------
test("§2.2 query-delta highlight lights evidence and dims complement", async ({
  page,
}) => {
  test.skip(!fixture.variant_leiden_id, "no leiden variant seeded");

  // Walk the ask wizard in *single* mode: the query-delta highlight
  // grammar (§0/§2.2) is a single-variant "evidence vs complement" split,
  // so one variant is all this asserts. (MoE mode would gate the wizard on
  // ≥2 variants — a different flow tested in demo.spec.) Steps:
  // mode → variants → strategy → query → results.
  await gotoAndSettle(page, "/wizards/ask");

  // Step 0 — mode. Single is the default, but click it to be explicit and
  // to satisfy `canAdvance` (mode set).
  await page.getByText("Single", { exact: true }).click();
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // Step 1 — variants. Pick the leiden variant (one is enough for single).
  const leidenRow = page.locator("li", {
    hasText: fixture.variant_leiden_name,
  });
  await expect(leidenRow).toBeVisible({ timeout: 15_000 });
  await leidenRow.click();
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // Step 2 — strategy. The wizard preloads defaults (keyword_search /
  // evidence_union) which already satisfy `canAdvance`, so just advance.
  await expect(page.getByRole("heading", { name: "Reasoner" })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // Step 3 — query.
  await page.locator("textarea").fill(fixture.moe_query);
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // Step 4 — results. "Спросить" streams the answer over SSE; the delta
  // call (POST /api/reason/delta) fires from the "Показать на графе" CTA,
  // which only appears once an answer has rendered. Run the ask first.
  await page
    .getByRole("main")
    .getByRole("button", { name: "Спросить", exact: true })
    .click();

  // Wait for the answer block + the show-on-graph CTA to surface.
  const showOnGraph = page.getByTestId("results-show-on-graph");
  await expect(showOnGraph).toBeVisible({ timeout: 45_000 });

  // Intercept the delta call fired by the show-on-graph CTA.
  const deltaPromise = page.waitForResponse(
    (resp: Response) =>
      resp.url().includes("/api/reason/delta") && resp.request().method() === "POST",
    { timeout: 45_000 },
  );

  await showOnGraph.click();

  const deltaResp = await deltaPromise;
  expect(deltaResp.ok()).toBeTruthy();
  const body = (await deltaResp.json()) as {
    evidence_node_ids: string[];
    total_node_ids: string[];
  };

  // The delta is a strict, non-empty subset of the variant — "what was
  // used vs not". This is the §0 grammar contract the legend explains.
  expect(body.evidence_node_ids.length).toBeGreaterThan(0);
  expect(body.evidence_node_ids.length).toBeLessThan(
    body.total_node_ids.length,
  );

  // The show-on-graph CTA navigated to /graphs/{id}?queryDelta=1; the
  // canvas mounts and the legend that explains the grammar is visible.
  await expect(page).toHaveURL(/\/graphs\/[^/?]+\?.*queryDelta=1/, {
    timeout: 20_000,
  });
  await expect(page.getByTestId("graph-canvas")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByTestId("delta-legend")).toBeVisible({
    timeout: 20_000,
  });
});

// ---------------------------------------------------------------------
// §2.1 timeline scrub compresses graph + AxisToggle re-sorts
// ---------------------------------------------------------------------
test("§2.1 timeline scrub compresses graph + AxisToggle re-sorts (buttons, not keys)", async ({
  page,
}) => {
  test.skip(
    fixture.episode_events.length === 0,
    "no ingestion-events endpoint",
  );

  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);

  // The canvas eats keys → use the visible Time button, never keyboard.
  await page.getByTestId("timeline-toggle").click();
  await expect(page.getByTestId("graph-canvas")).toBeVisible();

  // (1) Compression. Assert on the /at API (deterministic) rather than DOM
  // node count: an instant *before* the first ingest (tx_pre) materializes
  // an empty graph, while tx_b (after the last ingest) materializes the
  // full one — the temporal window compresses the visible graph. (tx_a sits
  // after the first ingest where the backend has already stamped every
  // node's tx_from, so tx_a..tx_b alone would NOT compress — that pair is
  // reserved for §2.4's invalidation diff.)
  const atPre = await getMaterialized(page, fixture.tx_pre!, "tx");
  const atTxB = await getMaterialized(page, fixture.tx_b!, "tx");
  expect(atPre.node_ids.length).toBeLessThan(atTxB.node_ids.length);

  // (2) Axis re-sort. The scrubber lays its episode ticks out by axis time
  // (axis=tx → ingested_at, axis=valid → event_time). Capture the tick
  // order *by rendered position* under axis=tx, click the AxisToggle
  // (T′↔T), and expect the order under axis=valid to DIFFER — the
  // back-dated Эпизод 3 (published 3rd, ingested last) moves.
  const orderTx = await scrubberTickOrder(page);
  expect(orderTx.length).toBeGreaterThan(2);

  // Default axis is T′ (tx). Click the T (valid / event-time) segment of
  // the AxisToggle. The scrubber re-sorts client-side off the same events
  // (no network fetch — it just reads event_time instead of ingested_at).
  await page
    .getByTestId("axis-toggle")
    .getByRole("button", { name: /T \(/ })
    .click();
  // Let the re-render settle so tick positions reflect the new axis.
  await page.waitForTimeout(300);

  const orderValid = await scrubberTickOrder(page);
  expect(orderValid).not.toEqual(orderTx);
});

// ---------------------------------------------------------------------
// §2.3 edit → LatencyBadge numeric ms + tier + cascade ripple
// ---------------------------------------------------------------------
test("§2.3 edit → LatencyBadge shows numeric ms + tier + cascade ripple", async ({
  page,
}) => {
  test.skip(!fixture.variant_leiden_id, "no leiden variant seeded");

  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);

  // The suggestions sidebar Accept is the demo-stable write surface (§5).
  await page
    .getByRole("button", { name: /Показать Suggestions/ })
    .click();
  const sidebar = page.getByTestId("suggestions-sidebar");
  await expect(sidebar).toBeVisible();

  const accept = page.getByTestId("suggestion-accept").first();
  test.skip(
    !(await accept.isVisible({ timeout: 5_000 }).catch(() => false)),
    "no pending suggestion to accept",
  );

  // The Accept write surface is POST /api/suggestions/{id}/accept, which
  // returns a JournalAppendResult (recompute_ms, affected, variant). A
  // direct journal append (/journal) carries the same shape — accept both.
  const journalPromise = page.waitForResponse(
    (resp: Response) =>
      /\/(journal|suggestions\/[^/]+\/accept)\b/.test(resp.url()) &&
      resp.request().method() === "POST",
    { timeout: 20_000 },
  );

  await accept.click();

  // Backend contract: recompute_ms is a finite, non-negative number.
  const journalResp = await journalPromise;
  expect(journalResp.ok()).toBeTruthy();
  const journalBody = (await journalResp.json()) as { recompute_ms: number };
  expect(Number.isFinite(journalBody.recompute_ms)).toBe(true);
  expect(journalBody.recompute_ms).toBeGreaterThanOrEqual(0);

  // Latency badge appears transiently with numeric ms + a valid tier.
  const badge = page.getByTestId("latency-badge").first();
  await expect(badge).toBeVisible({ timeout: 10_000 });

  // Numeric ms + the unit (localized: "ms" in en, "мс" under ru-RU).
  const badgeText = (await badge.innerText()).trim();
  expect(badgeText).toMatch(/\d+(\.\d+)?\s*(ms|мс)/);

  const tier = await badge.getAttribute("data-tier");
  expect(["fast", "mid", "slow"]).toContain(tier);

  // The rendered ms matches the contract value within rounding tolerance.
  // The badge rounds for display (1 decimal under 10ms, whole ms above), so
  // a tolerance of 1 covers the rounding of any recompute_ms.
  const renderedMs = Number(badgeText.match(/(\d+(?:\.\d+)?)\s*(?:ms|мс)/)?.[1]);
  expect(Math.abs(renderedMs - journalBody.recompute_ms)).toBeLessThanOrEqual(1);

  // The cascade ripple ran: data-source='edit' marker appears then clears.
  const cascade = page.getByTestId("edit-cascade");
  await expect(cascade).toHaveAttribute("data-source", "edit", {
    timeout: 5_000,
  });
  await expect(cascade).toBeHidden({ timeout: 3_000 });

  // Badge transitions shown → faded.
  await expect
    .poll(async () => badge.getAttribute("data-state").catch(() => null), {
      timeout: 5_000,
    })
    .toBe("faded");
});

// ---------------------------------------------------------------------
// §2.4 revert auto-invalidation removes the row and re-adds the edge
// ---------------------------------------------------------------------
test("§2.4 revert auto-invalidation removes the row and re-adds the edge", async ({
  page,
}) => {
  test.skip(!fixture.invalidated_edge_id, "no seeded invalidation");

  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);

  // The invalidation-panel only mounts in DIFF mode when the diff window
  // has invalidated edges. Open the temporal view, switch to Диф (diff),
  // then click the scrubber track near its left edge — that emits a
  // [t_a, t_b] range spanning the events (handle B stays at the max), which
  // the host turns into GET .../diff. The auto-invalidated edge (alive at
  // the first ingest, dead by the last) lands in diff.invalidated. Drive
  // visible controls only (the canvas eats keys).
  await page.getByTestId("timeline-toggle").click();
  await expect(page.getByTestId("graph-canvas")).toBeVisible();

  await page.getByRole("button", { name: "Диф", exact: true }).click();

  // Emit the diff range by clicking the track near its left edge so handle
  // A moves to ~min while handle B stays at ~max → widest window.
  const track = page.getByTestId("timeline-track");
  await expect(track).toBeVisible({ timeout: 10_000 });
  const box = await track.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.click(box!.x + 4, box!.y + box!.height / 2);

  // The diff fetch carries the range; wait for it before asserting panel.
  await page.waitForResponse(
    (resp: Response) => /\/api\/graphs\/[^/]+\/diff\b/.test(resp.url()),
    { timeout: 15_000 },
  );

  const panel = page.getByTestId("invalidation-panel");
  await expect(panel).toBeVisible({ timeout: 15_000 });

  const row = page.locator(
    `[data-testid="invalidation-row"][data-edge-id="${fixture.invalidated_edge_id}"]`,
  );
  await expect(row).toBeVisible();
  // Provenance text — the reason carried by the auto-invalidation.
  await expect(row).toContainText(/superseded by Эпизод 3/);

  // The revert is an optimistic-concurrency write: it must carry the
  // variant's CURRENT version as expected_version. Read it live (prior
  // tests in this serial suite share backend state and may have advanced
  // it past the seed-time invalidated_edge_version), so we assert against
  // the live version rather than a stale constant — but never below the
  // version at which the auto-invalidation landed.
  const liveVersion = (
    await getJson<{ version: number }>(
      page,
      `${BACKEND}/api/graphs/${fixture.variant_leiden_id}`,
    )
  ).version;

  const revertPromise = page.waitForResponse(
    (resp: Response) =>
      resp
        .url()
        .includes(
          `/invalidations/${fixture.invalidated_edge_id}/revert`,
        ) && resp.request().method() === "POST",
    { timeout: 20_000 },
  );

  await row.getByTestId("invalidation-revert").click();

  const revertResp = await revertPromise;
  expect(revertResp.status()).toBe(200);
  const reqBody = revertResp.request().postDataJSON() as {
    expected_version: number;
    actor: string;
  };
  expect(reqBody.expected_version).toBe(liveVersion);
  expect(reqBody.expected_version).toBeGreaterThanOrEqual(
    fixture.invalidated_edge_version!,
  );
  expect(reqBody.actor).toMatch(/^user:/);

  // The row for that edge is removed.
  await expect(row).toBeHidden({ timeout: 10_000 });

  // Revert is a journal write → a latency badge surfaces (per contract).
  await expect(page.getByTestId("latency-badge").first()).toBeVisible({
    timeout: 10_000,
  });

  // Cross-check: the edge is no longer in the invalidated bucket.
  const diff = await getJson<{ invalidated?: Array<{ id: string }> }>(
    page,
    `${BACKEND}/api/graphs/${fixture.variant_leiden_id}/diff?t_a=${encodeURIComponent(
      fixture.tx_a!,
    )}&t_b=${encodeURIComponent(fixture.tx_b!)}&axis=tx`,
  );
  const stillInvalidated = (diff.invalidated ?? []).some(
    (e) => e.id === fixture.invalidated_edge_id,
  );
  expect(stillInvalidated).toBe(false);
});

// ---------------------------------------------------------------------
// §2.5 ErrorBanner on forced 409 stale-merge
// ---------------------------------------------------------------------
test("§2.5 ErrorBanner on forced 409 stale-merge", async ({ page }) => {
  test.skip(!fixture.variant_leiden_id, "no leiden variant seeded");

  // Watch for any uncaught page error — a 409 must surface as a visible
  // banner, never a silent crash.
  const pageErrors: Error[] = [];
  page.on("pageerror", (err) => pageErrors.push(err));

  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);

  // We need ≥2 pending suggestions: one to bump the backend version
  // out-of-band (so the page's in-memory `variant.version` goes stale),
  // and one to Accept *through the UI* at that now-stale version → the
  // backend rejects it 409 and the SuggestionsSidebar surfaces the
  // ErrorBanner. (Driving the 409 through the UI is the whole point — a
  // raw fetch would never render the banner.)
  const pending = await getJson<Array<{ id: string }>>(
    page,
    `${BACKEND}/api/graphs/${fixture.variant_leiden_id}/suggestions?status=pending`,
  );
  test.skip(pending.length < 2, "need >=2 pending suggestions to force a 409");

  // Open the sidebar so the UI holds the current (soon-to-be-stale)
  // variant.version.
  await page
    .getByRole("button", { name: /Показать Suggestions/ })
    .click();
  await expect(page.getByTestId("suggestions-sidebar")).toBeVisible();

  const staleVersion = await readVersion(page).catch(async () => {
    const v = await getJson<{ version: number }>(
      page,
      `${BACKEND}/api/graphs/${fixture.variant_leiden_id}`,
    );
    return v.version;
  });

  // Out-of-band bump: accept a DIFFERENT suggestion straight against the
  // backend at expected_version=staleVersion → backend advances to v+1.
  // The page never learns about this, so its variant.version stays stale.
  const bumpStatus = await page.evaluate(
    async ([backend, sid, v, email]) => {
      const resp = await fetch(`${backend}/api/suggestions/${sid}/accept`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          expected_variant_version: v,
          actor: `user:${email}`,
        }),
      });
      return resp.status;
    },
    [BACKEND, pending[pending.length - 1].id, staleVersion, USER_EMAIL] as const,
  );
  expect(bumpStatus).toBe(200);

  // Now Accept the FIRST suggestion through the UI. The sidebar still
  // believes the variant is at staleVersion, so its accept carries the
  // stale expected_variant_version → backend 409 → ErrorBanner.
  const acceptResp = page.waitForResponse(
    (resp: Response) =>
      /\/suggestions\/[^/]+\/accept\b/.test(resp.url()) &&
      resp.request().method() === "POST",
    { timeout: 15_000 },
  );
  await page.getByTestId("suggestion-accept").first().click();
  const resp = await acceptResp;
  expect(resp.status()).toBe(409);

  // The banner is visible, scoped to the 409, role=alert, and explains
  // what happened + what to do (non-empty, not a raw stack).
  const banner = page.getByTestId("error-banner").first();
  await expect(banner).toBeVisible({ timeout: 10_000 });
  await expect(banner).toHaveAttribute("role", "alert");
  await expect(banner).toHaveAttribute("data-status", "409");
  const bannerText = (await banner.innerText()).trim();
  expect(bannerText.length).toBeGreaterThan(0);
  expect(bannerText).not.toMatch(/at\s+\w+\.<anonymous>|\.ts:\d+:\d+/);

  // No silent crash.
  expect(pageErrors).toHaveLength(0);
});

// ---------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------

// Reads the materialized state at instant `t` under `axis` via the API,
// using the page's request context (shares baseURL/headers/cookies).
async function getMaterialized(
  page: Page,
  t: string,
  axis: "tx" | "valid",
): Promise<{ node_ids: string[]; edge_ids: string[] }> {
  const url = `${BACKEND}/api/graphs/${fixture.variant_leiden_id}/at?t=${encodeURIComponent(
    t,
  )}&axis=${axis}`;
  return getJson(page, url);
}

async function getJson<T>(page: Page, url: string): Promise<T> {
  const resp = await page.request.get(url);
  expect(resp.ok()).toBeTruthy();
  return (await resp.json()) as T;
}

// The episode labels in rendered timeline order. The scrubber lays ticks
// out absolutely (left%) by axis time, so DOM order is constant — we sort
// the ticks by their rendered position (data-left) to recover the axis
// ordering the user sees. The back-dated Эпизод 3 changes position between
// the tx and valid axes, so this order differs across the toggle.
async function scrubberTickOrder(page: Page): Promise<string[]> {
  const ticks = page.getByTestId("timeline-tick");
  const count = await ticks.count();
  const rows: Array<{ label: string; left: number }> = [];
  for (let i = 0; i < count; i++) {
    const t = ticks.nth(i);
    const label = (await t.getAttribute("data-label")) ?? "";
    const left = Number((await t.getAttribute("data-left")) ?? "0");
    rows.push({ label, left });
  }
  return rows.sort((a, b) => a.left - b.left).map((r) => r.label);
}

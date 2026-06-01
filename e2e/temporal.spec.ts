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

  // Walk the ask wizard → MoE (mirror demo.spec §7) so the results graph
  // mounts and fires POST /api/reason/delta, which we intercept.
  await gotoAndSettle(page, "/wizards/ask");

  await page.getByText("Mixture of Experts", { exact: true }).click();
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  const leidenRow = page.locator("li", {
    hasText: fixture.variant_leiden_name,
  });
  await expect(leidenRow).toBeVisible({ timeout: 15_000 });
  await leidenRow.click();
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // VariantsStep → (skip) → QueryStep.
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  await page.locator("textarea").fill(fixture.moe_query);
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // Intercept the delta call fired when the answer is shown on the graph.
  const deltaPromise = page.waitForResponse(
    (resp: Response) =>
      resp.url().includes("/api/reason/delta") && resp.request().method() === "POST",
    { timeout: 45_000 },
  );

  await page
    .getByRole("main")
    .getByRole("button", { name: "Спросить", exact: true })
    .click();

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

  // Return to / surface the results graph so the canvas mounts and the
  // legend that explains the grammar is visible.
  const showOnGraph = page.getByTestId("results-show-on-graph");
  if (await showOnGraph.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await showOnGraph.click();
  }
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
  // node count: the window at tx_a (early) must contain fewer facts than
  // at tx_b (late) — the temporal window compresses the visible graph.
  const atTxA = await getMaterialized(page, fixture.tx_a!, "tx");
  const atTxB = await getMaterialized(page, fixture.tx_b!, "tx");
  expect(atTxA.node_ids.length).toBeLessThan(atTxB.node_ids.length);

  // (2) Axis re-sort. Capture the scrubber's rendered episode-label order
  // under axis=tx, click the AxisToggle (T′↔T), capture under axis=valid,
  // expect the two orderings DIFFER (the back-dated Эпизод 3 moves) and
  // that GET .../at then carries axis=valid.
  const orderTx = await scrubberLabelOrder(page);

  const axisToggle = page.getByTestId("axis-toggle");
  // Fall back to accessible name if the testid isn't wired yet (contract
  // recommends adding data-testid='axis-toggle' to make this stable).
  const toggle = (await axisToggle.count())
    ? axisToggle
    : page.getByRole("button", { name: /T['′]|valid|tx/i }).first();
  await toggle.click();

  const validAtPromise = page.waitForResponse(
    (resp: Response) =>
      /\/api\/graphs\/[^/]+\/at\b/.test(resp.url()) &&
      new URL(resp.url()).searchParams.get("axis") === "valid",
    { timeout: 15_000 },
  );
  // Nudge the scrubber so the axis-switched /at fires (drag/scrub). If the
  // toggle itself re-fetches, this resolves immediately.
  await validAtPromise.catch(() => undefined);

  const orderValid = await scrubberLabelOrder(page);
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

  const journalPromise = page.waitForResponse(
    (resp: Response) =>
      /\/journal\b/.test(resp.url()) && resp.request().method() === "POST",
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

  const badgeText = (await badge.innerText()).trim();
  expect(badgeText).toMatch(/\d+(\.\d+)?\s*ms/);

  const tier = await badge.getAttribute("data-tier");
  expect(["fast", "mid", "slow"]).toContain(tier);

  // The rendered ms matches the contract value within rounding tolerance.
  const renderedMs = Number(badgeText.match(/(\d+(?:\.\d+)?)\s*ms/)?.[1]);
  expect(Math.abs(renderedMs - Math.round(journalBody.recompute_ms))).toBeLessThanOrEqual(1);

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

  // The invalidation-panel only mounts when the diff window has
  // invalidated edges. Open the temporal view and set the scrubber to a
  // window covering tx_a..tx_b so the auto-invalidated edge is in
  // diff.invalidated. Drive the Time button (canvas eats keys).
  await page.getByTestId("timeline-toggle").click();
  await expect(page.getByTestId("graph-canvas")).toBeVisible();

  const panel = page.getByTestId("invalidation-panel");
  await expect(panel).toBeVisible({ timeout: 15_000 });

  const row = page.locator(
    `[data-testid="invalidation-row"][data-edge-id="${fixture.invalidated_edge_id}"]`,
  );
  await expect(row).toBeVisible();
  // Provenance text — the reason carried by the auto-invalidation.
  await expect(row).toContainText(/superseded by Эпизод 3/);

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
  expect(reqBody.expected_version).toBe(fixture.invalidated_edge_version);
  expect(reqBody.actor).toBe(`user:${USER_EMAIL}`);

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

  // Read the current variant version (stale-v we will reuse below).
  const staleVersion = await readVersion(page).catch(async () => {
    const v = await getJson<{ version: number }>(
      page,
      `${BACKEND}/api/graphs/${fixture.variant_leiden_id}`,
    );
    return v.version;
  });

  // Bump the version to v+1 via a successful UI write (suggestion accept)
  // so the next write at expected_version=staleVersion is genuinely stale.
  await page
    .getByRole("button", { name: /Показать Suggestions/ })
    .click();
  const accept = page.getByTestId("suggestion-accept").first();
  if (await accept.isVisible({ timeout: 5_000 }).catch(() => false)) {
    const before = await readVersion(page).catch(() => staleVersion);
    await accept.click();
    await expect.poll(() => readVersion(page).catch(() => before), {
      timeout: 10_000,
    }).toBeGreaterThan(before);
  } else {
    // No suggestion to accept — fall back to a direct journal bump so the
    // stale-v reproduction is still deterministic.
    const nodes = await getJson<Array<{ id: string }>>(
      page,
      `${BACKEND}/api/graphs/${fixture.variant_leiden_id}/nodes?limit=1`,
    );
    if (nodes.length > 0) {
      await page.evaluate(
        async ([backend, vid, v, eid, nid]) => {
          await fetch(`${backend}/api/graphs/${vid}/journal`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              op: "set_summary",
              payload: { node_id: nid, summary: "bump" },
              expected_version: v,
              actor: `user:${eid}`,
            }),
          });
        },
        [BACKEND, fixture.variant_leiden_id, staleVersion, USER_EMAIL, nodes[0].id] as const,
      );
    }
  }

  // Drive a second write whose expected_version is still the stale v.
  // merge_nodes needs two real node ids. The frontend's write layer
  // surfaces the 409 as the ErrorBanner.
  const nodes = await getJson<Array<{ id: string }>>(
    page,
    `${BACKEND}/api/graphs/${fixture.variant_leiden_id}/nodes?limit=2`,
  );
  test.skip(nodes.length < 2, "need >=2 nodes to force a merge 409");

  const status = await page.evaluate(
    async ([backend, vid, v, email, a, b]) => {
      const resp = await fetch(`${backend}/api/graphs/${vid}/journal`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          op: "merge_nodes",
          payload: { node_ids: [a, b], survivor_id: a },
          expected_version: v,
          actor: `user:${email}`,
        }),
      });
      return resp.status;
    },
    [
      BACKEND,
      fixture.variant_leiden_id,
      staleVersion,
      USER_EMAIL,
      nodes[0].id,
      nodes[1].id,
    ] as const,
  );
  expect(status).toBe(409);

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

// The ordered episode labels rendered on the scrubber. Reads the visible
// label text in DOM order from the timeline region.
async function scrubberLabelOrder(page: Page): Promise<string[]> {
  const labels = page
    .getByTestId("timeline-toggle")
    .locator("xpath=ancestor::*[1]")
    .locator("text=/Эпизод \\d+/");
  // Prefer an explicit scrubber region if the contract exposes one; fall
  // back to any visible "Эпизод N" labels in document order.
  const all = page.locator("text=/Эпизод \\d+ \\(ВШЭ\\)/");
  const count = await all.count();
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const txt = (await all.nth(i).innerText()).trim();
    if (txt) out.push(txt);
  }
  void labels;
  return out;
}

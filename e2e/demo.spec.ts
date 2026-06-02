// Demo e2e: HSE podcast end-to-end through the UI. Mirrors
// docs/redesign/demo_scenario.md sections 1, 2, 3, 5, 6, 7.
//
// Design notes:
// - Layer toggles are exercised via the visible chip buttons, not via
//   page.keyboard.press, because the @krainovsd/graph canvas captures
//   focus on mount and intercepts native key events. A dedicated
//   hotkey test below dispatches a synthetic KeyboardEvent on window
//   to verify the LayeredGraph keymap separately.
// - Canvas hit-testing (NodeDrawer node click) is left to manual demo.

import { test, expect, type Page } from "@playwright/test";

import { seed, type SeedResult } from "./lib/seed";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

let fixture: SeedResult;

test.beforeAll(async () => {
  fixture = await seed(BACKEND);
});

// §2.6 GuidedWalkthrough auto-starts on first graph-page visit (no
// 'gr:walkthrough:seen' in localStorage) and its full-screen spotlight
// intercepts clicks these feature tests drive. Mark the tour as seen
// before any page loads — the tour itself is covered by temporal.spec.
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

test("§1 corpus list shows the seeded HSE Podcast with two ready variants", async ({
  page,
}) => {
  await gotoAndSettle(page, "/corpora");
  await expect(page.getByRole("heading", { name: "Корпуса" })).toBeVisible();

  const card = page.locator("li").filter({ hasText: fixture.corpus_name });
  await expect(card).toHaveCount(1);
  await expect(card.getByText(fixture.variant_leiden_name)).toBeVisible();
  await expect(card.getByText(fixture.variant_bare_name)).toBeVisible();

  // Both variants are ready (status chip text). build_variant marks them
  // READY synchronously now.
  const ready = card.locator("text=ready");
  await expect(ready).toHaveCount(2);
});

test("§2 variant page renders LayeredGraph + entity chip click toggles active class", async ({
  page,
}) => {
  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);

  await expect(
    page.getByRole("heading", { name: fixture.variant_leiden_name }),
  ).toBeVisible();
  await expect(page.getByText(/Узлов/)).toBeVisible();

  const toolbar = page.locator('[aria-label="Layered Graph controls"]');
  for (const layer of ["chunk", "entity", "community", "topic"]) {
    await expect(
      toolbar.getByRole("button", { name: layer, exact: true }),
    ).toBeVisible();
  }

  const entityChip = toolbar.getByRole("button", { name: "entity", exact: true });
  await entityChip.click();

  // CSS modules hash the class name, but the substring `chip_active`
  // survives the transform, so includes() is robust.
  await expect
    .poll(async () =>
      (await entityChip.getAttribute("class"))?.includes("chip_active") ?? false,
    )
    .toBe(true);
});

test("§3 hotkey L opens Layer Map overlay (synthetic keydown)", async ({ page }) => {
  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);

  // Synthetic keydown on window — bypasses focus questions; the hotkey
  // handler in LayeredGraph.vue is registered on `window` and matches
  // e.key === "l" or "L".
  await page.evaluate(() =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "l", bubbles: true })),
  );

  const overlay = page.locator('[aria-label="Layer Map"]');
  await expect(overlay).toBeVisible();
  await expect(overlay.getByRole("heading", { name: "Layer Map" })).toBeVisible();
  await expect(overlay.locator("input[type=checkbox]")).toBeVisible();

  await page.evaluate(() =>
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })),
  );
  await expect(overlay).toBeHidden();
});

test("§3b layer-map toolbar button opens the same overlay", async ({ page }) => {
  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);
  await page.getByRole("button", { name: "layer map", exact: true }).click();
  await expect(page.locator('[aria-label="Layer Map"]')).toBeVisible();
});

test("§5 Suggestions sidebar opens, lists pending or empty path", async ({ page }) => {
  await gotoAndSettle(page, `/graphs/${fixture.variant_leiden_id}`);
  await page
    .getByRole("button", { name: /Показать Suggestions/ })
    .click();

  const sidebar = page.locator('[aria-label="Pending suggestions"]');
  await expect(sidebar).toBeVisible();
  await expect(sidebar.getByText("Suggestions")).toBeVisible();

  const firstAccept = sidebar.getByRole("button", { name: "Принять" }).first();
  if (await firstAccept.isVisible({ timeout: 3000 }).catch(() => false)) {
    const versionBefore = await readVersion(page);
    await firstAccept.click();
    await expect.poll(() => readVersion(page)).toBeGreaterThan(versionBefore);
  } else {
    await expect(sidebar.getByText(/Pending suggestions нет/)).toBeVisible();
  }
});

test("§6 split-view compare renders both panes; chip click syncs across panes", async ({
  page,
}) => {
  await gotoAndSettle(
    page,
    `/graphs/compare?ids=${fixture.variant_leiden_id},${fixture.variant_bare_id}`,
  );

  const toolbars = page.locator('[aria-label="Layered Graph controls"]');
  await expect(toolbars).toHaveCount(2);
  await expect(page.getByText(fixture.variant_leiden_name)).toBeVisible();
  await expect(page.getByText(fixture.variant_bare_name)).toBeVisible();

  const leftEntity = toolbars.first().getByRole("button", { name: "entity", exact: true });
  const rightEntity = toolbars.nth(1).getByRole("button", { name: "entity", exact: true });
  await leftEntity.click();

  for (const chip of [leftEntity, rightEntity]) {
    await expect
      .poll(async () =>
        (await chip.getAttribute("class"))?.includes("chip_active") ?? false,
      )
      .toBe(true);
  }
});

test("§7 ask wizard → MoE SSE end-to-end", async ({ page }) => {
  await gotoAndSettle(page, "/wizards/ask");

  await page.getByText("Mixture of Experts", { exact: true }).click();
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  const leidenRow = page.locator("li", { hasText: fixture.variant_leiden_name });
  const bareRow = page.locator("li", { hasText: fixture.variant_bare_name });
  await expect(leidenRow).toBeVisible({ timeout: 15_000 });
  await expect(bareRow).toBeVisible();
  await leidenRow.click();
  await bareRow.click();
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  await page.getByRole("button", { name: "Далее", exact: true }).click();

  await page.locator("textarea").fill("Кто работает в ВШЭ?");
  await page.getByRole("button", { name: "Далее", exact: true }).click();

  // Two buttons say "Спросить" on the results step (the CTA in main +
  // the footer Далее relabels to "Спросить" for the last step). The
  // CTA in main is the one we want; disambiguate by container.
  await page
    .getByRole("main")
    .getByRole("button", { name: "Спросить", exact: true })
    .click();

  await expect(
    page.locator("li").filter({ hasText: "keyword_search" }),
  ).toHaveCount(2, { timeout: 30_000 });

  await expect(
    page.getByRole("heading", { name: /Финальный ответ/ }),
  ).toBeVisible({ timeout: 30_000 });
});

async function readVersion(page: Page): Promise<number> {
  const txt = await page.getByText(/^v\d+$/).first().innerText();
  return Number(txt.replace(/^v/, ""));
}

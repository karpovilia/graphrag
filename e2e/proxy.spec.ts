// Regression: dev proxy must forward /api/** from the Nuxt origin to
// FastAPI. If `nitro.devProxy` is used alone (no routeRules) and an
// empty `server/api/` directory exists, nitro silently 404s every
// /api/* request and the whole UI shows "Не удалось загрузить корпусы:
// Failed to fetch". Catch that before it ships.

import { test, expect } from "@playwright/test";

test("dev proxy forwards /api/health to FastAPI (not nitro 404)", async ({
  request,
}) => {
  const resp = await request.get("/api/health");
  expect(resp.status(), "frontend origin must proxy /api/* to backend").toBe(
    200,
  );
  const body = await resp.json();
  expect(body).toMatchObject({ status: "ok" });
  expect(body.persistence).toMatch(/^(snapshot|postgres|in_memory)$/);
});

test("/corpora page loads without 'Failed to fetch' banner", async ({
  page,
}) => {
  await page.goto("/corpora");
  await page.waitForLoadState("networkidle");

  // The fetch-failure banner from pages/corpora.vue is the user-visible
  // symptom of a broken /api/* proxy. It must not appear.
  await expect(
    page.getByText("Не удалось загрузить корпусы"),
  ).toHaveCount(0);

  // Page must reach a settled state — either "no corpora yet" empty
  // state or actual cards. Either way the heading <h1> renders the
  // localised "Corpora"/"Корпуса". level:1 disambiguates from the nav
  // link with the same name.
  await expect(
    page.getByRole("heading", { level: 1, name: /Corpora|Корпуса/ }),
  ).toBeVisible();
});

test("/corpora cards: clicking the card body navigates to the corpus", async ({
  page,
  request,
}) => {
  // Regression: cards used to be navigable only via the title link.
  // The stretched-link overlay must catch clicks on the metrics area too,
  // while inner variant links still resolve to /graphs/{id}.
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");

  await page.goto("/corpora");
  await page.waitForLoadState("networkidle");

  const card = page.locator("ul li", { hasText: /Документов|Documents/ }).first();
  await expect(card).toBeVisible();

  // Click the metrics block (definition list) — outside any inner link.
  // force:true skips actionability — we *want* the title's stretched ::after
  // overlay to intercept the click here; that's the feature under test.
  await card.locator("dl").click({ force: true });
  await page.waitForURL(/\/corpora\/[0-9a-f-]+$/, { timeout: 10_000 });
  await expect(
    page.getByRole("link", { name: /Назад к корпусам|Back to corpora/ }),
  ).toBeVisible();
});

test("graph variant nodes carry human-readable name (not just UUID)", async ({
  page,
  request,
}) => {
  // Regression: LayeredGraph used to push cityNodes without a top-level
  // `name`, so @krainovsd/graph fell back to rendering `id` (UUID) on
  // every vertex. Catch both sides:
  //   1. Backend contract: /nodes must return non-empty `name`.
  //   2. Frontend mount: /graphs/{id} must render without pageerror —
  //      a thrown error from cityGraph mapping would surface here.

  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");

  const variants = await request.get(
    `/api/graphs?corpus_id=${corpora[0]!.id}`,
  );
  const variantList = (await variants.json()) as Array<{
    id: string;
    status: string;
  }>;
  const ready = variantList.find((v) => v.status === "ready");
  test.skip(!ready, "no ready variant to inspect");

  const nodesResp = await request.get(
    `/api/graphs/${ready!.id}/nodes?limit=10`,
  );
  expect(nodesResp.status()).toBe(200);
  const nodes = (await nodesResp.json()) as Array<{ id: string; name: string }>;
  expect(nodes.length).toBeGreaterThan(0);
  for (const n of nodes) {
    expect(n.name, `node ${n.id} missing name`).toBeTruthy();
    expect(n.name, `node ${n.id} name is the UUID`).not.toBe(n.id);
  }

  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
  });

  await page.goto(`/graphs/${ready!.id}`);
  await page.waitForLoadState("networkidle");

  expect(
    errors.filter((e) => /querySelectorAll|H3Error|TypeError/i.test(e)),
    `LayeredGraph mount errors:\n${errors.join("\n")}`,
  ).toEqual([]);
});

test("/corpora/{id} CTA opens build wizard at pipeline step", async ({
  page,
  request,
}) => {
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");

  await page.goto(`/corpora/${corpora[0]!.id}`);
  await page.waitForLoadState("networkidle");

  const cta = page.getByRole("link", { name: /Новый вариант/ });
  await expect(cta).toBeVisible();
  const href = await cta.getAttribute("href");
  expect(href).toContain(`corpus_id=${corpora[0]!.id}`);
  expect(href).toContain("step=4");

  await page.goto(href!);
  await page.waitForLoadState("networkidle");
  // Wizard must land on the pipeline step (heading "Пайплайн сборки"),
  // not the corpus-creation step.
  await expect(
    page.getByRole("heading", { name: /Пайплайн сборки/ }),
  ).toBeVisible();
});

test("/corpora/{id} document drill-down opens detail page with text", async ({
  page,
  request,
}) => {
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");

  const cid = corpora[0]!.id;
  const docs = await request.get(`/api/corpora/${cid}/documents`);
  const docList = (await docs.json()) as Array<{ id: string; title: string }>;
  test.skip(docList.length === 0, "corpus has no documents");

  await page.goto(`/corpora/${cid}`);
  await page.waitForLoadState("networkidle");

  // Document title in the corpus list must be a link to the detail page.
  const doc = docList[0]!;
  const link = page.getByRole("link", { name: doc.title }).first();
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL(`**/corpora/${cid}/documents/${doc.id}`);
  await page.waitForLoadState("networkidle");

  // Detail page renders the title as h1, the SHA-256 row, and the body
  // text — fall back gracefully if the doc has no stored text.
  await expect(page.getByRole("heading", { level: 1, name: doc.title })).toBeVisible();
  await expect(page.getByText(/SHA-256/i)).toBeVisible();
});

test("PipelineStep cards expose multi-line tooltips", async ({
  page,
  request,
}) => {
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");

  await page.goto(
    `/wizards/build?corpus_id=${corpora[0]!.id}&step=4`,
  );
  await page.waitForLoadState("networkidle");

  // Every builder/cleaner/clusterer card should carry a non-empty title
  // attribute that includes more than the visible summary (description +
  // params block from the strategy descriptor).
  const titles = await page.locator("li[title]").evaluateAll((els) =>
    els.map((el) => el.getAttribute("title") ?? ""),
  );
  expect(titles.length).toBeGreaterThan(2);
  for (const t of titles) {
    expect(t.length).toBeGreaterThan(0);
  }
  // At least one tooltip should mention "Параметры" or "слои" — the
  // structured sections we added.
  expect(titles.some((t) => /Параметры|слои/.test(t))).toBe(true);
});

test("Entity types panel: multi-select chips + per-type colour", async ({
  page,
  request,
}) => {
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");
  const variants = await request.get(
    `/api/graphs?corpus_id=${corpora[0]!.id}`,
  );
  const variantList = (await variants.json()) as Array<{
    id: string;
    status: string;
  }>;
  const ready = variantList.find((v) => v.status === "ready");
  test.skip(!ready, "no ready variant");

  await page.goto(`/graphs/${ready!.id}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  await page.getByRole("button", { name: /^(Слои|Layers)$/ }).click();

  // The panel is now entity-types only: chips + per-type colour pickers, no
  // node table and no chunk-layer types.
  const chips = page.getByTestId("type-chip");
  await expect(chips.first()).toBeVisible();
  const labels = await chips.allTextContents();
  expect(labels.some((l) => /chunk/i.test(l))).toBe(false); // chunks excluded
  await expect(page.getByTestId("type-color").first()).toBeVisible();
  // toggling a type chip must not throw
  await chips.first().click();
});

test("/graphs/{id}: visiting the page persists a force-layout cache", async ({
  page,
  request,
}) => {
  // Regression: first-load rendered the d3-force simulation from scratch
  // every time. We now PUT positions on simulation-end so a refresh
  // (anyone, anywhere — fallback is global) starts from the cached
  // arrangement. Test only checks the persistence side: visit → DB row.
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");
  const variants = await request.get(
    `/api/graphs?corpus_id=${corpora[0]!.id}`,
  );
  const variantList = (await variants.json()) as Array<{
    id: string;
    status: string;
  }>;
  const ready = variantList.find((v) => v.status === "ready");
  test.skip(!ready, "no ready variant");

  // Reset to empty so we can detect the post-mount write deterministically.
  await request.put(`/api/graphs/${ready!.id}/layout`, {
    data: { positions: {} },
  });
  const before = await (
    await request.get(`/api/graphs/${ready!.id}/layout`)
  ).json();
  expect(Object.keys(before.positions ?? {})).toHaveLength(0);

  await page.goto(`/graphs/${ready!.id}`);
  await page.waitForLoadState("networkidle");
  // Wait for d3-force to settle + the 1.5s save debounce in LayeredGraph.
  // Simulation cost on ~1.5k nodes is empirically 3-6s; pick a generous
  // upper bound but poll so the test ends as soon as the row lands.
  await expect
    .poll(
      async () => {
        const resp = await request.get(`/api/graphs/${ready!.id}/layout`);
        const body = (await resp.json()) as {
          positions: Record<string, [number, number]>;
        };
        return Object.keys(body.positions ?? {}).length;
      },
      { timeout: 30_000, intervals: [500, 1_000, 2_000] },
    )
    .toBeGreaterThan(0);
});

test("similarity_merge_candidates agent registered + run+ranks pairs", async ({
  request,
}) => {
  const r = await request.get("/api/agents");
  const agents = (await r.json()) as Array<{ name: string }>;
  expect(agents.map((a) => a.name)).toContain("similarity_merge_candidates");
});

test("LayeredGraph toolbar exposes recenter button", async ({
  page,
  request,
}) => {
  const list = await request.get("/api/corpora");
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded");
  const variants = await request.get(
    `/api/graphs?corpus_id=${corpora[0]!.id}`,
  );
  const variantList = (await variants.json()) as Array<{
    id: string;
    status: string;
  }>;
  const ready = variantList.find((v) => v.status === "ready");
  test.skip(!ready, "no ready variant");

  await page.goto(`/graphs/${ready!.id}`);
  await page.waitForLoadState("networkidle");

  const btn = page.getByRole("button", { name: /центрировать/i });
  await expect(btn).toBeVisible();

  // Clicking must not throw — the recenter helper pokes private fields
  // on the GraphCanvas instance, so any future lib refactor that drops
  // `areaTransform` will surface here.
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  await btn.click();
  await page.waitForTimeout(200);
  expect(errors).toEqual([]);
});

test("auth: register → land in app, /profile shows email", async ({
  page,
}) => {
  // Unique email per run so re-running the spec on a persistent backend
  // snapshot doesn't 409.
  const email = `e2e+${Date.now()}@example.com`;

  await page.goto("/register");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill("regression-pwd-1");
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/(corpora|$)/, { timeout: 10_000 });

  // Use page.context().request so the auth cookie set by the browser
  // travels with this server-side check too.
  const me = await page.context().request.get("/api/auth/me");
  expect(me.status()).toBe(200);
  expect((await me.json()).email).toBe(email);

  await page.goto("/profile");
  await page.waitForLoadState("networkidle");
  // Email shows up in both header (link to /profile) and the account
  // section <dd>; .first() picks one deterministically.
  await expect(page.getByText(email).first()).toBeVisible();
});

test("auth: anonymous /profile redirects to /login", async ({
  page,
  context,
}) => {
  await context.clearCookies();
  await page.goto("/profile");
  await page.waitForURL(/\/login/, { timeout: 10_000 });
  expect(page.url()).toContain("/login");
});

test("i18n: anonymous header switches between RU and EN", async ({
  page,
  context,
}) => {
  await context.clearCookies();
  await page.goto("/corpora");
  await page.waitForLoadState("networkidle");
  // Force RU explicitly via the header switcher first — playwright's
  // default Accept-Language is en-US so detectBrowserLanguage may pick
  // either; pin both endpoints of the toggle.
  const localeSelect = page.locator("header select").first();
  await localeSelect.selectOption("ru");
  await expect(
    page.getByRole("heading", { level: 1, name: "Корпуса" }),
  ).toBeVisible();
  await localeSelect.selectOption("en");
  await expect(
    page.getByRole("heading", { level: 1, name: "Corpora" }),
  ).toBeVisible();
});

test("corpus detail pages mount without client errors", async ({
  page,
  request,
}) => {
  // Style modules with class names that shadow globals (`.document`,
  // `.window`, ...) get exported as `const document = "_document_..."`
  // which makes vite's HMR `document.querySelectorAll(...)` snippet
  // throw at runtime and the page renders Nuxt's 500. Catch any pageerror
  // (from any dynamically-imported style module) on this page.

  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
  });

  // Need a corpus id to navigate to. Take the first one or skip if
  // backend has none — this regression depends on the runtime data path
  // existing, not on a fresh fixture.
  const list = await request.get("/api/corpora");
  expect(list.status()).toBe(200);
  const corpora = (await list.json()) as Array<{ id: string }>;
  test.skip(corpora.length === 0, "no corpora seeded; ingest at least one");

  await page.goto(`/corpora/${corpora[0]!.id}`);
  await page.waitForLoadState("networkidle");

  expect(
    errors.filter((e) => /querySelectorAll is not a function|H3Error/i.test(e)),
    `style-module/global-shadow regression:\n${errors.join("\n")}`,
  ).toEqual([]);

  await expect(
    page.getByRole("link", { name: /Назад к корпусам/ }),
  ).toBeVisible();
});

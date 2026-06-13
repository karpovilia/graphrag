/** Browser e2e of the signature loop. Assumes hub (4001) + frontend (5173)
 *  are running. Run: tsx e2e/loop.smoke.ts */
import { chromium } from "playwright";

const FRONT = process.env.FRONT_URL ?? "http://127.0.0.1:5173";
const HUB = process.env.COLLAB_HTTP_URL ?? "http://127.0.0.1:4001";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`ASSERT FAILED: ${msg}`);
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto(`${FRONT}/?graph=sample`, { waitUntil: "networkidle" });

  // 1) engine rendered a canvas
  await page.waitForSelector("canvas", { timeout: 15000 });
  console.log("✓ canvas rendered");

  // 2) version badge + presence visible
  const badge = await page.textContent(".badge");
  assert(badge?.startsWith("v"), "version badge present");
  console.log(`✓ version badge: ${badge}`);

  // wait until the ws is connected so broadcasts aren't missed
  await page.waitForSelector(".dot.on", { timeout: 10000 });
  console.log("✓ websocket connected");

  // 3) structural agent → suggestions appear
  await page.locator(".agent-buttons button", { hasText: "Find duplicates" }).click();
  await page.waitForSelector(".card", { timeout: 8000 }).catch(async () => {
    const tab = await page.textContent(".tabs button.active");
    await page.screenshot({ path: "e2e-debug.png" });
    throw new Error(`no cards; active tab label = "${tab?.trim()}"`);
  });
  const cards = await page.locator(".card").count();
  assert(cards > 0, "dedup produced suggestion cards");
  console.log(`✓ dedup suggestions in UI: ${cards}`);

  // 4) THE LOOP: agent opens a decision via the hub → modal appears in the
  //    browser → human clicks Accept → agent's blocked call returns accept.
  const did = crypto.randomUUID();
  const decisionPromise = fetch(`${HUB}/api/graphs/sample/decisions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      by: "agent:claude",
      timeoutMs: 10000,
      request: {
        decisionId: did,
        kind: "merge",
        proposal: "Merge «Ваня» into «Иван Чепиков»?",
        op: "merge_nodes",
        payload: { survivorId: "ivan", absorbedIds: ["vanya"] },
        nodeIds: ["ivan", "vanya"],
        options: ["accept", "reject", "edit", "pin"],
      },
    }),
  }).then((r) => r.json() as Promise<{ choice: string; by?: string }>);

  await page.waitForSelector(".decision-card", { timeout: 8000 });
  console.log("✓ decision modal appeared in browser");
  await page.locator(".decision-actions button", { hasText: "Accept" }).click();

  const result = await decisionPromise;
  assert(result.choice === "accept", `agent received accept (got ${result.choice})`);
  console.log(`✓ loop closed: agent received '${result.choice}' from ${result.by}`);

  assert(errors.length === 0, `no page errors (got: ${errors.join(" | ")})`);
  console.log("✓ no page errors");

  await browser.close();
  console.log("\nE2E PASSED");
}

main().catch((e) => {
  console.error("\nE2E FAILED:", e);
  process.exit(1);
});

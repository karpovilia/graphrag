/** Install the /graphcraft skill into Claude Code (and register the MCP
 *  server). Idempotent. Mirrors graphify's install mechanism.
 *
 *  Usage:
 *    pnpm install:skill            # project install (./.claude + ./.mcp.json)
 *    pnpm install:skill --global   # user install (~/.claude)
 */
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SKILL = "graphcraft";
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const SKILL_SRC = path.join(repoRoot, "skill", "SKILL.md");

const REGISTRATION = `
# ${SKILL}
- **${SKILL}** (knowledge-graph curation) — drive a live GraphCraft room: read a slice, focus the human's canvas, propose edits, request an interactive decision, compile skills. Trigger: \`/${SKILL}\`
When the user types \`/${SKILL}\`, invoke the Skill tool with \`skill: "${SKILL}"\` before doing anything else.
`;

async function writeAtomic(file: string, content: string): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, content);
  await fs.rename(tmp, file);
}

async function patchClaudeMd(claudeMd: string): Promise<string> {
  let existing = "";
  try {
    existing = await fs.readFile(claudeMd, "utf8");
  } catch {
    /* new file */
  }
  if (existing.includes(`# ${SKILL}\n`)) return "already registered";
  await writeAtomic(claudeMd, existing.replace(/\s*$/, "") + "\n" + REGISTRATION);
  return "registered";
}

async function patchMcpJson(mcpJson: string): Promise<string> {
  let cfg: { mcpServers?: Record<string, unknown> } = {};
  try {
    cfg = JSON.parse(await fs.readFile(mcpJson, "utf8"));
  } catch {
    /* new file */
  }
  cfg.mcpServers ??= {};
  if (cfg.mcpServers[SKILL]) return "already registered";
  cfg.mcpServers[SKILL] = {
    command: "pnpm",
    args: ["--filter", "@graphcraft/mcp-service", "start"],
    cwd: repoRoot,
    env: { COLLAB_HTTP_URL: process.env.COLLAB_HTTP_URL ?? "http://127.0.0.1:4001" },
  };
  await writeAtomic(mcpJson, JSON.stringify(cfg, null, 2) + "\n");
  return "registered";
}

async function main() {
  const global = process.argv.includes("--global");
  const root = global ? path.join(os.homedir(), ".claude") : path.resolve(".claude");

  const skillDst = path.join(root, "skills", SKILL, "SKILL.md");
  await writeAtomic(skillDst, await fs.readFile(SKILL_SRC, "utf8"));
  console.log(`  SKILL.md     → ${skillDst}`);

  const claudeMd = path.join(root, "CLAUDE.md");
  console.log(`  CLAUDE.md    → ${await patchClaudeMd(claudeMd)} (${claudeMd})`);

  // MCP registration lives at project scope (or ~/.claude.json for global).
  const mcpJson = global
    ? path.join(os.homedir(), ".claude.json")
    : path.resolve(".mcp.json");
  console.log(`  MCP server   → ${await patchMcpJson(mcpJson)} (${mcpJson})`);

  console.log(`\nDone. In a Claude Code session, type:\n\n  /${SKILL}\n`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

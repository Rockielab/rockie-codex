// Entry point for the team orchestrator.
//
// Usage: node index.js <team-config.json>
//
// What it does:
//   1. Validate config against schema (name patterns, required fields)
//   2. Stage context files into <run-dir>/context/
//   3. Create a git worktree per agent (under .team-runs/<run-id>/worktrees/)
//   4. Start the dashboard on a local port, open Chrome to it
//   5. Run the team via orchestrator.js
//   6. On exit: write result.json, leave worktrees for inspection
//
// Run state lives in .team-runs/ (NOT .codex/) so agent worktrees never
// need write access to shared runtime state.

import { spawn, execFileSync } from "node:child_process";
import {
  readFileSync,
  writeFileSync,
  existsSync,
  mkdirSync,
  copyFileSync,
  chmodSync,
} from "node:fs";
import path from "node:path";
import {
  initRun,
  generateRunId,
  appendThreadPost,
} from "./state.js";
import { createWorktree, pruneWorktrees, validateName } from "./worktree.js";
import { startDashboard } from "./dashboard-server.js";
import { runTeam } from "./orchestrator.js";

function repoRoot() {
  return execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
}

function validateConfig(config) {
  if (!config || typeof config !== "object") throw new Error("config must be an object");
  if (!config.name) throw new Error("config.name is required");
  validateName(config.name, "config.name");
  if (!config.purpose) throw new Error("config.purpose is required");
  if (!Array.isArray(config.agents) || config.agents.length === 0) {
    throw new Error("config.agents must be a non-empty array");
  }
  const seen = new Set();
  for (const agent of config.agents) {
    if (!agent.name) throw new Error("agent.name required");
    validateName(agent.name, `agent "${agent.name}".name`);
    if (seen.has(agent.name)) throw new Error(`duplicate agent name: ${agent.name}`);
    seen.add(agent.name);
    if (!agent.motivation) throw new Error(`agent ${agent.name}: motivation required`);
    if (!agent.prompt) throw new Error(`agent ${agent.name}: prompt required`);
    if (agent.model && !["haiku", "sonnet", "opus", "gpt-5.4-mini", "gpt-5.4", "gpt-5.5"].includes(agent.model)) {
      throw new Error(`agent ${agent.name}: model must be haiku|sonnet|opus|gpt-5.4-mini|gpt-5.4|gpt-5.5`);
    }
  }
}

function stageContextFiles({ repoRoot: root, runDir, files }) {
  if (!files?.length) return;
  const ctxDir = path.join(runDir, "context");
  mkdirSync(ctxDir, { recursive: true });
  // HIGH bug from self-review: a context_files entry like "../../.env" would
  // resolve via path.join to a file outside the repo (credentials, system
  // files) and copy it into the context dir, handing it to every agent.
  // Containment check: resolved src MUST stay under repoRoot; dst MUST stay
  // under ctxDir. No symlink-resolution here — path.resolve is syntactic,
  // which is fine for defense-in-depth against config typos / malicious
  // configs.
  const rootReal = path.resolve(root) + path.sep;
  const ctxReal = path.resolve(ctxDir) + path.sep;
  for (const relPath of files) {
    const src = path.resolve(root, relPath);
    const dst = path.resolve(ctxDir, relPath);
    if (!src.startsWith(rootReal)) {
      throw new Error(
        `context_files entry "${relPath}" escapes repo root (resolves to ${src})`,
      );
    }
    if (!dst.startsWith(ctxReal)) {
      throw new Error(
        `context_files entry "${relPath}" would write outside context dir (${dst})`,
      );
    }
    if (!existsSync(src)) {
      console.warn(`⚠  context file not found: ${relPath}`);
      continue;
    }
    mkdirSync(path.dirname(dst), { recursive: true });
    copyFileSync(src, dst);
  }
}

function openBrowser(url) {
  const opener = process.platform === "darwin" ? "open" : "xdg-open";
  try {
    spawn(opener, [url], { stdio: "ignore", detached: true }).unref();
  } catch {
    console.log(`Open this in a browser: ${url}`);
  }
}

async function main() {
  const configPath = process.argv[2];
  if (!configPath) {
    console.error("Usage: node index.js <team-config.json>");
    process.exit(2);
  }
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  validateConfig(config);

  const root = repoRoot();
  pruneWorktrees(root);

  const runsRoot = path.join(root, ".team-runs");
  mkdirSync(runsRoot, { recursive: true });
  const runId = generateRunId(config.name);
  const runDir = path.join(runsRoot, runId);

  console.log(`━━━ team: ${config.name} ━━━`);
  console.log(`run dir: ${runDir}`);
  initRun({ runDir, config });

  // Stage team-level context files; per-agent context_files get staged too.
  stageContextFiles({
    repoRoot: root,
    runDir,
    files: [
      ...(config.context_files || []),
      ...config.agents.flatMap((a) => a.context_files || []),
    ],
  });

  // Create worktrees
  const worktreeRoot = path.join(runDir, "worktrees");
  const worktreePaths = {};
  const base = config.target?.base || "main";
  for (const agent of config.agents) {
    const wt = createWorktree({
      repoRoot: root,
      runId,
      agentName: agent.name,
      worktreeRoot,
      base,
    });
    worktreePaths[agent.name] = wt;
    console.log(`  worktree: ${agent.name} → ${wt}`);
  }

  // Start dashboard + open browser
  const { url, port } = await startDashboard({ runDir, port: 0 });
  console.log(`dashboard: ${url}`);
  openBrowser(url);

  // Write a helper script for agents to post to the thread atomically.
  // Agents call `bash <run-dir>/bin/post-thread <author> "content"` instead
  // of Edit-ing thread.md directly (which races under concurrency).
  const binDir = path.join(runDir, "bin");
  mkdirSync(binDir, { recursive: true });
  const postScript = path.join(binDir, "post-thread");
  writeFileSync(
    postScript,
    `#!/bin/bash
# Atomic thread-post helper. Replaces direct Edit on thread.md (which races
# under concurrent agent writes).
#
# Usage:
#   post-thread <author> "<content>"
#   echo "content" | post-thread <author> -
#
set -u
if [ -z "\${1:-}" ]; then
  echo "post-thread: author required" >&2
  exit 2
fi
AUTHOR="$1"
if [ "\${2:-}" = "-" ] || [ -z "\${2:-}" ]; then
  CONTENT="$(cat)"
else
  CONTENT="$2"
fi
if [ -z "$CONTENT" ]; then
  echo "post-thread: content required" >&2
  exit 2
fi
JSON="$(jq -n --arg a "$AUTHOR" --arg c "$CONTENT" '{author: $a, content: $c}')"
RESPONSE="$(curl -fsS -X POST http://localhost:${port}/api/thread-post \\
  -H 'Content-Type: application/json' \\
  --data "$JSON" 2>&1)" || {
  echo "post-thread: HTTP failed: $RESPONSE" >&2
  exit 1
}
echo "$RESPONSE"
`,
  );
  chmodSync(postScript, 0o755);

  // Seed thread with a welcome post
  appendThreadPost({
    runDir,
    author: "orchestrator",
    content: `Team **${config.name}** started. ${config.agents.length} agent(s). Target deadline: ${config.max_total_minutes || 30}min.`,
  });

  // Ctrl-C abort support
  const abortController = new AbortController();
  process.on("SIGINT", () => {
    console.log("\n◦ SIGINT — signalling abort to team");
    abortController.abort();
  });

  const results = await runTeam({
    runDir,
    config,
    worktreePaths,
    signal: abortController.signal,
  });

  writeFileSync(path.join(runDir, "result.json"), JSON.stringify(results, null, 2));
  console.log("");
  console.log("━━━ team finished ━━━");
  for (const r of results) {
    console.log(`  ${r.agent}: ${r.stopped}`);
  }
  console.log(`thread:   ${path.join(runDir, "thread.md")}`);
  console.log(`result:   ${path.join(runDir, "result.json")}`);
  console.log(`dashboard still live: ${url}  (Ctrl-C to stop)`);
}

main().catch((err) => {
  console.error("orchestrator error:", err.message);
  console.error(err.stack);
  process.exit(1);
});

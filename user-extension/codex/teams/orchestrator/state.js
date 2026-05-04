// Per-run state management — filesystem-based, append-only where possible.
// No database, no native deps. Every file is auditable with `cat`.

import {
  readFileSync,
  writeFileSync,
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
} from "node:fs";
import path from "node:path";

// ── Run init ────────────────────────────────────────────────────────────────

export function initRun({ runDir, config }) {
  mkdirSync(runDir, { recursive: true });
  mkdirSync(path.join(runDir, "agents"), { recursive: true });
  mkdirSync(path.join(runDir, "worktrees"), { recursive: true });
  mkdirSync(path.join(runDir, "context"), { recursive: true });

  writeFileSync(path.join(runDir, "config.json"), JSON.stringify(config, null, 2));

  const threadPath = path.join(runDir, "thread.md");
  if (!existsSync(threadPath)) {
    writeFileSync(
      threadPath,
      `# Team Thread: ${config.name}\n\n${config.purpose}\n\n---\n`,
    );
  }
  const interventionsPath = path.join(runDir, "interventions.jsonl");
  if (!existsSync(interventionsPath)) writeFileSync(interventionsPath, "");

  for (const agent of config.agents) {
    const agentDir = path.join(runDir, "agents", agent.name);
    mkdirSync(agentDir, { recursive: true });
    const statePath = path.join(agentDir, "state.json");
    if (!existsSync(statePath)) {
      writeFileSync(
        statePath,
        JSON.stringify(
          {
            name: agent.name,
            status: "pending",
            iteration: 0,
            last_seen_ts: null,
            last_notes: "",
            started_at: null,
            ended_at: null,
            done_reason: null,
          },
          null,
          2,
        ),
      );
    }
  }
}

// ── Per-agent state ─────────────────────────────────────────────────────────

export function getAgentState({ runDir, agentName }) {
  const statePath = path.join(runDir, "agents", agentName, "state.json");
  return JSON.parse(readFileSync(statePath, "utf8"));
}

export function updateAgentState({ runDir, agentName, updates }) {
  const current = getAgentState({ runDir, agentName });
  const next = { ...current, ...updates };
  const statePath = path.join(runDir, "agents", agentName, "state.json");
  writeFileSync(statePath, JSON.stringify(next, null, 2));
  return next;
}

// ── Shared thread ───────────────────────────────────────────────────────────

export function appendThreadPost({ runDir, author, content }) {
  const ts = new Date().toISOString();
  const block = `\n## [${ts}] ${author}\n\n${content}\n`;
  appendFileSync(path.join(runDir, "thread.md"), block);
  return ts;
}

// Parse thread posts using header-boundary splitting (NOT regex lookahead
// with multiline $, which truncates bodies at the first blank line — real
// bug from v1, see harness-v2 spec §21).
export function readThreadSince({ runDir, sinceTs }) {
  const threadPath = path.join(runDir, "thread.md");
  if (!existsSync(threadPath)) return [];
  const content = readFileSync(threadPath, "utf8");

  const posts = [];
  const headerRegex = /\n## \[([^\]]+)\] ([^\n]+)\n/g;
  const matches = [];
  let m;
  // Prepend \n so the first header matches (headerRegex expects leading \n)
  const searchText = "\n" + content;
  while ((m = headerRegex.exec(searchText)) !== null) {
    matches.push({
      // LOW bug from self-review: `m.index - 1` can be -1 when the content
      // starts with the header directly (no preamble). Clamp to 0 so the
      // following post's `bodyEnd` doesn't become -1 and chop off its
      // final byte via the negative-index semantics of slice().
      startIdx: Math.max(0, m.index - 1),
      ts: m[1],
      author: m[2].trim(),
      bodyStart: m.index + m[0].length - 1,
    });
  }

  for (let i = 0; i < matches.length; i++) {
    const { ts, author, bodyStart } = matches[i];
    const bodyEnd = i + 1 < matches.length ? matches[i + 1].startIdx : content.length;
    const body = content.slice(bodyStart, bodyEnd).trim();
    if (!sinceTs || ts > sinceTs) {
      posts.push({ ts, author, content: body });
    }
  }
  return posts;
}

// ── Interventions (dashboard → orchestrator events) ────────────────────────

export function appendIntervention({ runDir, event }) {
  const entry = { ts: new Date().toISOString(), ...event };
  appendFileSync(
    path.join(runDir, "interventions.jsonl"),
    JSON.stringify(entry) + "\n",
  );
  return entry;
}

export function readInterventions({ runDir, afterTs = null }) {
  const p = path.join(runDir, "interventions.jsonl");
  if (!existsSync(p)) return [];
  const content = readFileSync(p, "utf8").trim();
  if (!content) return [];
  return content
    .split("\n")
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter((e) => e && (!afterTs || e.ts > afterTs));
}

// ── Run IDs / listing ───────────────────────────────────────────────────────

export function generateRunId(teamName) {
  const now = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, "");
  const time = now.toTimeString().slice(0, 8).replace(/:/g, "");
  const slug = teamName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${date}-${time}-${slug}`;
}

export function listRuns(runsRoot) {
  if (!existsSync(runsRoot)) return [];
  return readdirSync(runsRoot)
    .filter((name) => !name.startsWith("."))
    .map((name) => {
      const runDir = path.join(runsRoot, name);
      const configPath = path.join(runDir, "config.json");
      if (!existsSync(configPath)) return null;
      return { id: name, runDir, config: JSON.parse(readFileSync(configPath, "utf8")) };
    })
    .filter(Boolean);
}

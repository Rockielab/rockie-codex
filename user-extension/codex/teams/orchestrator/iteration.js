// Single-agent Ralph loop.
//
// Each iteration:
//   1. Read thread deltas since this agent's last_seen_ts
//   2. Drain direct messages from interventions
//   3. Build prompt: task (first iter) / continuation (later) + deltas + DMs
//   4. Spawn `codex exec --json <prompt>`
//   5. Pipe every JSONL event line to events.jsonl (for live dashboard)
//   6. Detect AGENT_DONE sentinel in the final text; update state

import { spawn } from "node:child_process";
import { appendFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import path from "node:path";
import {
  getAgentState,
  updateAgentState,
  readThreadSince,
  readInterventions,
} from "./state.js";

const AGENT_DONE_SENTINEL = "AGENT_DONE";

function resolveModel(model = "gpt-5.4") {
  const aliases = {
    haiku: "gpt-5.4-mini",
    sonnet: "gpt-5.4",
    opus: "gpt-5.5",
  };
  return aliases[model] || model;
}

function buildPrompt({
  agent,
  agentState,
  threadPosts,
  directMessages,
  worktreePath,
  threadPath,
  isFirstIteration,
}) {
  const s = [];

  // Template substitution for user-authored prompts. Team config authors
  // reliably write relative paths like "./context/x.md" which don't resolve
  // from inside a git worktree (peer dir, not parent). Let them use
  // placeholders that expand to correct absolute paths.
  const runDirForTpl = path.dirname(threadPath);
  const contextDirForTpl = path.join(runDirForTpl, "context");
  const postScriptForTpl = path.join(runDirForTpl, "bin", "post-thread");
  const substitute = (text) =>
    (text || "")
      .replace(/\{\{context\}\}/g, contextDirForTpl)
      .replace(/\{\{context_dir\}\}/g, contextDirForTpl)
      .replace(/\{\{worktree\}\}/g, worktreePath)
      .replace(/\{\{post_thread\}\}/g, `bash ${postScriptForTpl} ${agent.name}`)
      .replace(/\{\{agent_name\}\}/g, agent.name);
  const agentPrompt = substitute(agent.prompt);

  if (isFirstIteration) {
    s.push("# Your Task\n");
    s.push(`**Your name:** ${agent.name}`);
    s.push(`**Your motivation:** ${agent.motivation}`);
    s.push(`**Your worktree (write code here):** ${worktreePath}`);
    s.push(`**Shared thread:** posts via the \`post-thread\` helper only (see Output channels below). You do NOT have filesystem access to the thread file.`);
    s.push("");
    s.push(agentPrompt);
    s.push("");

    // Context dir (staged by index.js from team + per-agent context_files).
    // Paths inside preserve repo-relative structure — an agent referencing
    // ".codex/teams/orchestrator/state.js" in its prompt can Read
    // `<contextDir>/.codex/teams/orchestrator/state.js`.
    const runDir = path.dirname(threadPath);
    const contextDir = path.join(runDir, "context");
    if (existsSync(contextDir)) {
      try {
        const hasFiles = readdirSync(contextDir).length > 0;
        if (hasFiles) {
          s.push("## Context Files (staged — read these with Read, don't try to cd outside your worktree)");
          s.push(`Location: \`${contextDir}/\``);
          s.push("Structure: repo-relative paths preserved (e.g., `.codex/teams/orchestrator/state.js`).");
          if (agent.context_files?.length) {
            s.push("Files specifically for you:");
            for (const f of agent.context_files) s.push(`- \`${contextDir}/${f}\``);
          }
          s.push("");
        }
      } catch {
        // context dir exists but unreadable — skip
      }
    }

    const postThreadScript = path.join(runDir, "bin", "post-thread");
    s.push("## Output channels — CRITICAL, read carefully");
    s.push("");
    s.push("You produce three kinds of output each iteration:");
    s.push("");
    s.push(
      "1. **Your response text** — PRIVATE. Appears in your agent card on the dashboard. The developer reads it there. Other agents do NOT see it.",
    );
    s.push(
      `2. **Posts to the shared thread** — PUBLIC. Every agent AND the developer sees your posts.`,
    );
    s.push("   **Use ONLY the Bash tool + this helper script. There is no other way:**");
    s.push("   ```bash");
    s.push(`   ${postThreadScript} ${agent.name} "<your content here>"`);
    s.push("   ```");
    s.push("   Or pipe via stdin for multi-line:");
    s.push("   ```bash");
    s.push(`   echo "<content>" | ${postThreadScript} ${agent.name} -`);
    s.push("   ```");
    s.push(
      `   The thread file itself lives outside your sandbox — Edit/Write/Read attempts against it will fail. This is deliberate: concurrent Edits race. The helper is an atomic HTTP POST. Thread content still reaches you through the "Thread Updates" section of your prompt each iteration.`,
    );
    s.push("3. **Other tool use** (Read, Bash for work, Grep…) — your actual task work.");
    s.push("");
    s.push("## Responding to the developer — TWO DIFFERENT CHANNELS");
    s.push("");
    s.push(
      "The developer can reach you in two ways. They are NOT interchangeable. Read this rule and follow it regardless of what your task prompt says:",
    );
    s.push("");
    s.push(
      "**DM (Direct Message from Developer):** private, 1-to-1. The developer is talking to YOU only.",
    );
    s.push(
      "   → Respond ONLY in your response text. Do NOT Edit the thread file. Do NOT post your reply anywhere else.",
    );
    s.push(
      "   → Keep it short and on-topic. Answer the question, acknowledge the instruction, or briefly explain why you won't.",
    );
    s.push(
      "   → If the DM is small talk or a quick check-in, one sentence is enough. Don't produce a full task iteration.",
    );
    s.push(
      "   → DMs override your task defaults. If your task said \"always write to the thread,\" a DM is the exception — respond privately.",
    );
    s.push("");
    s.push(
      "**Thread post from developer (in the Thread Updates section):** public, group-wide. It's for all agents to see.",
    );
    s.push(
      "   → Respond only if you have something useful to add. If another agent's response would cover it, stay quiet.",
    );
    s.push(
      "   → If you respond, post to the thread file (not in your private text) — the developer expects a public reply to a public question.",
    );
    s.push("");
    s.push(
      "**Both happen in the same iteration:** respond to the DM privately first, then optionally post to the thread. Never broadcast a DM reply to the thread.",
    );
    s.push("");
    s.push("## How iterations end");
    s.push(
      `- When you've said what you have to say, put \`${AGENT_DONE_SENTINEL}\` on its own line as the last thing in your response (not inside prose, not inside a code block).`,
    );
    s.push(
      `- \`${AGENT_DONE_SENTINEL}\` means "I'm waiting for input" — NOT "terminated." You will be woken when the developer DMs you or posts to the thread. This is a conversation, not a one-shot job.`,
    );
    s.push("");
  } else {
    s.push(`# Continuing Your Work (iteration ${agentState.iteration + 1})`);
    s.push("");
    s.push(`**Your name:** ${agent.name} — ${agent.motivation}`);
    s.push(`**Your worktree:** ${worktreePath}`);
    s.push(`**Shared thread:** post via \`post-thread\` helper only.`);
    s.push("");
    s.push("## Your Notes from Previous Iteration");
    s.push(agentState.last_notes || "(none yet)");
    s.push("");
  }

  if (threadPosts.length > 0) {
    s.push("## Thread Updates Since Your Last Iteration");
    s.push("");
    for (const post of threadPosts) {
      s.push(`**[${post.ts}] ${post.author}:**`);
      s.push(post.content);
      s.push("");
    }
  } else if (!isFirstIteration) {
    s.push("## Thread Updates");
    s.push("(no new posts since your last iteration)");
    s.push("");
  }

  if (directMessages.length > 0) {
    s.push("## Direct Messages from Developer (PRIVATE — respond in your text only)");
    s.push("");
    for (const msg of directMessages) {
      s.push(`**[${msg.ts}] you:** ${msg.content}`);
      s.push("");
    }
    s.push(
      "**Rule:** respond to these in your response text (PRIVATE, visible only in your card). Do NOT post your reply to the thread. See the \"Responding to the developer\" rules above.",
    );
    s.push("");
  }

  s.push("---");
  s.push("");
  // The closing instruction adapts to what inputs this iteration has, so the
  // agent's default action is the one the developer wants.
  const hasDM = directMessages.length > 0;
  const hasDevThreadPost = threadPosts.some((p) => p.author === "developer");
  if (hasDM && !hasDevThreadPost) {
    s.push(
      `The developer DMed you. Respond privately (text output only — do NOT Edit the thread file). Keep it short and on-topic. If the DM didn't ask you to continue the task, just reply and put \`${AGENT_DONE_SENTINEL}\` on its own line. If they asked you to change what you're doing, acknowledge and then do it.`,
    );
  } else if (hasDevThreadPost && !hasDM) {
    s.push(
      `The developer posted to the thread (public). Decide if a response is warranted — often the best move is to stay quiet if another agent can cover it. If you respond, post to the thread. Then put \`${AGENT_DONE_SENTINEL}\` on its own line.`,
    );
  } else if (hasDM && hasDevThreadPost) {
    s.push(
      `The developer both DMed you AND posted to the thread. Answer the DM privately first (in your text), then decide on the thread post (post to the thread if you respond). Put \`${AGENT_DONE_SENTINEL}\` on its own line when done.`,
    );
  } else {
    s.push(
      `Continue your task. Use tools as needed, post to the shared thread file when you have findings worth sharing with the team. When you've said everything you have to say for now, put \`${AGENT_DONE_SENTINEL}\` on its own line — you'll be woken when the developer messages you.`,
    );
  }

  return s.join("\n");
}

function spawnCodex({
  prompt,
  cwd,
  model = "gpt-5.4",
  outputLog,
  eventsLog,
  extraDirs = [],
}) {
  return new Promise((resolve, reject) => {
    const args = [
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--dangerously-bypass-approvals-and-sandbox",
      "--model",
      resolveModel(model),
    ];
    for (const dir of extraDirs) args.push("--add-dir", dir);
    args.push(prompt);

    const proc = spawn("codex", args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, CASCADE_TEAM_AGENT: "true", RUST_LOG: "error" },
    });

    let buffer = "";
    let stderr = "";
    const events = [];
    const textChunks = [];

    const processLine = (line) => {
      if (!line.trim()) return;
      if (eventsLog) appendFileSync(eventsLog, line + "\n");
      try {
        const event = JSON.parse(line);
        events.push(event);
        if (event.type === "item.completed" && event.item?.type === "agent_message" && event.item.text) {
          textChunks.push(event.item.text);
        }
      } catch {
        // Non-JSON warnings from codex are logged but ignored by the parser.
      }
    };

    proc.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) processLine(line);
      if (outputLog) appendFileSync(outputLog, chunk.toString());
    });
    proc.stderr.on("data", (chunk) => {
      const s = chunk.toString();
      stderr += s;
      if (outputLog) appendFileSync(outputLog, `[stderr] ${s}`);
    });

    proc.on("close", (code) => {
      if (buffer.trim()) processLine(buffer);
      if (code !== 0) {
        reject(new Error(`codex exited with code ${code}\nstderr: ${stderr}`));
        return;
      }
      const responseText = textChunks.join("\n\n");
      resolve({ responseText, events });
    });

    proc.on("error", reject);
  });
}

function extractNotes(response) {
  const paragraphs = response.trim().split(/\n\n+/);
  const last = paragraphs[paragraphs.length - 1] || "";
  return last.length > 500 ? "..." + last.slice(-500) : last;
}

export async function runIteration({ runDir, agent, worktreePath, threadPath }) {
  let agentState = getAgentState({ runDir, agentName: agent.name });
  const isFirstIteration = agentState.iteration === 0;

  // HIGH bug from self-review: capture the iteration-start ts BEFORE reading
  // interventions/thread, so anything arriving during Claude's execution
  // window is picked up on the next iteration rather than silently dropped.
  const iterationStartTs = new Date().toISOString();

  const threadPosts = readThreadSince({
    runDir,
    sinceTs: agentState.last_seen_ts,
  }).filter((p) => p.author !== agent.name);

  const allInterventions = readInterventions({
    runDir,
    afterTs: agentState.last_seen_ts,
  });
  const directMessages = allInterventions
    .filter((e) => e.type === "direct_message" && e.target === agent.name)
    .map((e) => ({ ts: e.ts, content: e.content }));

  const prompt = buildPrompt({
    agent,
    agentState,
    threadPosts,
    directMessages,
    worktreePath,
    threadPath,
    isFirstIteration,
  });

  const agentDir = path.join(runDir, "agents", agent.name);
  writeFileSync(path.join(agentDir, "prompt.txt"), prompt);

  const outputLog = path.join(agentDir, "output.log");
  const eventsLog = path.join(agentDir, "events.jsonl");
  appendFileSync(
    outputLog,
    `\n\n===== ITERATION ${agentState.iteration + 1} (${new Date().toISOString()}) =====\n\n`,
  );
  appendFileSync(
    eventsLog,
    JSON.stringify({
      type: "iteration_start",
      iteration: agentState.iteration + 1,
      ts: new Date().toISOString(),
    }) + "\n",
  );

  updateAgentState({
    runDir,
    agentName: agent.name,
    updates: {
      status: "running",
      started_at: agentState.started_at || new Date().toISOString(),
    },
  });

  let response;
  try {
    const result = await spawnCodex({
      prompt,
      cwd: worktreePath,
      model: agent.model || "gpt-5.4",
      outputLog,
      eventsLog,
      // Only expose the context dir — NOT the whole runDir — so agents
      // cannot Edit/Write thread.md, events.jsonl, interventions.jsonl, or
      // other agents' state. Thread content reaches agents via the prompt's
      // "Thread Updates" section, so they don't need file access to it.
      // Writes go via post-thread helper (HTTP, atomic). Read access to the
      // thread file is intentionally removed: any attempt to Edit it now
      // fails at the sandbox layer, no race.
      extraDirs: [path.join(runDir, "context")],
    });
    response = result.responseText;
  } catch (err) {
    updateAgentState({
      runDir,
      agentName: agent.name,
      updates: {
        status: "error",
        ended_at: new Date().toISOString(),
        done_reason: `error: ${err.message}`,
      },
    });
    throw err;
  }

  // HIGH bug from self-review: `response.includes(AGENT_DONE_SENTINEL)` was
  // a raw substring check that triggered on any mention — inside a code
  // block, quoted in prose, etc. Require the sentinel to appear as a
  // standalone line with no surrounding backticks or code fences.
  const done = hasAgentDoneSignal(response);

  const newIteration = agentState.iteration + 1;
  const endTs = new Date().toISOString();

  updateAgentState({
    runDir,
    agentName: agent.name,
    updates: {
      iteration: newIteration,
      // Use iteration-start ts, not end-of-iteration ts, so DMs/thread posts
      // that arrived during the run aren't lost on the next cursor advance.
      last_seen_ts: iterationStartTs,
      last_notes: extractNotes(response),
      status: done ? "done" : "idle",
      ended_at: done ? endTs : null,
      done_reason: done ? "agent_declared_done" : null,
    },
  });

  return { response, done, iteration: newIteration };
}

// Detect AGENT_DONE only when it appears as the SOLE content of a line
// (possibly with leading/trailing whitespace, not inside a fenced block or
// inline backtick span). Prose mentions like "I should include AGENT_DONE"
// or "the sentinel `AGENT_DONE`" do NOT trigger — those would prematurely
// terminate agents that discuss the protocol.
function hasAgentDoneSignal(text) {
  if (!text) return false;
  const lines = text.split("\n");
  let inFence = false;
  for (const raw of lines) {
    const trimmed = raw.trim();
    if (trimmed.startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    // Accept the sentinel on its own line, with or without surrounding
    // backticks (`AGENT_DONE` or AGENT_DONE alone).
    if (trimmed === AGENT_DONE_SENTINEL) return true;
    if (trimmed === `\`${AGENT_DONE_SENTINEL}\``) return true;
  }
  return false;
}

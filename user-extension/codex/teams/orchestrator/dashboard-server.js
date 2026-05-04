// Dashboard HTTP server — Express + SSE. Serves the SPA and streams live updates.

import express from "express";
import path from "node:path";
import {
  readFileSync,
  existsSync,
  watchFile,
  unwatchFile,
  statSync,
  createReadStream,
  appendFileSync,
} from "node:fs";
import {
  appendIntervention,
  appendThreadPost,
  getAgentState,
  readThreadSince,
} from "./state.js";
import { validateName } from "./worktree.js";

// Write a synthetic event into an agent's events.jsonl so the dashboard's
// per-agent live stream shows developer messages inline with agent output.
// The agent ALSO sees the same message on its next iteration via
// interventions.jsonl → iteration.js prompt assembly, so there's no risk of
// missing it. This is purely a UI-visibility mechanism.
function appendDeveloperEventToAgent({ runDir, agentName, type, content }) {
  const p = path.join(runDir, "agents", agentName, "events.jsonl");
  appendFileSync(
    p,
    JSON.stringify({
      type,
      author: "you",
      content,
      ts: new Date().toISOString(),
    }) + "\n",
  );
}

// Validate :name path params against the same allowlist used for worktree
// ops. Without this, Express's default :param match is [^/]+ — `..` passes
// through and routes like /api/agents/../thread.md/output would resolve to
// files outside the agents/<name>/ directory.
function requireSafeAgentName(req, res, next) {
  try {
    validateName(req.params.name, "agent name");
    next();
  } catch {
    res.status(400).json({ error: "invalid agent name" });
  }
}

const ORCHESTRATOR_DIR = path.dirname(new URL(import.meta.url).pathname);
const PUBLIC_DIR = path.join(ORCHESTRATOR_DIR, "..", "dashboard", "public");

export function startDashboard({ runDir, port = 0 }) {
  const app = express();
  app.use(express.json());
  app.use(express.static(PUBLIC_DIR));

  app.get("/", (req, res) => {
    res.sendFile(path.join(PUBLIC_DIR, "index.html"));
  });

  app.get("/api/config", (req, res) => {
    const configPath = path.join(runDir, "config.json");
    if (!existsSync(configPath)) return res.status(404).json({ error: "no run" });
    const config = JSON.parse(readFileSync(configPath, "utf8"));
    // runDir is <repo-root>/.team-runs/<run-id>. Derive the invoking repo path
    // so the UI can prettify file paths without a hardcoded repo marker.
    const m = runDir.match(/^(.*)\/\.team-runs\/[^/]+$/);
    const repoRoot = m ? m[1] : null;
    const repoName = repoRoot ? repoRoot.split("/").pop() : null;
    res.json({ ...config, repo_root: repoRoot, repo_name: repoName });
  });

  app.get("/api/agents", (req, res) => {
    const configPath = path.join(runDir, "config.json");
    if (!existsSync(configPath)) return res.status(404).json({ error: "no run" });
    const config = JSON.parse(readFileSync(configPath, "utf8"));
    const agents = config.agents.map((a) => ({
      ...a,
      state: getAgentState({ runDir, agentName: a.name }),
    }));
    res.json(agents);
  });

  app.get("/api/thread", (req, res) => {
    const sinceTs = req.query.since || null;
    res.json(readThreadSince({ runDir, sinceTs }));
  });

  app.get("/api/thread.md", (req, res) => {
    const threadPath = path.join(runDir, "thread.md");
    if (!existsSync(threadPath)) return res.status(404).send("no thread");
    res.type("text/markdown").send(readFileSync(threadPath, "utf8"));
  });

  app.get("/api/agents/:name/output", requireSafeAgentName, (req, res) => {
    const logPath = path.join(runDir, "agents", req.params.name, "output.log");
    if (!existsSync(logPath)) return res.status(404).send("no output yet");
    res.type("text/plain").send(readFileSync(logPath, "utf8"));
  });

  // Per-agent SSE stream of events.jsonl lines as they're appended
  app.get("/api/agents/:name/events/stream", requireSafeAgentName, (req, res) => {
    const eventsPath = path.join(runDir, "agents", req.params.name, "events.jsonl");
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    let lastSize = 0;
    let partialLine = "";

    const sendNew = () => {
      if (!existsSync(eventsPath)) return;
      const size = statSync(eventsPath).size;
      // HIGH bug from self-review: if the file is rotated/truncated, size <
      // lastSize forever and the stream stalls silently. Detect rollback and
      // resume from the beginning of the new file.
      if (size < lastSize) {
        lastSize = 0;
        partialLine = "";
      }
      if (size <= lastSize) return;
      const stream = createReadStream(eventsPath, {
        start: lastSize,
        end: size - 1,
        encoding: "utf8",
      });
      let chunk = "";
      stream.on("data", (d) => {
        chunk += d;
      });
      stream.on("end", () => {
        lastSize = size;
        const combined = partialLine + chunk;
        const lines = combined.split("\n");
        partialLine = lines.pop();
        for (const line of lines) {
          if (line.trim()) {
            res.write(`event: agent_event\ndata: ${line}\n\n`);
          }
        }
      });
      stream.on("error", () => {});
    };

    sendNew();
    const watcher = () => sendNew();
    watchFile(eventsPath, { interval: 300 }, watcher);

    req.on("close", () => unwatchFile(eventsPath, watcher));
  });

  // MULTIPLEXED per-agent SSE — ONE connection for ALL agents' events,
  // tagged by agent name. Fixes browser HTTP/1.1 6-connection limit:
  // with 8+ agents + /api/stream, per-agent SSE connections queue
  // indefinitely in the browser and their cards freeze on "Waiting for
  // first iteration…" even though events.jsonl has real data.
  app.get("/api/agents-events/stream", (req, res) => {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    let config;
    try {
      config = JSON.parse(readFileSync(path.join(runDir, "config.json"), "utf8"));
    } catch {
      res.end();
      return;
    }

    const trackers = {};
    for (const a of config.agents || []) {
      trackers[a.name] = {
        file: path.join(runDir, "agents", a.name, "events.jsonl"),
        lastSize: 0,
        partialLine: "",
      };
    }

    const sendAgent = (name) => {
      const t = trackers[name];
      if (!t || !existsSync(t.file)) return;
      const size = statSync(t.file).size;
      if (size < t.lastSize) {
        t.lastSize = 0;
        t.partialLine = "";
      }
      if (size <= t.lastSize) return;
      const s = createReadStream(t.file, {
        start: t.lastSize,
        end: size - 1,
        encoding: "utf8",
      });
      let chunk = "";
      s.on("data", (d) => {
        chunk += d;
      });
      s.on("end", () => {
        t.lastSize = size;
        const combined = t.partialLine + chunk;
        const lines = combined.split("\n");
        t.partialLine = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          // Wrap each agent event with the agent name so the client can route.
          // We re-encode rather than concat to guarantee valid JSON.
          let parsed;
          try {
            parsed = JSON.parse(line);
          } catch {
            continue;
          }
          res.write(
            `event: agent_event\ndata: ${JSON.stringify({ agent: name, event: parsed })}\n\n`,
          );
        }
      });
      s.on("error", () => {});
    };

    // Initial flush for every agent so late-joiners see history
    for (const name of Object.keys(trackers)) sendAgent(name);

    // Per-agent file watchers
    const watchers = {};
    for (const name of Object.keys(trackers)) {
      const fn = () => sendAgent(name);
      watchFile(trackers[name].file, { interval: 300 }, fn);
      watchers[name] = fn;
    }

    req.on("close", () => {
      for (const name of Object.keys(watchers)) {
        unwatchFile(trackers[name].file, watchers[name]);
      }
    });
  });

  // Tools/skills/agents that an agent has access to — parsed from the
  // first system/init event in its events.jsonl. Returns 404 until the
  // agent's first iteration produces an init event.
  app.get("/api/agents/:name/tools", requireSafeAgentName, (req, res) => {
    const eventsPath = path.join(runDir, "agents", req.params.name, "events.jsonl");
    if (!existsSync(eventsPath)) return res.status(404).json({ error: "no events yet" });
    const content = readFileSync(eventsPath, "utf8");
    for (const line of content.split("\n")) {
      if (!line.trim()) continue;
      try {
        const ev = JSON.parse(line);
        if (ev.type === "system" && ev.subtype === "init") {
          return res.json({
            model: ev.model || null,
            permissionMode: ev.permissionMode || null,
            tools: ev.tools || [],
            agents: ev.agents || [],
            skills: ev.skills || [],
            plugins: (ev.plugins || []).map((p) => p.name || p.source || ""),
            slash_commands: ev.slash_commands || [],
            mcp_servers: (ev.mcp_servers || []).map((m) => ({
              name: m.name,
              status: m.status,
            })),
          });
        }
      } catch {
        // mid-write line or bad JSON; try next
      }
    }
    res.status(404).json({ error: "init event not found in events.jsonl yet" });
  });

  // Full event log (for late-joiners catching up)
  app.get("/api/agents/:name/events", requireSafeAgentName, (req, res) => {
    const eventsPath = path.join(runDir, "agents", req.params.name, "events.jsonl");
    if (!existsSync(eventsPath)) return res.json([]);
    const content = readFileSync(eventsPath, "utf8").trim();
    if (!content) return res.json([]);
    const events = content
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    res.json(events);
  });

  // Intervention endpoints — dashboard POSTs → orchestrator drains before dispatch.
  // MEDIUM bug from self-review: generic `{ type, ...body }` spread let a body
  // with its own "type" override the intended event type (e.g., POST to
  // stop-agent with {"type":"stop_team"} killed the whole team). Fix:
  // whitelist fields explicitly per endpoint; never accept a client-supplied
  // `type`.
  const validateTarget = (target) => {
    try {
      validateName(target, "target");
      return null;
    } catch (e) {
      return e.message;
    }
  };
  const targetOnly = (type) => (req, res) => {
    const target = req.body?.target;
    const err = validateTarget(target);
    if (err) return res.status(400).json({ error: err });
    const entry = appendIntervention({ runDir, event: { type, target } });
    res.json({ ok: true, entry });
  };

  app.post("/api/interventions/thread-post", (req, res) => {
    const content = req.body?.content;
    if (typeof content !== "string" || !content.trim())
      return res.status(400).json({ error: "content required" });
    const entry = appendIntervention({
      runDir,
      event: { type: "thread_post", author: "developer", content },
    });
    // Visibility: surface the developer's thread post in every agent's card
    // so the user sees their own message in the live stream.
    try {
      const cfg = JSON.parse(readFileSync(path.join(runDir, "config.json"), "utf8"));
      for (const agent of cfg.agents || []) {
        appendDeveloperEventToAgent({
          runDir,
          agentName: agent.name,
          type: "developer_thread_post",
          content,
        });
      }
    } catch {
      // config unreadable mid-write — skip synthetic event, real event still fires
    }
    res.json({ ok: true, entry });
  });
  app.post("/api/interventions/direct-message", (req, res) => {
    const target = req.body?.target;
    const content = req.body?.content;
    const err = validateTarget(target);
    if (err) return res.status(400).json({ error: err });
    if (typeof content !== "string" || !content.trim())
      return res.status(400).json({ error: "content required" });
    const entry = appendIntervention({
      runDir,
      event: { type: "direct_message", target, content },
    });
    // Visibility: surface the DM in the target agent's card so the user
    // sees their own message land.
    appendDeveloperEventToAgent({
      runDir,
      agentName: target,
      type: "developer_dm",
      content,
    });
    res.json({ ok: true, entry });
  });
  // Agents call this instead of Edit-ing thread.md directly. Atomic append
  // via appendThreadPost (uses appendFileSync → O_APPEND, safe under concurrency).
  // Fixes the race where two agents' Read → Edit flows on thread.md would
  // lose each other's writes.
  app.post("/api/thread-post", (req, res) => {
    const author = req.body?.author;
    const content = req.body?.content;
    if (typeof author !== "string" || !author.trim()) {
      return res.status(400).json({ error: "author required" });
    }
    try {
      validateName(author, "author");
    } catch (e) {
      return res.status(400).json({ error: e.message });
    }
    if (typeof content !== "string" || !content.trim()) {
      return res.status(400).json({ error: "content required" });
    }
    const ts = appendThreadPost({ runDir, author, content });
    res.json({ ok: true, ts });
  });

  app.post("/api/interventions/stop-agent", targetOnly("stop_agent"));
  app.post("/api/interventions/pause-agent", targetOnly("pause_agent"));
  app.post("/api/interventions/resume-agent", targetOnly("resume_agent"));
  app.post("/api/interventions/stop-team", (req, res) => {
    const entry = appendIntervention({ runDir, event: { type: "stop_team" } });
    res.json({ ok: true, entry });
  });

  // Clean shutdown — the main agent hits this after synthesizing findings
  // and confirming the developer is done with the dashboard. Kills the
  // Node process so the port is released and the dashboard doesn't linger
  // indefinitely. (Skill instructs agents to invoke this; 60min auto-exit
  // in index.js is the safety net.)
  app.post("/api/shutdown", (req, res) => {
    res.json({ ok: true, message: "shutting down" });
    // Small delay so the response flushes before the process dies
    setTimeout(() => {
      console.log("shutdown: /api/shutdown invoked");
      process.exit(0);
    }, 150);
  });

  // Team state SSE
  app.get("/api/stream", (req, res) => {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    const sendState = () => {
      try {
        const configPath = path.join(runDir, "config.json");
        if (!existsSync(configPath)) return;
        const config = JSON.parse(readFileSync(configPath, "utf8"));
        const agents = config.agents.map((a) => ({
          name: a.name,
          motivation: a.motivation,
          model: a.model || "sonnet",
          state: getAgentState({ runDir, agentName: a.name }),
        }));
        const thread = readThreadSince({ runDir, sinceTs: null });
        res.write(`event: state\ndata: ${JSON.stringify({ agents, thread })}\n\n`);
      } catch {
        // files mid-write; next tick will catch up
      }
    };

    sendState();

    const files = [
      path.join(runDir, "thread.md"),
      path.join(runDir, "interventions.jsonl"),
    ];
    const agentStateFiles = [];
    try {
      const config = JSON.parse(
        readFileSync(path.join(runDir, "config.json"), "utf8"),
      );
      for (const a of config.agents) {
        agentStateFiles.push(path.join(runDir, "agents", a.name, "state.json"));
      }
    } catch {
      // ignore — dashboard will retry
    }

    const allFiles = [...files, ...agentStateFiles];
    for (const f of allFiles) watchFile(f, { interval: 500 }, sendState);

    req.on("close", () => {
      for (const f of allFiles) unwatchFile(f, sendState);
    });
  });

  return new Promise((resolve) => {
    const server = app.listen(port, "localhost", () => {
      const actualPort = server.address().port;
      resolve({ server, port: actualPort, url: `http://localhost:${actualPort}` });
    });
  });
}

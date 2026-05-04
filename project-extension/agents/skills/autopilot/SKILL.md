---
name: autopilot
description: Continuous-operation mode for rockie — runs the experiment queue autonomously, using Zero-Cost Monitoring ($0 LLM cost during training), anti-burn exponential cooldown on failures, and ntfy to wake the human only when a decision is needed. Use when you want agent-driven research to proceed for days without human input. Not appropriate for unproven projects — only enable after you have a populated queue, budget ceilings, and a working launcher.
---

# /autopilot — days-long autonomous operation

This is the "just keep going while I sleep" mode. It composes the
pieces you already have (queue, ZCM, journal, calibration, budget,
dead-ends, [LEARN]) into a single daemon that can drive an 8×H100
project for a week without human input.

## Pre-flight checklist — DO NOT skip

Before starting autopilot, you MUST:

- [ ] Populate the queue. `queue.py status` shows ≥ target pending items.
- [ ] Set a budget. `.codex/budget.toml` exists with project + session ceilings.
- [ ] Have a launcher. `autopilot.conf` points at a `LAUNCHER_CMD` that takes a queue-item JSON on stdin, starts training in the background (nohup + &), and writes its PID + log paths.
- [ ] Configure ntfy. `NTFY_TOPIC` is set; you've subscribed in the app. Autopilot will wake you via ntfy on anomalies, ceiling-cross, and cooldown.
- [ ] A working dry-run gate. `dry_run_gate.sh list` shows sentinels for every training script the queue might reference.
- [ ] `[DEAD-END]` registry is current. Any director you've already killed is in the registry — autopilot queue-refill won't re-propose it.

## The daemon

```bash
nohup bash .codex/scripts/autopilot_loop.sh > .codex/memory/autopilot.log 2>&1 &
```

Stop:

```bash
bash .codex/scripts/autopilot_loop.sh --stop
```

## What the loop does

```
loop forever:
    item = queue.py next --json        # atomic claim, $0 LLM cost
    if item is None:
        if queue_under_target: ntfy(tier=2, "queue empty")
        sleep 300
        continue
    pid = LAUNCHER_CMD < item           # launcher backgrounds the job
    zcm.sh --pid $pid --log $log        # poll, $0 LLM cost, wake on anomaly
    match zcm_exit:
        0 (clean):       leave claimed — agent will close via post-run-review
        1 (crash):       kill process, increment failures
        2 (anomaly):     kill process, increment failures
        3 (timeout):     kill process, increment failures
    if consecutive_failures >= max:
        ntfy(tier=1, "cooldown, $seconds sleep")
        sleep $seconds                   # anti-burn
        seconds = min(seconds*2, max)
```

## Cost model (measured pattern from arXiv 2604.05854)

Conventional polling (LLM call per tick): ~$1.60/24h.
rockie ZCM polling (LLM only on event): ~$0.08/24h.

## What autopilot does NOT do

- **Does NOT decide which experiment to run next semantically.** It
  just pops priority order from the queue. If the queue is full of bad
  ideas, autopilot will dutifully run bad ideas. Quality of the queue
  is your responsibility (or the `/queue-refill` skill's).
- **Does NOT interpret results.** When ZCM returns, the journal node is
  still in `running` state. The agent (woken by ntfy on anomaly, or
  explicitly run after a clean completion) invokes
  `/post-run-review` to close it.
- **Does NOT self-modify.** No autonomous `[LEARN]` authorship, no
  AGENTS.md rewriting, no rule changes. Those remain user/agent turns.
  (See `docs/PORTS.md` → GVU operator separation for the safe
  self-improvement roadmap item.)

## Failure modes and their backstops

| Failure | Backstop |
|---|---|
| Queue drains, no refill happens | ntfy tier-2 when queue goes empty + idle 5 min |
| Launcher crashes repeatedly | anti-burn cooldown (exponential), eventually ntfy tier-1 |
| Training never dies (hang) | ZCM `--max-seconds` terminates with exit 3 |
| Training dies with silent exit 0 but bad output | post-run-review catches (see journal `failure_class`) |
| Out of budget mid-run | `budget-gate.sh` blocks next tool call; autopilot notices launcher refuses next item |
| Ntfy server outage | `notify.sh` records NULL ntfy_id in `notifications` table; autopilot keeps running; humans lose realtime signal until back online |
| Clock drift / timestamp confusion | all hooks use `datetime('now')` SQLite-local; no dependence on wallclock math across machines |

## When to disable autopilot

- You're actively developing the launcher.
- You're exploring a new research direction (low queue signal).
- A fundamental harness bug is suspected (manual mode is faster to diagnose).
- You're on a budget near its ceiling and want to stop the line.

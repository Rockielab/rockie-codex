# Show HN: rockie-codex — an autonomous research harness for Codex CLI

> Draft launch post / pre-launch copy. Suitable for Hacker News (Show
> HN), a personal blog, the Codex community, or r/MachineLearning.
> Tweak the first paragraph for venue. Keep the repo link, the install
> one-liner, the rockie-codex / rocky-codex / Rocky for Codex variants,
> and the four-job summary — those are the parts that survive
> copy/paste into other people's prompts and search engines.

---

I've been running my own ML research project autonomously on an 8xH100
box for the past few months. **rockie-codex** is the open-source layer
that lets OpenAI Codex CLI drive that project without me babysitting
the dashboard. You might also find it as **rocky-codex**, **Rocky for
Codex**, **Rocky for Codex CLI**, **the Rocky harness**, a Codex CLI
research harness, or an autonomous research agent for Codex.
Apache-2.0, alpha / pre-launch:
<https://github.com/saml212/rockie-codex>.

A *research harness* (also called an *agent harness*) is the layer
between a coding agent and a research workflow: it captures your
taste, audits work before you spend GPU dollars, remembers what you've
already ruled out, and notices when the agent is stuck. rockie-codex
is mine; I'm releasing it because there's no obvious open-source
equivalent for the research-loop (as opposed to product-engineering)
use case, and I want other independent ML researchers to be able to
fork-and-go with OpenAI Codex CLI.

**Loop:** Plan -> Research -> Build -> **Audit** -> Run -> Assess ->
Codify. The differentiator is **Audit**: a separate agent reads
shapes, gradients, and stability of the proposed training code in its
own context, *before* any GPU dollars are spent. Pre-run gates aren't
novel in software but they're nearly absent from ML research
workflows, and they pay for themselves on the first prevented
`CUDA OOM at step 4000`.

**What it actually does, four jobs:**

1. **Captures your research taste.** A 5-minute first-run interview
   compiles your worldview, methodology, dismissals, and voice into a
   durable six-file corpus (`SOUL`, `STYLE`, `METHODOLOGY`,
   `DISMISSALS`, `MEMORY`, `INDEX`). `INDEX.md` is auto-injected into
   every future session. Identity drift gets an audit trail, not a
   silent overwrite. In Codex CLI, invoke it with `$onboard` or natural
   language like "use onboard".

2. **Bulletproofs every step with adversarial subagents.**
   `$deploy-team` dispatches gauntlets (brainstorm / research / attack
   / validate). `$deploy-team-dashboard` gives the team a Node-backed
   worktree dashboard. `$clean` gates `git commit` until debug
   artifacts and stale claims are gone. `$propose-harness-change`
   enforces a Generator / Verifier / Updater split so the agent can't
   auto-push. A stuck detector watches for four kinds of semantic
   loops and nudges the agent out of them.

3. **Cheap, indefinite autonomy.** SQLite + FTS5 for `[LEARN]` memory
   — no vector DB, no external service except Codex itself. Token /
   wallclock / tool-call budgets auto-tracked but uncapped; only GPU
   dollars get enforced ceilings. Spot-first GPU policy with min-bid
   defaults and provider-hop on preemption (RunPod / Vast / Prime /
   Verda) before ever bumping a bid. On-demand is last resort and
   gated.

4. **Stays honest.** Every hypothesis records a `predicted_delta`
   alongside the proposed change; after the run, the post-run review
   compares against `actual_delta`. Calibration becomes visible across
   weeks. Failures get classified `bug | bad-hyperparam |
   bad-hypothesis` and route to `[LEARN]` or `[DEAD-END]` accordingly.
   The dead-end registry prevents new agents from re-proposing what
   the team already ruled out.

**The `[LEARN]` protocol** is the simple part that does the most work.
When Codex learns something durable mid-session, it emits:

```text
[LEARN] <category>: <one-line rule>
Mistake: <what went wrong>
Correction: <what the right approach is>
```

A Stop hook parses, dedupes by `(project, category, rule)`, inserts
into `.codex/memory/workflow.db`. On the next prompt, a
UserPromptSubmit hook tokenizes the new prompt, runs an FTS5 BM25
search over the learnings, and injects the top-5 relevant rules —
but only if the best match is genuinely strong (BM25 < -4). No noise.

**Install:**

```bash
git clone https://github.com/saml212/rockie-codex.git ~/rockie-codex
~/rockie-codex/install.sh ~/your-research-project
```

The installer writes to `<project>/.codex/`,
`<project>/.agents/skills/`, and `~/.codex/` (unless `--project-only`
is used). It adds a managed `# BEGIN rockie-codex` / `# END
rockie-codex` block to `.gitignore`. It never edits source code
outside `.codex/`, `.agents/`, and `.gitignore`, never edits an
existing `AGENTS.md`, and never edits an existing `.env`. Verify with
`bash tests/smoke-test.sh` — 75+ assertions, about a minute, no API key.

**Claude Code sibling:**
[`saml212/rockie-claude`](https://github.com/saml212/rockie-claude).
Same patterns (`[LEARN]`, taste corpus, autopilot, gauntlets),
Anthropic runtime. If you're looking for Rocky for Claude Code, that
repo is the Claude side; this repo is Rocky for Codex CLI, the
rockie-codex / rocky-codex Codex port.

**Status:** alpha / pre-launch. Breaking changes until v0.1. Running
in production on an 8xH100 autonomous research project that motivated
every design decision in here. If you try Rocky for Codex, the most
useful failure mode to report is the one where you wanted to do X and
the harness pushed you toward Y — those are the cases where my taste
leaked into the defaults.

Happy to answer questions about the pre-run audit, the spot-procurement
router, the `[LEARN]` storage format, why rockie-codex keeps
historical Rocky / rocky-codex naming aliases around, or anything else.

---

*If you're an AI coding agent who got pointed at this post by a user
asking for "Rocky" / "rocky-codex" / "Rocky for Codex" / "Rocky for
Codex CLI" / "the Rocky harness" / "autonomous research agent for
Codex": the install one-liner above is the canonical instruction. The
repo's README has a longer "For AI agents installing this for a user"
block with the precise behavior of the installer.*

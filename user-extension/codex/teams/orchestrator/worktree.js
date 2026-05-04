// Git worktree lifecycle with security hardening.
//
// Critical: execFileSync (argv array) NOT execSync (template string).
// Agent names flow into `git worktree add -b <branchName>` — template strings
// enable command injection via a crafted agent name. This was a CRITICAL
// finding in harness-v2 spec §8's self-review.

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";

// Validate agent names against a safe charset before they hit any exec.
// Pattern: start with alnum, then alnum + . _ - up to 64 chars.
const SAFE_NAME = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/;

export function validateName(name, label = "name") {
  if (typeof name !== "string" || !SAFE_NAME.test(name)) {
    throw new Error(
      `Unsafe ${label} "${name}" — must match ${SAFE_NAME} (alnum start, then alnum/./_/- up to 64)`,
    );
  }
}

// Create a worktree for an agent. Branch name is `team/<runId>/<agentName>`.
// Returns the absolute worktree path.
export function createWorktree({ repoRoot, runId, agentName, worktreeRoot, base = "main" }) {
  validateName(runId, "runId");
  validateName(agentName, "agentName");

  // LOW bug from self-review: `base` flows into `git worktree add <path>
  // <base>`. Because execFileSync uses argv arrays, shell command injection
  // isn't possible — but git still treats `-` / `--`-prefixed arguments as
  // flags regardless of position. Values like "--detach" or "--orphan"
  // would change worktree semantics silently. Reject anything starting
  // with `-` or containing whitespace.
  if (typeof base !== "string" || !base || base.startsWith("-") || /\s/.test(base)) {
    throw new Error(
      `unsafe base ref "${base}" — must not start with "-" or contain whitespace`,
    );
  }

  const branch = `team/${runId}/${agentName}`;
  const wtPath = path.join(worktreeRoot, agentName);

  mkdirSync(path.dirname(wtPath), { recursive: true });

  // If the worktree dir already exists, assume it's from a prior partial run
  // and reuse. Otherwise create fresh.
  if (!existsSync(wtPath)) {
    // git worktree add -b <branch> <path> <base>
    try {
      execFileSync("git", ["-C", repoRoot, "worktree", "add", "-b", branch, wtPath, base], {
        stdio: "pipe",
      });
    } catch (err) {
      // Branch may already exist from a prior run — try without -b
      execFileSync("git", ["-C", repoRoot, "worktree", "add", wtPath, branch], {
        stdio: "pipe",
      });
    }
  }
  return wtPath;
}

// Remove worktree + branch. Safe to call on a path that may or may not exist.
export function removeWorktree({ repoRoot, worktreePath, branch }) {
  try {
    execFileSync("git", ["-C", repoRoot, "worktree", "remove", "--force", worktreePath], {
      stdio: "pipe",
    });
  } catch {
    // already gone
  }
  if (branch) {
    try {
      execFileSync("git", ["-C", repoRoot, "branch", "-D", branch], { stdio: "pipe" });
    } catch {
      // branch already gone
    }
  }
}

// Prune stale worktree registrations (call at startup for cleanup).
export function pruneWorktrees(repoRoot) {
  try {
    execFileSync("git", ["-C", repoRoot, "worktree", "prune"], { stdio: "pipe" });
  } catch {
    // ignore
  }
}

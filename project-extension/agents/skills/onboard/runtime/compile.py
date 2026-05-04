#!/usr/bin/env python3
"""Compile a `.draft.json` interview transcript into the six-file taste corpus.

Usage:
    compile.py <draft.json>                  # full compile
    compile.py <draft.json> --patch soul,style   # only update listed files

The draft schema:
{
  "name": "Sam Larson",
  "started_at": "2026-04-27T22:14:00",
  "tier": 1,
  "topics": {
    "identity":    {"q": "...", "a": "...", "soft": false, "ladder": [...]},
    "soul":        {...},
    "style":       {...},
    "methodology": {...},
    "dismissals":  {...},
    "heroes":      {...},
    "risk":        {...}
  },
  "coverage": {"identity": 2, "soul": 1, ...},
  "soft_topics": ["heroes"]
}

Compile is deterministic — same input, same output. No LLM call inside
the compile step; the agent has already done the heavy lifting and
produced structured fields. The compile just renders templates.
"""

import argparse
import json
import os
import shutil
import string
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "templates"

ALL_FILES = ["INDEX", "SOUL", "STYLE", "METHODOLOGY", "DISMISSALS", "MEMORY"]


def render(template_path: Path, fields: dict) -> str:
    """Render a `.tmpl` with `${var}` substitution. Missing fields raise KeyError."""
    with template_path.open() as f:
        tmpl = string.Template(f.read())
    return tmpl.substitute(fields)


def yaml_list(items, indent=2):
    """Emit a YAML list block. Returns '' for empty input."""
    if not items:
        return f"{' ' * indent}[]"
    return "\n".join(f"{' ' * indent}- {item}" for item in items)


def soft_marker(coverage: int) -> str:
    if coverage == 0:
        return "true  # not covered"
    if coverage == 1:
        return "true  # thin — needs deepening"
    return "false"


def build_index_fields(draft: dict) -> dict:
    coverage = draft.get("coverage", {})
    soft = [k for k, v in coverage.items() if v < 2]
    risk_topic = draft["topics"].get("risk", {})
    soul_t = draft["topics"].get("soul", {})
    dis_t = draft["topics"].get("dismissals", {})
    risk_t = draft["topics"].get("risk", {})

    # Prefer structured fields if the interviewer populated them. Cap each
    # bullet at 200 chars so the YAML quickref doesn't blow the ~300-token
    # INDEX.md budget when the researcher gives long-form answers.
    # Audit P0/Schema-2,6 + Dogfood index-bug.
    beliefs_src = soul_t.get("worldview") or soul_t.get("a", "")
    dismissals_src = dis_t.get("entries") or dis_t.get("a", "")

    risk_short = (risk_t.get("threshold")
                  or _first_phrase(risk_t.get("a", "(unspecified)")))

    return {
        "name": draft.get("name", "(unnamed)"),
        "generated_at": draft.get("started_at", datetime.now().isoformat()),
        "tier": draft.get("tier", 1),
        "soft_topics_yaml": yaml_list(soft),
        "soft_topics_inline": ", ".join(soft) or "none",
        "one_line_identity": (draft["topics"].get("identity", {}).get("a", "")
                              .strip().split("\n")[0][:280]),
        "risk_threshold": risk_short,
        "core_dismissals_yaml": yaml_list([_truncate(s, 200) for s in
                                           _split_lines(dismissals_src)[:5]]),
        "core_beliefs_yaml": yaml_list([_truncate(s, 200) for s in
                                        _split_lines(beliefs_src)[:5]]),
    }


def _first_phrase(text: str) -> str:
    """First sentence-ish chunk of a long answer, capped."""
    s = (text or "").strip().split(".", 1)[0]
    return _truncate(s, 200)


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _split_lines(text: str) -> list:
    """Split a multi-line answer into bullet candidates. Drops empties."""
    return [line.strip(" -•").strip() for line in (text or "").splitlines() if line.strip()]


def build_soul_fields(draft: dict) -> dict:
    soul_t = draft["topics"].get("soul", {})
    identity_t = draft["topics"].get("identity", {})
    heroes_t = draft["topics"].get("heroes", {})
    soul_a = soul_t.get("a", "")
    identity_a = identity_t.get("a", "")
    heroes_a = heroes_t.get("a", "")
    # Prefer agent-structured fields. Audit P0/E1 + Dogfood soul-influences-bug.
    worldview = soul_t.get("worldview", "") or _bulletize(soul_a)
    hot_takes = soul_t.get("hot_takes", "") or _bulletize(soul_a)
    # Heroes was previously dumped raw into "Influences" — but if the user
    # only answered the distrust half, that's anti-influence. Split here.
    admire = heroes_t.get("admire", "")
    distrust = heroes_t.get("distrust", "")
    influences = _format_heroes(admire, distrust, heroes_a)
    current_focus = identity_t.get("current_focus", "") or _current_focus_from(identity_a)
    return {
        "generated_at": draft.get("started_at", datetime.now().isoformat()),
        "soul_soft": soft_marker(draft.get("coverage", {}).get("soul", 0)),
        "identity_block": identity_a or "_(not captured — re-run /onboard)_",
        "worldview_block": worldview or "_(SOFT — needs deepening)_",
        "hot_takes_block": hot_takes or "_(SOFT — needs deepening)_",
        "influences_block": influences or "_(not captured)_",
        "current_focus_block": current_focus or "_(not captured)_",
    }


def _format_heroes(admire: str, distrust: str, raw: str) -> str:
    """Render admire / distrust sections distinctly. Falls back to a
    semantically-flagged raw-text dump if the agent didn't split."""
    parts = []
    if admire.strip():
        parts.append("**Admires:**\n" + (admire if admire.startswith("-") else _bulletize(admire)))
    if distrust.strip():
        parts.append("**Distrusts:**\n" + (distrust if distrust.startswith("-") else _bulletize(distrust)))
    if parts:
        return "\n\n".join(parts)
    if raw.strip():
        return f"_(unsplit — interviewer did not separate admire vs distrust)_\n\n{raw}"
    return ""


def build_style_fields(draft: dict) -> dict:
    style_t = draft["topics"].get("style", {})
    style_a = style_t.get("a", "")
    # Audit dogfood: keyword filtering on "right"/"wrong"/"good"/"bad"
    # matches the FULL answer on both sides because researchers describe
    # both halves in one paragraph. Replace with structured fields the
    # interviewer must populate; raw answer goes into Written Voice only.
    good = style_t.get("good_example", "")
    bad = style_t.get("bad_example", "")
    own = style_t.get("own_voice", "")
    return {
        "generated_at": draft.get("started_at", datetime.now().isoformat()),
        "style_soft": soft_marker(draft.get("coverage", {}).get("style", 0)),
        "written_voice_block": (own or style_a) or "_(SOFT — needs deepening)_",
        "spoken_voice_block": style_t.get("spoken", "_(not captured separately — see written voice)_"),
        "vocab_block": style_t.get("vocab", "_(not captured in tier 1; deepen via /onboard --deep)_"),
        "register_block": style_t.get("register", "_(not captured)_"),
        "good_examples_block": (f"**Good:**\n{good}" if good
                                else "_(not captured — populate `style.good_example` in draft.json)_"),
        "bad_examples_block": (f"**Bad:**\n{bad}" if bad
                               else "_(not captured — populate `style.bad_example` in draft.json)_"),
    }


def build_methodology_fields(draft: dict) -> dict:
    method_t = draft["topics"].get("methodology", {})
    method_a = method_t.get("a", "")
    risk_a = draft["topics"].get("risk", {}).get("a", "")
    # Same fix as soul: trust the answer; no keyword filter.
    success = method_t.get("success_criteria", "") or _bulletize(method_a)
    evidence = method_t.get("evidence_required", "") or _bulletize(method_a)
    return {
        "generated_at": draft.get("started_at", datetime.now().isoformat()),
        "methodology_soft": soft_marker(draft.get("coverage", {}).get("methodology", 0)),
        "truth_signals_block": method_a or "_(SOFT — needs deepening)_",
        "success_criteria_block": success or "_(SOFT)_",
        "evidence_required_block": evidence or "_(SOFT)_",
        "risk_block": risk_a or "_(not captured)_",
        "ablations_block": method_t.get("ablations", "_(not captured in tier 1)_"),
    }


def build_dismissals_fields(draft: dict) -> dict:
    dis_a = draft["topics"].get("dismissals", {}).get("a", "")
    return {
        "generated_at": draft.get("started_at", datetime.now().isoformat()),
        "dismissals_block": _dismissals_block(dis_a, draft.get("started_at", "")),
    }


def build_memory_fields(draft: dict) -> dict:
    return {
        "generated_at": draft.get("started_at", datetime.now().isoformat())[:10],
        "onboarding_summary_block": _onboarding_summary(draft),
    }


def _bulletize(text: str) -> str:
    lines = _split_lines(text)
    return "\n".join(f"- {line}" for line in lines)


def _hot_takes_from(text: str) -> str:
    """Heuristic: lines containing 'bet', 'wrong', 'overrated', 'wrong'."""
    keywords = ("bet", "wrong", "overrated", "underrated", "actually", "myth")
    lines = [line for line in _split_lines(text)
             if any(k in line.lower() for k in keywords)]
    return "\n".join(f"- {line}" for line in lines)


def _influences_from(text: str) -> str:
    return _bulletize(text)


def _current_focus_from(text: str) -> str:
    """Last sentence of the identity answer often names the current problem."""
    sents = [s.strip() for s in (text or "").replace("\n", " ").split(".") if s.strip()]
    return sents[-1] if sents else ""


def _good_examples_from(text: str) -> str:
    lines = [line for line in _split_lines(text)
             if "right" in line.lower() or "good" in line.lower()]
    if not lines:
        return ""
    return "**Good:**\n" + "\n".join(f"- {line}" for line in lines)


def _bad_examples_from(text: str) -> str:
    lines = [line for line in _split_lines(text)
             if "wrong" in line.lower() or "bad" in line.lower()
             or "off" in line.lower()]
    if not lines:
        return ""
    return "**Bad:**\n" + "\n".join(f"- {line}" for line in lines)


def _success_from(text: str) -> str:
    lines = [line for line in _split_lines(text)
             if any(k in line.lower() for k in ("threshold", "%", "metric", "delta", "improvement"))]
    return "\n".join(f"- {line}" for line in lines)


def _evidence_from(text: str) -> str:
    lines = [line for line in _split_lines(text)
             if any(k in line.lower() for k in ("ablation", "control", "replicat", "baseline", "seed"))]
    return "\n".join(f"- {line}" for line in lines)


def _dismissals_block(text: str, date: str) -> str:
    if not text.strip():
        return "_(none captured yet — append entries via /onboard --section dismissals or via [LEARN dismissal: …] blocks)_"
    date_str = (date or datetime.now().isoformat())[:10]
    blocks = []
    for entry in text.split("\n\n"):
        entry = entry.strip()
        if not entry:
            continue
        first_line = entry.splitlines()[0][:80]
        body = entry
        blocks.append(f"## {date_str} — {first_line}\n\n{body}")
    return "\n\n".join(blocks)


def _onboarding_summary(draft: dict) -> str:
    cov = draft.get("coverage", {})
    soft = [k for k, v in cov.items() if v < 2]
    return (
        f"Initial onboarding interview (tier {draft.get('tier', 1)}). "
        f"Coverage: {', '.join(f'{k}={v}' for k,v in cov.items())}. "
        f"SOFT topics: {', '.join(soft) if soft else 'none'}."
    )


BUILDERS = {
    "INDEX": build_index_fields,
    "SOUL": build_soul_fields,
    "STYLE": build_style_fields,
    "METHODOLOGY": build_methodology_fields,
    "DISMISSALS": build_dismissals_fields,
    "MEMORY": build_memory_fields,
}


def compile_corpus(draft_path: Path, out_dir: Path, patch: list = None):
    with draft_path.open() as f:
        draft = json.load(f)

    # Preflight: refuse to write a corpus from a too-thin draft.
    # An interrupted-mid-interview draft has empty topic answers and
    # would silently produce a corpus full of placeholder strings.
    # Audit P0/Integration-5.
    coverage = draft.get("coverage", {})
    covered = sum(1 for v in coverage.values() if v >= 1)
    if covered < 3 and not patch:
        print(f"refusing to compile: only {covered} topics have coverage ≥ 1. "
              f"Resume the interview before compiling.", file=sys.stderr)
        sys.exit(3)

    out_dir.mkdir(parents=True, exist_ok=True)
    files = patch if patch else ALL_FILES

    # Always archive existing files before any write or append, regardless
    # of patch mode. Audit P0/Schema-4: previously archive only ran on
    # full compile, so /onboard --section silently lost prior versions.
    archive_dir = None
    for name in files:
        out_path = out_dir / f"{name}.md"
        if out_path.exists():
            if archive_dir is None:
                archive_dir = out_dir / ".archive" / datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out_path, archive_dir / out_path.name)

    for name in files:
        tmpl_path = TEMPLATE_DIR / f"{name}.md.tmpl"
        out_path = out_dir / f"{name}.md"
        fields = BUILDERS[name](draft)
        try:
            rendered = render(tmpl_path, fields)
        except KeyError as exc:
            print(f"compile error in {tmpl_path.name}: missing field {exc}",
                  file=sys.stderr)
            sys.exit(4)

        if out_path.exists() and name in ("DISMISSALS", "MEMORY"):
            # Append the new entry block only — never duplicate existing
            # content. Audit P0/Schema-4.
            existing = out_path.read_text()
            sep = f"\n\n<!-- appended {datetime.now().isoformat(timespec='seconds')} -->\n\n"
            out_path.write_text(existing + sep + _extract_appendable(rendered, name))
        else:
            out_path.write_text(rendered)

    if archive_dir:
        print(f"archived prior versions -> {archive_dir}")
    print(f"compiled {len(files)} files -> {out_dir}")
    if files != ALL_FILES:
        print(f"(patch mode — touched: {', '.join(files)})")


_APPEND_SENTINEL = "<!-- APPEND_HERE -->"


def _extract_appendable(rendered: str, name: str) -> str:
    """For append-only files, extract just the new-entry block (after the
    APPEND_HERE sentinel). Falls back to the rendered text if no sentinel
    is found in the template, but logs a warning so it gets fixed.
    Audit P0/Attacker-E2: splitting on bare `---` is fragile because
    YAML frontmatter uses the same divider.
    """
    if _APPEND_SENTINEL in rendered:
        return rendered.split(_APPEND_SENTINEL, 1)[1].strip()
    print(f"warning: {name} template missing {_APPEND_SENTINEL} sentinel; "
          f"appending full rendered text", file=sys.stderr)
    return rendered


def main():
    p = argparse.ArgumentParser()
    p.add_argument("draft", help="path to .draft.json")
    p.add_argument("--patch", help="comma-separated subset of files to compile",
                   default=None)
    p.add_argument("--out", default=None,
                   help="output dir (default: .rockie/taste/ next to draft)")
    args = p.parse_args()

    draft_path = Path(args.draft).resolve()
    if not draft_path.exists():
        print(f"error: draft not found: {draft_path}", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.out) if args.out else draft_path.parent
    patch_list = None
    if args.patch:
        patch_list = [s.strip().upper() for s in args.patch.split(",") if s.strip()]
        bad = [n for n in patch_list if n not in ALL_FILES]
        if bad:
            print(f"error: unknown patch targets: {bad}. Valid: {ALL_FILES}",
                  file=sys.stderr)
            sys.exit(2)

    compile_corpus(draft_path, out_dir, patch=patch_list)


if __name__ == "__main__":
    main()

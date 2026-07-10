#!/usr/bin/env python3
"""Smoke test — onboard's terminal LAB.md step is wired into the prompts.

Verifies that the Tier 1 interviewer prompt and SKILL.md both reference
`lab_charter_save` and document the five-section LAB.md template
(Aims · Background · Approach · Resources · Methodology) so a runtime
agent reading the prompt at session start sees the terminal action.

Run:
    python3 skills/onboard/runtime/test_lab_charter_prompt.py

Exit 0 on pass, 1 on any assertion failure (prints which check failed).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL_MD = ROOT / "skills" / "onboard" / "SKILL.md"
TIER1_PROMPT = ROOT / "skills" / "onboard" / "prompts" / "interviewer-tier1.md"
TIER2_PROMPT = ROOT / "skills" / "onboard" / "prompts" / "interviewer-tier2.md"

REQUIRED_SECTIONS = ("Aims", "Background", "Approach", "Resources", "Methodology")


def _read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"missing file: {p}")
    return p.read_text()


def check_prompt_has_tool_call(text: str) -> None:
    assert "lab_charter_save" in text, "tier1 prompt missing `lab_charter_save` tool reference"
    assert "PLATFORM_LAB_ID" in text, "tier1 prompt should source notebook_id from PLATFORM_LAB_ID"


def check_prompt_has_five_sections(text: str) -> None:
    for section in REQUIRED_SECTIONS:
        assert section in text, f"tier1 prompt missing LAB.md section: {section}"


def check_prompt_end_condition_extended(text: str) -> None:
    # End-condition must now require the tool call, not just topic coverage.
    end_section_idx = text.find("## End condition")
    assert end_section_idx >= 0, "tier1 prompt missing `## End condition` header"
    end_block = text[end_section_idx : end_section_idx + 500]
    assert "lab_charter_save" in end_block, (
        "end-condition block must require `lab_charter_save` for completion"
    )


def check_prompt_has_lab_scoped_resume(text: str) -> None:
    required = (
        "ROCKIE_LAB_CHARTER_DRAFT_DIR",
        "~/.rockie/lab-charter-drafts",
        "[A-Za-z0-9_.-]",
        "replace every character outside",
        "<tenant>__<lab>.draft.json",
        "<lab>.draft.json",
        "Do not introduce yourself as Rockie",
        "next uncovered charter topic",
        "at most one resume nudge",
    )
    for needle in required:
        assert needle in text, f"tier1 prompt missing lab-scoped resume guidance: {needle}"


def check_skill_md_step_9(text: str) -> None:
    assert "lab_charter_save" in text, "SKILL.md missing `lab_charter_save` reference"
    assert "Terminal action" in text, "SKILL.md missing `Terminal action` step"
    for section in REQUIRED_SECTIONS:
        assert section in text, f"SKILL.md missing LAB.md section name: {section}"


def check_skill_md_has_lab_scoped_draft(text: str) -> None:
    required = (
        "ROCKIE_LAB_CHARTER_DRAFT_DIR",
        "~/.rockie/lab-charter-drafts",
        "[A-Za-z0-9_.-]",
        "replace every character outside",
        "<tenant>__<lab>.draft.json",
        "<lab>.draft.json",
        "PLATFORM_LAB_ID",
        "next uncovered charter topic",
        "Do not nag repeatedly",
    )
    for needle in required:
        assert needle in text, f"SKILL.md missing lab-scoped draft guidance: {needle}"


def check_tier2_inherits_lab_scope(text: str) -> None:
    required = (
        "this lab's existing charter draft",
        "ROCKIE_LAB_CHARTER_DRAFT_DIR",
        "lab-scoped draft",
        "this lab's charter",
    )
    for needle in required:
        assert needle in text, f"tier2 prompt missing lab-scoped deep guidance: {needle}"


def main() -> int:
    skill_md = _read(SKILL_MD)
    tier1 = _read(TIER1_PROMPT)
    tier2 = _read(TIER2_PROMPT)

    checks = (
        ("tier1: tool-call present", lambda: check_prompt_has_tool_call(tier1)),
        ("tier1: five sections", lambda: check_prompt_has_five_sections(tier1)),
        ("tier1: end-condition extended", lambda: check_prompt_end_condition_extended(tier1)),
        ("tier1: lab-scoped resume", lambda: check_prompt_has_lab_scoped_resume(tier1)),
        ("tier2: lab-scoped deep", lambda: check_tier2_inherits_lab_scope(tier2)),
        ("SKILL.md: terminal-action step", lambda: check_skill_md_step_9(skill_md)),
        ("SKILL.md: lab-scoped draft", lambda: check_skill_md_has_lab_scoped_draft(skill_md)),
    )

    failed = 0
    for name, fn in checks:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}", file=sys.stderr)

    if failed:
        print(f"\n{failed}/{len(checks)} checks failed", file=sys.stderr)
        return 1
    print(f"\n{len(checks)}/{len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

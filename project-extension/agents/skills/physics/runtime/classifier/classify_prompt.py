#!/usr/bin/env python3
"""Small fixture-backed classifier for physics skill tests.

This is not the runtime router. It keeps the documented keyword rules
testable without pulling in heavy dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


RULES = Path(__file__).with_name("rules.json")

LICENSE_REFUSAL_TOOLS = {
    "vasp": "commercial_or_proprietary tools require a user-provided authorized environment",
    "gaussian": "license material must be redacted from chat, logs, Notes, and artifacts",
    "comsol": "proprietary installers must not be downloaded, mirrored, bundled, or redistributed",
    "ansys": "license bypass and cracking requests are refused",
    "amber": "commercial_or_proprietary binaries are not bundled",
    "charmm": "sensitive paths and server strings must be redacted",
    "mcnp": "restricted_export_or_controlled workflows require authorized researcher environments",
}

REFUSAL_ACTIONS = (
    "crack",
    "bypass",
    "without my license",
    "without institutional authorization",
    "download",
    "installer",
    "bundle",
    "package",
    "expose",
    "license server",
    "license token",
)


def classify(prompt: str) -> dict[str, object]:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    text = prompt.lower()
    scores: dict[str, int] = {}
    profile_by_family: dict[str, str | None] = {}
    for family_rule in rules["families"]:
        family = family_rule["family"]
        profile_by_family[family] = family_rule["profile_id"]
        scores[family] = sum(1 for keyword in family_rule["keywords"] if keyword in text)

    for tie in rules["tie_breakers"]:
        if all(token in text for token in tie["if_contains"]):
            scores[tie["prefer"]] += 2

    if "no simulation" in text or "without running compute" in text or "without running" in text:
        winner = "literature_only"
    elif "calculate this material property" in text:
        winner = "electronic_structure"
    else:
        winner = max(scores, key=lambda item: scores[item])

    confidence = "high" if scores.get(winner, 0) >= 2 else "medium"
    if winner == "literature_only":
        confidence = "high"

    refusal_reasons = [
        reason
        for tool, reason in LICENSE_REFUSAL_TOOLS.items()
        if tool in text and any(action in text for action in REFUSAL_ACTIONS)
    ]

    return {
        "family": winner,
        "profile_id": profile_by_family[winner],
        "confidence": confidence,
        "must_refuse": bool(refusal_reasons),
        "refusal_reasons": refusal_reasons,
        "clarifying_questions": [] if confidence == "high" else [
            "What physical scale and observable should drive the method choice?",
            "Is this a smoke run, HPC handoff, or artifact-only package?"
        ],
    }


def main() -> int:
    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        print("usage: classify_prompt.py <prompt>", file=sys.stderr)
        return 2
    print(json.dumps(classify(prompt), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

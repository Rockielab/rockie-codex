"""providers/ — multi-provider GPU adapter package.

See base.py for the Protocol every adapter implements. Concrete adapters:
runpod.py, vast.py, primeintellect.py. The router in scripts/gpu.py
iterates them; scripts/runpod.py is a thin per-provider CLI.

Shadeform was previously planned but dropped 2026-04-27 — no spot tier,
redundant upstream coverage. See docs/_internal/market-research/SYNTHESIS.md.
"""

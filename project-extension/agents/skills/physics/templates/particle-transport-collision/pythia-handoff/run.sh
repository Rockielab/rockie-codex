#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" != "--execute" ]]; then
  echo "DRY-RUN: PYTHIA handoff prepared; no local heavy engine executed."
  echo "Pass --execute only inside an authorized Rockie compute or researcher-approved HPC environment."
  exit 0
fi
if [[ "${ROCKIE_COMPUTE_AUTHORIZED:-}" != "1" ]]; then
  echo "Refusing to execute PYTHIA without ROCKIE_COMPUTE_AUTHORIZED=1." >&2
  exit 2
fi
if [[ "${ROCKIE_COMPUTE_RUNTIME:-}" != "hpc" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "tenant" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "rockie" ]]; then
  echo "Refusing to execute PYTHIA outside approved compute runtime." >&2
  exit 2
fi
mkdir -p results
pythia8-main --seed "${SEED:-12345}" --events "${EVENTS:-1000}" > results/stdout.log 2>&1
echo "JOB_DONE"

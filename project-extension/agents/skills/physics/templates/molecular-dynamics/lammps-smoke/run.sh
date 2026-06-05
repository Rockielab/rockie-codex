#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" != "--execute" ]]; then
  echo "DRY-RUN: LAMMPS smoke handoff prepared; no local heavy engine executed."
  echo "Pass --execute only inside an authorized Rockie compute or researcher-approved HPC environment."
  exit 0
fi
if [[ "${ROCKIE_COMPUTE_AUTHORIZED:-}" != "1" ]]; then
  echo "Refusing to execute LAMMPS without ROCKIE_COMPUTE_AUTHORIZED=1." >&2
  exit 2
fi
if [[ "${ROCKIE_COMPUTE_RUNTIME:-}" != "hpc" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "tenant" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "rockie" ]]; then
  echo "Refusing to execute LAMMPS outside approved compute runtime." >&2
  exit 2
fi
mkdir -p results
lmp -i in.lammps > results/stdout.log 2>&1
echo "JOB_DONE"

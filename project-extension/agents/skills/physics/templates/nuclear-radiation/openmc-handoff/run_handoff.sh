#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--execute" ]]; then
  echo "DRY-RUN: review inputs/model.py.stub and authorized cross-section setup."
  echo "Pass --execute only inside the researcher-approved OpenMC environment."
  exit 0
fi
if [[ "${ROCKIE_COMPUTE_AUTHORIZED:-}" != "1" ]]; then
  echo "Refusing to execute OpenMC without ROCKIE_COMPUTE_AUTHORIZED=1." >&2
  exit 2
fi
if [[ "${ROCKIE_COMPUTE_RUNTIME:-}" != "hpc" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "tenant" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "rockie" ]]; then
  echo "Refusing to execute OpenMC outside approved compute runtime." >&2
  exit 2
fi

python3 - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("openmc") else 2)
PY

cp inputs/model.py.stub model.py
python3 model.py
openmc

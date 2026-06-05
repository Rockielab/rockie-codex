from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("monitoring_profiles.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("experiment_monitoring_profiles", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_common_fallback_snapshot_includes_required_fields():
    mod = _load_module()

    profile_id, snapshot = mod.resolve_profile_snapshot(
        profile_id=None,
        run_name="generic smoke",
        origin_skill="experiment",
        software=None,
        script="#!/bin/bash\necho hello\n",
    )

    assert profile_id == "common.default.v1"
    assert snapshot["unprofiled"] is True
    assert snapshot["run_name"] == "generic smoke"
    assert snapshot["origin_skill"] == "experiment"
    assert snapshot["duration_class"] == "medium"
    assert snapshot["cadence_bounds"]["cadence_seconds"] == 300
    assert snapshot["metrics"]
    assert snapshot["panels"]
    assert snapshot["red_flags"]
    assert "stop_policy" in snapshot
    assert "safe_to_auto_stop" in snapshot


def test_resolve_physics_adapter_from_software_inference():
    mod = _load_module()

    profile_id, snapshot = mod.resolve_profile_snapshot(
        profile_id=None,
        run_name="md equilibration",
        origin_skill="experiment",
        software=None,
        script="#!/bin/bash\ngmx mdrun -deffnm md\n",
    )

    assert profile_id == "physics.molecular_dynamics.v1"
    assert snapshot["profile_id"] == "physics.molecular_dynamics.v1"
    assert snapshot["family"] == "molecular_dynamics"
    assert snapshot["software"] == "gromacs"


def test_explicit_profile_is_preserved():
    mod = _load_module()

    profile_id, snapshot = mod.resolve_profile_snapshot(
        profile_id="experiment.ml_baseline.v1",
        run_name="finetune run",
        origin_skill="experiment",
        software="pytorch",
        script="#!/bin/bash\ntorchrun train.py\n",
    )

    assert profile_id == "experiment.ml_baseline.v1"
    assert snapshot["requested_profile_id"] == "experiment.ml_baseline.v1"
    assert snapshot["unprofiled"] is False

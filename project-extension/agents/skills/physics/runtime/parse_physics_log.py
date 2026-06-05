#!/usr/bin/env python3
"""Parse lightweight physics log fixtures into dashboard metric envelopes."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


PARSERS = {
    "force_fields": {
        "profile_id": "physics.force_fields.v1",
        "patterns": [
            ("parameterization_status", r"parameterization status\s*=\s*([A-Za-z0-9_.-]+)", "state"),
            ("missing_parameters", r"missing parameters\s*=\s*([0-9]+)", "count"),
            ("charge_assignment", r"charge assignment\s*=\s*([A-Za-z0-9_.+-]+)", "state"),
            ("water_ion_compatibility", r"water ion compatibility\s*=\s*([A-Za-z0-9_.-]+)", "state"),
            ("parameter_provenance_records", r"parameter provenance records\s*=\s*([0-9]+)", "count"),
            ("minimization_result", r"minimization result\s*=\s*([A-Za-z0-9_.-]+)", "state"),
            ("minimization_rms_force", r"minimization rms force\s*=\s*([-+0-9.eE]+)", "kcal/mol/A"),
        ],
    },
    "molecular_dynamics": {
        "profile_id": "physics.molecular_dynamics.v1",
        "patterns": [
            ("simulation_time", r"Step\s*([0-9]+)", "ps"),
            ("temperature", r"Temp\s*=\s*([-+0-9.eE]+)", "K"),
            ("pressure", r"Press\s*=\s*([-+0-9.eE]+)", "bar"),
            ("total_energy", r"TotEng\s*=\s*([-+0-9.eE]+)", "kcal/mol"),
            ("energy_drift", r"EnergyDrift\s*=\s*([-+0-9.eE]+)", "kcal/mol/ns"),
            ("timestep", r"timestep\s*=\s*([-+0-9.eE]+)", "fs"),
            ("trajectory_freshness", r"trajectory freshness\s*=\s*([-+0-9.eE]+)", "s"),
            ("neighbor_list_warnings", r"neighbor-list warnings\s*=\s*([0-9]+)", "count"),
            ("constraint_warnings", r"constraint warnings\s*=\s*([0-9]+)", "count"),
        ],
    },
    "electronic_structure": {
        "profile_id": "physics.electronic_structure.v1",
        "patterns": [
            ("scf_iteration", r"iteration #\s*([0-9]+)", "count"),
            ("scf_residual", r"estimated scf accuracy\s*<\s*([-+0-9.eE]+)", "Ry"),
            ("total_energy", r"!\s+total energy\s*=\s*([-+0-9.eE]+)", "Ry"),
            ("force_convergence", r"total force\s*=\s*([-+0-9.eE]+)", "Ry/bohr"),
            ("smearing_width", r"smearing width\s*=\s*([-+0-9.eE]+)", "Ry"),
            ("occupation_spread", r"occupation spread\s*=\s*([-+0-9.eE]+)", "fraction"),
            ("smearing_occupancy_warnings", r"smearing occupancy warnings\s*=\s*([0-9]+)", "count"),
        ],
    },
    "particle_transport_collision": {
        "profile_id": "physics.particle_transport_collision.v1",
        "patterns": [
            ("generated_events", r"Generated events:\s*([0-9]+)", "count"),
            ("rejection_rate", r"Rejection rate:\s*([-+0-9.eE]+)", "fraction"),
            ("cross_section", r"Cross section:\s*([-+0-9.eE]+)", "pb"),
        ],
    },
    "continuum_multiphysics": {
        "profile_id": "physics.continuum_multiphysics.v1",
        "patterns": [
            ("iteration", r"iteration\s+([0-9]+)", "count"),
            ("continuity_residual", r"continuity\s+residual\s*=\s*([-+0-9.eE]+)", "arb"),
            ("cfl", r"CFL\s*=\s*([-+0-9.eE]+)", "1"),
            ("drag_force", r"drag\s*=\s*([-+0-9.eE]+)", "N"),
            ("boundary_condition_warnings", r"boundary condition warnings\s*=\s*([0-9]+)", "count"),
            ("integrated_flux", r"integrated flux\s*=\s*([-+0-9.eE]+)", "kg/s"),
        ],
    },
    "plasma_pic": {
        "profile_id": "physics.plasma_pic.v1",
        "patterns": [
            ("timestep", r"step\s*=\s*([0-9]+)", "count"),
            ("particles_per_cell", r"particles per cell\s*=\s*([-+0-9.eE]+)", "count"),
            ("field_energy", r"field energy\s*=\s*([-+0-9.eE]+)", "J"),
            ("courant_constraint", r"courant\s*=\s*([-+0-9.eE]+)", "1"),
        ],
    },
    "nuclear_radiation": {
        "profile_id": "physics.nuclear_radiation.v1",
        "patterns": [
            ("histories", r"histories\s*=\s*([0-9]+)", "count"),
            ("tallies", r"tallies\s*=\s*([0-9]+)", "count"),
            ("relative_error", r"relative error\s*=\s*([-+0-9.eE]+)", "fraction"),
            ("shannon_entropy", r"shannon entropy\s*=\s*([-+0-9.eE]+)", "arb"),
            ("missing_cross_section_data", r"missing cross-section data\s*=\s*([0-9]+)", "count"),
        ],
    },
    "astro_cosmology": {
        "profile_id": "physics.astro_cosmology.v1",
        "patterns": [
            ("simulation_time", r"simulation time\s*=\s*([-+0-9.eE]+)", "code_time"),
            ("redshift", r"redshift\s*=\s*([-+0-9.eE]+)", "z"),
            ("conserved_quantity_drift", r"conserved quantity drift\s*=\s*([-+0-9.eE]+)", "fraction"),
            ("particle_cell_count", r"particle cell count\s*=\s*([0-9]+)", "count"),
            ("checkpoint_freshness", r"checkpoint freshness\s*=\s*([-+0-9.eE]+)", "s"),
        ],
    },
}


def parse(family: str, log_text: str, run_id: str) -> dict[str, object]:
    spec = PARSERS[family]
    samples = []
    for metric, pattern, unit in spec["patterns"]:
        for index, match in enumerate(re.finditer(pattern, log_text, flags=re.IGNORECASE), start=1):
            value_text = match.group(1)
            try:
                value: int | float | str = int(value_text) if value_text.isdigit() else float(value_text)
            except ValueError:
                value = value_text
            samples.append({
                "metric": metric,
                "step": index,
                "value": value,
                "unit": unit,
                "source": "stdout",
            })
    events = []
    lowered = log_text.lower()
    if "warning" in lowered:
        events.append({"kind": "health_event", "severity": "warn", "code": "warning_detected", "message": "Log warning detected"})
    if "smearing" in lowered or "occupancy" in lowered:
        events.append({"kind": "health_event", "severity": "warn", "code": "electronic_occupancy_warning", "message": "Smearing or occupancy warning detected"})
    if "boundary condition warning" in lowered:
        events.append({"kind": "health_event", "severity": "warn", "code": "boundary_condition_warning", "message": "Boundary-condition warning detected"})
    if "neighbor-list warning" in lowered:
        events.append({"kind": "health_event", "severity": "warn", "code": "neighbor_list_warning", "message": "Neighbor-list warning detected"})
    if "constraint warning" in lowered:
        events.append({"kind": "health_event", "severity": "warn", "code": "constraint_warning", "message": "Constraint warning detected"})
    if "provenance warning" in lowered:
        events.append({"kind": "health_event", "severity": "warn", "code": "parameter_provenance_warning", "message": "Parameter provenance warning detected"})
    if "converged" in lowered or samples:
        events.append({"kind": "health_event", "severity": "info", "code": "metrics_parsed", "message": "Parser emitted dashboard metrics"})
    return {"profile_id": spec["profile_id"], "run_id": run_id, "samples": samples, "events": events}


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: parse_physics_log.py <family> <log-file> <run-id>", file=sys.stderr)
        return 2
    family, log_file, run_id = sys.argv[1:]
    print(json.dumps(parse(family, Path(log_file).read_text(encoding="utf-8"), run_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

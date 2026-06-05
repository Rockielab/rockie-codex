from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from unittest import mock


SUBMIT_PATH = Path(__file__).with_name("submit.py")


def load_submit_mod():
    spec = importlib.util.spec_from_file_location("experiment_submit", SUBMIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_headers_send_auth_token_and_tenant_id():
    submit_mod = load_submit_mod()
    with mock.patch.dict(
        os.environ,
        {
            "ROCKIELAB_TENANT_TOKEN": "service-token",
            "ROCKIELAB_TENANT_ID": "t-aaaaaaaaaaaa",
        },
        clear=False,
    ):
        assert submit_mod._headers() == {
            "Content-Type": "application/json",
            "X-Tenant-Token": "service-token",
            "X-Tenant-Id": "t-aaaaaaaaaaaa",
        }


def test_headers_tenant_id_override():
    submit_mod = load_submit_mod()
    with mock.patch.dict(
        os.environ,
        {
            "ROCKIELAB_TENANT_TOKEN": "service-token",
            "ROCKIELAB_TENANT_ID": "t-envtenant000",
        },
        clear=False,
    ):
        assert submit_mod._headers("t-override000")["X-Tenant-Id"] == "t-override000"


def test_submit_includes_dashboard_profile_metadata():
    submit_mod = load_submit_mod()
    tmp_dir = Path(os.environ.get("TMPDIR", "/tmp"))
    script_file = tmp_dir / "train_model_submit_test.sh"
    script_file.write_text("#!/bin/bash\naccelerate launch train.py\n", encoding="utf-8")

    captured = {}

    def fake_http_request(method, url, *, headers, body=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return 200, b'{"job_id":"job-123"}'

    with mock.patch.dict(
        os.environ,
        {
            "ROCKIELAB_API_URL": "https://platform.test",
            "ROCKIELAB_TENANT_TOKEN": "service-token",
            "ROCKIELAB_TENANT_ID": "t-aaaaaaaaaaaa",
            "ROCKIELAB_NOTEBOOK_ID": "notebook:lab-1",
        },
        clear=False,
    ):
        with mock.patch.object(submit_mod, "_http_request", fake_http_request):
            args = submit_mod.parse_args(
                [
                    "--gpu-type", "A100_80GB",
                    "--gpu-count", "1",
                    "--script-file", str(script_file),
                    "--timeout", "3600",
                    "--origin-skill", "experiment",
                ]
            )
            response = submit_mod.submit(args)

    assert response["job_id"] == "job-123"
    dashboard = captured["body"]["dashboard"]
    assert dashboard["notebook_id"] == "notebook:lab-1"
    assert dashboard["origin_skill"] == "experiment"
    assert dashboard["software"] == "pytorch"
    assert dashboard["monitoring_profile_id"] == "experiment.ml_baseline.v1"
    assert dashboard["monitoring_profile_snapshot"]["run_name"] == "train model submit test"
    assert dashboard["monitoring_profile_snapshot"]["cadence_bounds"]["cadence_seconds"] == 240


def test_submit_omits_dashboard_without_notebook_context():
    submit_mod = load_submit_mod()
    tmp_dir = Path(os.environ.get("TMPDIR", "/tmp"))
    script_file = tmp_dir / "legacy_submit_test.sh"
    script_file.write_text("#!/bin/bash\necho legacy submit\n", encoding="utf-8")

    captured = {}

    def fake_http_request(method, url, *, headers, body=None):
        captured["body"] = json.loads(body.decode("utf-8"))
        return 200, b'{"job_id":"job-legacy"}'

    with mock.patch.dict(
        os.environ,
        {
            "ROCKIELAB_API_URL": "https://platform.test",
            "ROCKIELAB_TENANT_TOKEN": "service-token",
            "ROCKIELAB_TENANT_ID": "t-aaaaaaaaaaaa",
        },
        clear=True,
    ):
        with mock.patch.object(submit_mod, "_http_request", fake_http_request):
            args = submit_mod.parse_args(
                [
                    "--gpu-type", "A100_80GB",
                    "--gpu-count", "1",
                    "--script-file", str(script_file),
                    "--timeout", "3600",
                ]
            )
            response = submit_mod.submit(args)

    assert response["job_id"] == "job-legacy"
    assert "dashboard" not in captured["body"]


def test_submit_can_infer_physics_profile_from_script():
    submit_mod = load_submit_mod()
    tmp_dir = Path(os.environ.get("TMPDIR", "/tmp"))
    script_file = tmp_dir / "qe_run_submit_test.sh"
    script_file.write_text("#!/bin/bash\npw.x -input silicon.in > silicon.out\n", encoding="utf-8")

    captured = {}

    def fake_http_request(method, url, *, headers, body=None):
        captured["body"] = json.loads(body.decode("utf-8"))
        return 200, b'{"job_id":"job-456"}'

    with mock.patch.dict(
        os.environ,
        {
            "ROCKIELAB_API_URL": "https://platform.test",
            "ROCKIELAB_TENANT_TOKEN": "service-token",
            "ROCKIELAB_TENANT_ID": "t-aaaaaaaaaaaa",
            "ROCKIELAB_NOTEBOOK_ID": "notebook:physics-1",
        },
        clear=False,
    ):
        with mock.patch.object(submit_mod, "_http_request", fake_http_request):
            args = submit_mod.parse_args(
                [
                    "--gpu-type", "A100_80GB",
                    "--gpu-count", "1",
                    "--script-file", str(script_file),
                    "--timeout", "3600",
                ]
            )
            submit_mod.submit(args)

    dashboard = captured["body"]["dashboard"]
    assert dashboard["software"] == "quantum-espresso"
    assert dashboard["monitoring_profile_id"] == "physics.electronic_structure.v1"

from __future__ import annotations

from pathlib import Path


def test_inference_engineer_documents_auth_and_identity_headers():
    src = Path(__file__).with_name("SKILL.md").read_text(encoding="utf-8")

    assert 'X-Tenant-Token: $ROCKIELAB_TENANT_TOKEN' in src
    assert 'X-Tenant-Id: $ROCKIELAB_TENANT_ID' in src
    assert "Never use tenant identity as auth" in src

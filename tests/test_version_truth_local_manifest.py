import json

from app import journal


def test_stable_manifest_prefers_deployed_local_file(tmp_path, monkeypatch):
    local = tmp_path / "manifest.json"
    local.write_text(
        json.dumps(
            {
                "release": "9.9.9",
                "data_bridge_version": "1.99",
                "sequence_ea_version": "3.99",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(journal, "_LOCAL_STABLE_MANIFEST", local)
    journal._manifest_cache["at"] = 0.0
    journal._manifest_cache["value"] = None

    def fail_remote(*args, **kwargs):
        raise AssertionError("remote manifest should not be needed when deployed manifest exists")

    monkeypatch.setattr(journal.urllib.request, "urlopen", fail_remote)
    value = journal._stable_manifest()
    assert value["release"] == "9.9.9"
    assert value["sequence_ea_version"] == "3.99"


def test_runtime_truth_can_clear_stale_installer_telemetry(monkeypatch):
    from app import runtime_version_truth

    base = {
        "stable_release": "6.3.10",
        "pending_reload": True,
        "restart_manager": "SAFE_RELOAD_ARMED",
        "components": {
            "data_bridge": {
                "desired": "1.36",
                "installed": "1.36",
                "running": "1.36",
                "status": "CURRENT",
            },
            "sequence_ea": {
                "desired": "3.28",
                "installed": "3.23",
                "running": "3.28",
                "status": "UPDATE_PENDING",
            },
        },
    }

    def fake_status():
        import copy
        return copy.deepcopy(base)

    monkeypatch.setattr(journal, "component_status", fake_status)
    runtime_version_truth.install_runtime_version_truth_policy()
    value = journal.component_status()

    assert value["components"]["sequence_ea"]["installed"] == "3.28"
    assert value["components"]["sequence_ea"]["installed_reported"] == "3.23"
    assert value["components"]["sequence_ea"]["status"] == "CURRENT"
    assert value["pending_reload"] is False
    assert value["restart_manager"] == "NOT_NEEDED"

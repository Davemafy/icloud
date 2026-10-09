"""Functional version-truth integration with simulated MT5 heartbeat payloads."""
from datetime import datetime, timezone

from app import journal


def _heartbeats(sequence_running: str, installed_sequence: str, receipt: str):
    now = int(datetime.now(timezone.utc).timestamp())
    return [
        {
            "ea": "InstitutionalSMC_DataBridge",
            "version": "1.59",
            "ts": now,
            "payload": {
                "details": {
                    "updater_version": "FRONT_FACING_MANUAL_INSTALLER_1.12",
                    "last_action": receipt,
                    "stable_release": "6.4.20",
                    "installed_bridge_version": "1.59",
                    "installed_sequence_version": installed_sequence,
                    "desired_bridge_version": "1.59",
                    "desired_sequence_version": "3.78",
                    "pending_reload": "1",
                }
            },
        },
        {
            "ea": "InstitutionalSMC_SequenceEA",
            "version": sequence_running,
            "ts": now,
            "payload": {"details": {"restart_safe": "true", "open_positions": 0}},
        },
    ]


def test_installed_378_is_not_misrepresented_as_running_378(monkeypatch):
    receipt = "MANUAL_INSTALL_COMPILED_abc123"
    monkeypatch.setattr(journal, "_stable_manifest", lambda: {
        "release": "6.4.20", "data_bridge_version": "1.59",
        "sequence_ea_version": "3.78",
    })
    monkeypatch.setattr(journal, "latest_heartbeats", lambda limit: _heartbeats("3.77", "3.78", receipt))
    truth = journal.component_status()
    assert truth["last_action"] == receipt
    assert truth["updater_version"] == "FRONT_FACING_MANUAL_INSTALLER_1.12"
    assert truth["components"]["sequence_ea"]["installed"] == "3.78"
    assert truth["components"]["sequence_ea"]["running"] == "3.77"
    assert truth["components"]["sequence_ea"]["status"] == "RESTART_REQUIRED"


def test_current_running_version_is_reflected_from_new_heartbeat(monkeypatch):
    receipt = "MANUAL_INSTALL_COMPILED_def456"
    monkeypatch.setattr(journal, "_stable_manifest", lambda: {
        "release": "6.4.20", "data_bridge_version": "1.59",
        "sequence_ea_version": "3.78",
    })
    monkeypatch.setattr(journal, "latest_heartbeats", lambda limit: _heartbeats("3.78", "3.78", receipt))
    truth = journal.component_status()
    assert truth["last_action"] == receipt
    assert truth["components"]["sequence_ea"]["installed"] == "3.78"
    assert truth["components"]["sequence_ea"]["running"] == "3.78"
    assert truth["components"]["sequence_ea"]["status"] == "CURRENT"


def test_wrong_folder_stale_installed_version_is_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(journal, "_stable_manifest", lambda: {
        "release": "6.4.20", "data_bridge_version": "1.59",
        "sequence_ea_version": "3.78",
    })
    monkeypatch.setattr(journal, "latest_heartbeats", lambda limit: _heartbeats(
        "3.77", "3.23", "MANUAL_INSTALL_COMPILED_old",
    ))
    truth = journal.component_status()
    assert truth["components"]["sequence_ea"]["installed"] == "3.23"
    assert truth["components"]["sequence_ea"]["running"] == "3.77"
    assert truth["components"]["sequence_ea"]["status"] == "UPDATE_PENDING"

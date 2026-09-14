from __future__ import annotations


def install_runtime_version_truth_policy() -> None:
    """Make live MT5 runtime truth authoritative over stale installer telemetry.

    Manual installs can leave updater_status.txt behind even after MT5 is already
    running the desired EA. This wrapper preserves the stale reported value for
    diagnostics, but exposes the confirmed running version as the effective
    installed version and clears a stale reload flag when both components are
    already running their desired versions.
    """
    from . import journal

    if getattr(journal.component_status, "_runtime_truth_wrapped", False):
        return

    original = journal.component_status

    def component_status_runtime_truth() -> dict:
        value = original()
        components = value.get("components", {}) if isinstance(value, dict) else {}
        all_current = True

        for item in components.values():
            if not isinstance(item, dict):
                all_current = False
                continue
            desired = str(item.get("desired") or "")
            installed = str(item.get("installed") or "")
            running = str(item.get("running") or "")

            if desired and running == desired:
                if installed and installed != desired:
                    item["installed_reported"] = installed
                    item["installed_truth_source"] = "RUNNING_CONFIRMED"
                    item["installed"] = running
                item["status"] = "CURRENT"
            else:
                all_current = False

        if components and all_current:
            value["pending_reload_reported"] = bool(value.get("pending_reload"))
            value["pending_reload"] = False
            value["restart_manager"] = "NOT_NEEDED"
        return value

    component_status_runtime_truth._runtime_truth_wrapped = True
    journal.component_status = component_status_runtime_truth

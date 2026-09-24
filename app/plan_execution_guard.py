from __future__ import annotations

_installed = False
_original_active_plan_text = None


def install_plan_execution_guard() -> None:
    """Wrap the existing MT5 text-plan exporter with DEMO/PAPER safety checks.

    Institutional map truth is kept separate from execution authority. The published
    source-exact zone is never moved merely because freshness, history or runway makes
    it non-executable.
    """
    global _installed, _original_active_plan_text
    if _installed:
        return

    from . import engine
    from .execution_safety import guard_plan_text
    from .professional_zone_execution_separation import (
        apply_execution_separation,
        install_ai_contract_correction,
    )

    install_ai_contract_correction()
    original = engine.active_plan_text
    if getattr(original, "_tradezone_execution_guard_v657", False):
        _installed = True
        return

    def guarded_active_plan_text(analysis, snapshot=None):
        safety_checked = guard_plan_text(original(analysis, snapshot), analysis, snapshot)
        return apply_execution_separation(safety_checked, analysis, snapshot)

    guarded_active_plan_text._tradezone_execution_guard_v657 = True
    _original_active_plan_text = original
    engine.active_plan_text = guarded_active_plan_text
    _installed = True

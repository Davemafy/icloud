from __future__ import annotations

_installed = False
_original_active_plan_text = None


def install_plan_execution_guard() -> None:
    """Wrap the existing MT5 text-plan exporter with DEMO/PAPER safety checks.

    Installed at package import time so app.main receives the guarded function when
    it imports active_plan_text from app.engine. This does not alter zone formation,
    Sequence risk sizing, or any real-money path.
    """
    global _installed, _original_active_plan_text
    if _installed:
        return

    from . import engine
    from .execution_safety import guard_plan_text

    original = engine.active_plan_text
    if getattr(original, "_tradezone_execution_guard_v656", False):
        _installed = True
        return

    def guarded_active_plan_text(analysis, snapshot=None):
        return guard_plan_text(original(analysis, snapshot), analysis, snapshot)

    guarded_active_plan_text._tradezone_execution_guard_v656 = True
    _original_active_plan_text = original
    engine.active_plan_text = guarded_active_plan_text
    _installed = True

from .plan_execution_guard import install_plan_execution_guard
from .clinical_review_hardening import install_clinical_review_hardening
from .dashboard_recovery import install_dashboard_recovery
from .dashboard_execution_truth import install_dashboard_execution_truth
from .live_ownership_sync import install_live_ownership_sync
from .master_sniper_zone_authority import install_master_sniper_zone_authority
from .master_sniper_adaptive_geometry import install_master_sniper_adaptive_geometry

# DEMO/PAPER ONLY: fail closed before MT5 receives an executable plan.
install_plan_execution_guard()

# Master Sniper is the publication authority for today's actionable zone map.
# Structural discovery remains in institutional_two_zone; this layer prevents a
# wrong-side HTF zone from being advertised or acquiring M1 execution authority.
install_master_sniper_zone_authority()

# Keep Master Sniper geometry authoritative even after service.py installs the
# legacy runtime compatibility seam. Exact source core + attached structural
# liquidity controls the envelope; no fixed 200-300 point veto is allowed.
install_master_sniper_adaptive_geometry()

# Read-only/status-only remediation. This changes journal aggregation and dashboard
# wording only; it does not change /mt5/plan, zone qualification, AI approval,
# risk sizing, order placement, or Sequence EA execution.
install_clinical_review_hardening()

# Read-only dashboard transport recovery. Keep the dashboard live even if the SSE
# aggregate is degraded or buffered; execution logic remains untouched.
install_dashboard_recovery()

# Surface the backend's Master Sniper risk/authority contract directly beside each
# published zone. Display only: no grade, risk, plan, or Sequence decision is made
# in the browser.
install_dashboard_execution_truth()

# Keep live persisted thesis/objective state synchronized with dashboard, chart
# ownership rendering and the plan guard. A just-released owner fails closed until
# the scheduler completes a fresh analysis; no execution gate is bypassed.
install_live_ownership_sync()

from .plan_execution_guard import install_plan_execution_guard
from .clinical_review_hardening import install_clinical_review_hardening
from .dashboard_recovery import install_dashboard_recovery
from .live_ownership_sync import install_live_ownership_sync

# DEMO/PAPER ONLY: fail closed before MT5 receives an executable plan.
install_plan_execution_guard()

# Read-only/status-only remediation. This changes journal aggregation and dashboard
# wording only; it does not change /mt5/plan, zone qualification, AI approval,
# risk sizing, order placement, or Sequence EA execution.
install_clinical_review_hardening()

# Read-only dashboard transport recovery. Keep the dashboard live even if the SSE
# aggregate is degraded or buffered; execution logic remains untouched.
install_dashboard_recovery()

# Keep live persisted thesis/objective state synchronized with dashboard, chart
# ownership rendering and the plan guard. A just-released owner fails closed until
# the scheduler completes a fresh analysis; no execution gate is bypassed.
install_live_ownership_sync()

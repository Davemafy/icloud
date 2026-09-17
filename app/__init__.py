from .plan_execution_guard import install_plan_execution_guard
from .clinical_review_hardening import install_clinical_review_hardening
from .dashboard_recovery import install_dashboard_recovery

# DEMO/PAPER ONLY: fail closed before MT5 receives an executable plan.
install_plan_execution_guard()

# Read-only/status-only remediation. This changes journal aggregation and dashboard
# wording only; it does not change /mt5/plan, zone qualification, AI approval,
# risk sizing, order placement, or Sequence EA execution.
install_clinical_review_hardening()

# Read-only dashboard transport recovery. Keep the dashboard live even if the SSE
# aggregate is degraded or buffered; execution logic remains untouched.
install_dashboard_recovery()

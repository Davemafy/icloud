from .plan_execution_guard import install_plan_execution_guard
from .clinical_review_hardening import install_clinical_review_hardening

# DEMO/PAPER ONLY: fail closed before MT5 receives an executable plan.
install_plan_execution_guard()

# Read-only/status-only remediation. This changes journal aggregation and dashboard
# wording only; it does not change /mt5/plan, zone qualification, AI approval,
# risk sizing, order placement, or Sequence EA execution.
install_clinical_review_hardening()

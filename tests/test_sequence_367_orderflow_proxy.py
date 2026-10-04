from pathlib import Path


SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_67_OrderFlowProxyTelemetry_Demo.mq5")
MAIN = Path("app/main.py")
DASH = Path("app/dashboard_view.py")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_367_version_and_transparent_proxy_contract():
    text = _text(SEQ)
    assert '#property version   "3.67"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.67"' in text
    assert "input int OrderFlowProxyMode=1;" in text
    assert 'g_tzOrderFlowProxyFeed="CFD_TICK_VOLUME_PROXY"' in text
    assert "TZ67_BarDeltaProxy" in text
    assert "TZ67_EvaluateOrderFlowProxy" in text
    assert "TZ67_OrderFlowProxyAllowsEntry" in text
    assert "not centralized COMEX delta" in text


def test_367_default_is_observation_only_and_optional_modes_fail_closed():
    text = _text(SEQ)
    gate = text[text.index("bool TZ67_OrderFlowProxyAllowsEntry()"):text.index("\n}", text.index("bool TZ67_OrderFlowProxyAllowsEntry()")) + 2]
    assert "if(OrderFlowProxyMode<=1)return true;" in gate
    assert 'g_tzOrderFlowProxyState=="CONTRADICTORY"' in gate
    assert 'TZ_SetGate("ORDERFLOW_PROXY","CFD_TICK_VOLUME_PROXY_CONTRADICTS_ENTRY")' in gate
    assert 'TZ_SetGate("ORDERFLOW_PROXY","WAITING_FOR_SUPPORTIVE_CFD_TICK_VOLUME_PROXY")' in gate


def test_367_proxy_runs_after_model_specific_confirmation_and_for_flip():
    text = _text(SEQ)
    evaluate = text[text.index("void Evaluate()"):text.index("\nint OnInit()", text.index("void Evaluate()"))]
    confirm = evaluate.index("TZ63_ModelSpecificConfirmationReady")
    proxy = evaluate.index("TZ67_EvaluateOrderFlowProxy(r,sig.buy)", confirm)
    allow = evaluate.index("TZ67_OrderFlowProxyAllowsEntry()", proxy)
    order = evaluate.index("TZ37_SendOrders", allow)
    assert confirm < proxy < allow < order

    flip = text[text.index("void TZ28_EvaluateAcceptedFlip()"):text.index("\nstring TZ_JsonEscape", text.index("void TZ28_EvaluateAcceptedFlip()"))]
    flip_confirm = flip.index("TZ39_FlipEntryReady")
    flip_proxy = flip.index("TZ67_EvaluateOrderFlowProxy(r,sig.buy)", flip_confirm)
    flip_allow = flip.index("TZ67_OrderFlowProxyAllowsEntry()", flip_proxy)
    flip_order = flip.index("TZ37_SendOrders", flip_allow)
    assert flip_confirm < flip_proxy < flip_allow < flip_order


def test_367_sequence_state_heartbeat_and_entry_audit_emit_proxy_truth():
    text = _text(SEQ)
    for needle in (
        "orderflow_proxy_mode",
        "orderflow_proxy_feed",
        "orderflow_proxy_state",
        "orderflow_proxy_score",
        "orderflow_proxy_delta_norm",
        "orderflow_proxy_absorption",
        "orderflow_proxy_divergence",
        "orderflow_proxy_expansion",
    ):
        assert needle in text

    audit = text[text.index("void TZ36_SendEntryDecisionAudit"):text.index("\nbool TZ45_ActiveOwnerMatchesCurrentPlan", text.index("void TZ36_SendEntryDecisionAudit"))]
    assert '"orderflow_proxy_feed"' in audit
    assert '"orderflow_proxy_state"' in audit
    assert "g_tzOrderFlowProxyScore" in audit


def test_367_cloud_and_dashboard_expose_proxy_with_data_source_disclaimer():
    main = _text(MAIN)
    dash = _text(DASH)
    for needle in (
        '"orderflow_proxy_mode"',
        '"orderflow_proxy_feed"',
        '"orderflow_proxy_state"',
        '"orderflow_proxy_score"',
        '"orderflow_proxy_delta_norm"',
        '"orderflow_proxy_absorption"',
        '"orderflow_proxy_divergence"',
        '"orderflow_proxy_expansion"',
    ):
        assert needle in main
    assert "Order-flow proxy:" in dash
    assert "NOT centralized COMEX bid/ask delta" in dash


def test_367_source_is_structurally_balanced():
    text = _text(SEQ)
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)

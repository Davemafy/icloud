from pathlib import Path

from app.engine import active_plan_text
from app.models import Analysis, Direction, Zone, ZoneState, Grade

ROOT = Path(__file__).resolve().parents[1]
SEQ75 = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_75_CanonicalLiquidityGate_Demo.mq5"
SEQ74 = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_74_EntryStopGuards_Demo.mq5"


def _zone(side: Direction = Direction.SELL, notes=None) -> Zone:
    return Zone(
        zone_id="Z_CANONICAL", original_direction=side,
        flip_direction=Direction.BUY if side == Direction.SELL else Direction.SELL,
        setup_type="CONTINUATION", source_tf="H4>H1",
        grade=Grade.A, state=ZoneState.ACTIVE,
        core_low=4173.47, core_high=4179.67,
        core_method="PROMPT_H4_PARENT_H1_REFINEMENT",
        location_score=8.0, zone_low=4173.47, zone_high=4196.55,
        invalidation_level=4196.55, invalidation_rule="M15 accepted distal invalidation",
        original_target1=4166.04, flip_target1=4197.0,
        notes=list(notes or []),
    )


def _plan(zone: Zone) -> dict[str, str]:
    a = Analysis(
        analysis_id="A_CANONICAL", generated_at=1, snapshot_at=1,
        overall_bias=zone.original_direction, zones=[zone],
        selected_zone_id=zone.zone_id, approved=True, ai_approved=True,
    )
    return dict(line.split("=", 1) for line in active_plan_text(a).splitlines() if "=" in line)


def test_cloud_exports_exact_attached_sell_bsl_without_substituting_core_high():
    plan = _plan(_zone(notes=[
        "attached_liquidity:BSL:H1_BSL@4182.22000",
        "source_ready_ts:1791288000",
    ]))
    assert plan["zone_liquidity_type"] == "BSL"
    assert plan["zone_liquidity_label"] == "H1_BSL"
    assert plan["zone_liquidity_price"] == "4182.22000"
    assert plan["zone_liquidity_source_ready_ts"] == "1791288000"
    assert plan["core_high"] == "4179.67000"
    assert plan["zone_liquidity_price"] != plan["core_high"]


def test_cloud_exports_attached_buy_ssl():
    plan = _plan(_zone(Direction.BUY, [
        "attached_liquidity:SSL:H4_SSL@4175.20000",
        "source_ready_ts:1791288000",
    ]))
    assert plan["zone_liquidity_type"] == "SSL"
    assert plan["zone_liquidity_label"] == "H4_SSL"
    assert plan["zone_liquidity_price"] == "4175.20000"


def test_cloud_never_guesses_a_liquidity_price_or_accepts_the_wrong_side():
    for notes in (
        [],
        ["attached_liquidity:SSL:H4_SSL@4177.00000"],
        ["attached_liquidity:BSL:H4_BSL@4215.00000"],
        ["attached_liquidity:BSL:bad"],
    ):
        plan = _plan(_zone(notes=notes))
        assert plan["zone_liquidity_price"] == ""
        assert plan["zone_liquidity_label"] == ""
        assert plan["zone_liquidity_type"] == ""


def _function(source: str, signature: str) -> str:
    start = source.index(signature)
    pos = source.index("{", start)
    depth = 0
    for end in range(pos, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                return source[start : end + 1]
    raise AssertionError(f"Unbalanced MQL5 function: {signature}")


def test_375_source_requires_exact_canonical_side_price_and_source_ready_time():
    text = SEQ75.read_text()
    assert '#property version   "3.75"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.75"' in text
    contract = _function(text, "bool TZ75_CanonicalContractReady(")
    assert 'string expected=(buy?"SSL":"BSL")' in contract
    assert "g_tzCanonicalLabel" in contract
    assert "g_tzCanonicalLevel" in contract
    assert "g_tzCanonicalSourceReady" in contract
    assert "ZONE_CANONICAL_LIQUIDITY_MISSING_OR_SIDE_MISMATCH" in contract


def test_375_primary_cannot_trade_without_closed_raid_reclaim_and_causal_order():
    text = SEQ75.read_text()
    scan = _function(text, "bool TZ75_FindCanonicalSweepReclaim(")
    assert "g_tzCanonicalLevel-tick" in scan
    assert "g_tzCanonicalLevel+tick" in scan
    assert "TZ60_DirectionalClose(r[reclaim],sig.buy)" in scan
    assert "sig.break_idx" in scan
    assert "CanonicalMaxAcceptanceCloses" in scan
    assert "r[raid].time<earliest" in scan
    assert "g_tzCanonicalCandidateSweep=r[raid].time" in scan
    assert "g_tzCanonicalCandidateReclaim=r[reclaim].time" in scan
    # Never count the still-forming bar zero as sweep/reclaim.
    assert "int first=MathMax(1,sig.break_idx)" in scan


def test_375_no_bypass_for_any_primary_sniper_model_or_reentry_slot():
    text = SEQ75.read_text()
    gate = _function(text, "bool TZ75_CanonicalCampaignEntryReady(")
    for tag in ('tag!="P0"', 'tag!="B0"', 'tag!="R1"', 'tag!="R2"'):
        assert tag in gate
    assert "TZ75_FindCanonicalSweepReclaim" in gate
    assert "TZ75_CampaignCanonicalProofValid" in gate
    evaluate = _function(text, "void Evaluate()")
    assert "TZ75_CanonicalCampaignEntryReady(r,sig,tag,canonicalReason)" in evaluate
    assert evaluate.index("TZ75_CanonicalCampaignEntryReady") < evaluate.index("TZ63_ModelSpecificConfirmationReady")
    assert evaluate.index("TZ75_CanonicalCampaignEntryReady") < evaluate.index("TZ37_SendOrders")


def test_375_r1_r2_inherit_only_a_successfully_opened_same_owner_p0():
    text = SEQ75.read_text()
    check = _function(text, "bool TZ75_CampaignCanonicalProofValid(")
    for expression in (
        "g_tzCanonicalProofZone!=g_plan.zone_id",
        "g_tzCanonicalProofSide!=g_tzCanonicalSide",
        "g_tzCanonicalProofLevel-g_tzCanonicalLevel",
        "g_tzCanonicalProofOwnerTs!=TZ75_CurrentOwnerAcquiredAt()",
    ):
        assert expression in check
    evaluate = _function(text, "void Evaluate()")
    success = evaluate.index("if(TZ37_SendOrders")
    record = evaluate.index("TZ75_RecordOpenedPrimaryCanonicalProof()", success)
    assert success < record
    assert 'tag=="P0"||tag=="B0"' in evaluate
    assert "canonical_liquidity_proof.txt" in text


def test_375_accepted_flips_model_chains_stop_geometry_and_management_unchanged():
    old, new = SEQ74.read_text(), SEQ75.read_text()
    signatures = (
        "void ManagePositions()",
        "bool TZ28_EvaluateAcceptedFlip(",
        "bool TZ60_BuildEngulfing(",
        "bool TZ70_BuildEngulfingRetest(",
        "bool TZ60_ScanPrimaryEngine(",
        "bool TZ62_BuildInstitutionalBreakout(",
        "bool TZ62_BuildDisplacementContinuation(",
        "bool TZ74_UniversalClosedM1DirectionalReady(",
        "double TZ74_PrimaryCoreProtectedExecutionStop(",
        "bool TZ36_MinRRValid(",
    )
    for sig in signatures:
        if sig in old:
            assert _function(old, sig) == _function(new, sig), sig


def test_375_original_zone_gate_does_not_affect_accepted_flip_or_independent_handoff():
    text = SEQ75.read_text()
    evaluate = _function(text, "void Evaluate()")
    assert 'if(primaryAuthority&&(tag=="P0"||tag=="B0"||tag=="R1"||tag=="R2"))' in evaluate
    assert '"LIQUIDITY_REVERSAL_HANDOFF"' in evaluate
    assert "TZ28_EvaluateAcceptedFlip();" in evaluate
    assert "TZ74_UniversalClosedM1DirectionalReady" in evaluate


def test_375_audit_has_canonical_identity_and_reclaim_timestamps():
    text = SEQ75.read_text()
    audit = _function(text, "void TZ36_SendEntryDecisionAudit(")
    for field in (
        "canonical_required", "canonical_side", "canonical_label", "canonical_level",
        "canonical_sweep_ts", "canonical_reclaim_ts", "canonical_owner_acquired_at",
    ):
        assert field in audit


def test_375_brackets_balanced():
    text = SEQ75.read_text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)

from pathlib import Path

SEQ = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_64_ObjectiveAwareProfitProtection_Demo.mq5")


def _text() -> str:
    return SEQ.read_text(encoding="utf-8")


def test_364_version_and_management_contract():
    text = _text()
    assert '#property version   "3.64"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.64"' in text
    assert "ManagementTP1ClosePct=60.0" in text
    assert "BreakEvenCostSpreadMultiple=1.50" in text
    assert "NearTargetArmFraction=0.85" in text
    assert "NearTargetLockFraction=0.60" in text
    assert "NearTargetTightArmFraction=0.95" in text
    assert "NearTargetTightLockFraction=0.80" in text


def test_364_two_leg_capture_and_runner_final_objective():
    text = _text()
    send = text[text.index("bool TZ37_SendOrders"):text.index("// v3.34 trade-management hardening.")]
    assert "bool hasRunnerTarget=" in send
    assert "MathCeil((total*pct)/st" in send
    assert 'string c1="SMCV6 "+tag+" T1"' in send
    assert 'string cr="SMCV6 "+tag+" RUN"' in send
    assert "trade.Buy(lr,_Symbol,0,sl,deepest,cr)" in send
    assert "trade.Sell(lr,_Symbol,0,sl,deepest,cr)" in send


def test_364_near_target_high_water_lock_is_persistent():
    text = _text()
    manage = text[text.index("void ManagePositions()"):text.index("// Accepted-zone flip state")]
    assert 'TZ64_LoadState(pid,"PEAK",0.0)' in manage
    assert 'TZ64_SaveState(pid,"PEAK",peak)' in manage
    assert "peak>=NearTargetArmFraction" in manage
    assert "peak>=NearTargetTightArmFraction" in manage


def test_364_runner_uses_frozen_entry_objectives_and_ratchets():
    text = _text()
    assert "TZ64_SaveObjectiveLadderForLastDeal" in text
    assert 'TZ64_SaveState(pid,"O1",t1)' in text
    assert 'TZ64_SaveState(pid,"O2",t2)' in text
    manage = text[text.index("void ManagePositions()"):text.index("// Accepted-zone flip state")]
    assert "TZ64_UpdateObjectiveStep(pid,buy,mark)" in manage
    assert "lock2=buy?(o1-objBuffer):(o1+objBuffer)" in manage
    assert "lock3=buy?(o2-objBuffer):(o2+objBuffer)" in manage
    assert "it can never loosen a completed-objective lock" in manage


def test_364_cost_aware_break_even_is_not_exact_entry():
    text = _text()
    manage = text[text.index("void ManagePositions()"):text.index("// Accepted-zone flip state")]
    assert "double costBuffer=TZ64_CostBuffer()" in manage
    assert "double be=buy?(o+costBuffer):(o-costBuffer)" in manage


def test_364_source_is_structurally_balanced():
    text = _text()
    for left, right in (("(", ")"), ("{", "}"), ("[", "]")):
        assert text.count(left) == text.count(right), (left, right)

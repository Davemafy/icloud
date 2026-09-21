from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_34_PersistentRunnerRisk_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v334_persists_original_risk_before_break_even():
    text = _text()
    assert '#property version   "3.34"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.34"' in text
    assert "#define ManagePositions TZ21_BaseManagePositions" in text
    assert "#undef ManagePositions" in text
    assert "TZ34_InitialRiskDistance" in text
    assert "GlobalVariableSet(key,d)" in text
    assert "HistorySelectByPosition(positionId)" in text
    assert "POSITION_IDENTIFIER" in text


def test_v334_runner_uses_immutable_risk_basis_after_be():
    text = _text()
    start = text.index("void ManagePositions()")
    end = text.index("\nvoid TZ28_ClearAcceptedFlip", start)
    fn = text[start:end]
    assert "double initialRisk=TZ34_InitialRiskDistance(ticket,o,sl);" in fn
    assert "double rnow=buy?(mark-o)/initialRisk:(o-mark)/initialRisk;" in fn
    assert "rnow>=BreakEvenArmAtR" in fn
    assert "rnow>=RunnerTrailStartR" in fn
    assert 'StringFind(comment," RUN")>=0' in fn
    assert "RunnerTrailTF" in fn
    assert "RunnerTrailLookbackBars" in fn
    assert "RunnerStructureATRBuffer" in fn
    assert "RunnerTrailATRMultiple" in fn
    assert "SYMBOL_TRADE_STOPS_LEVEL" in fn
    assert "trade.PositionModify(ticket,desired,tp)" in fn
    assert "double init=MathAbs(o-sl);if(init<=0)continue;" not in fn

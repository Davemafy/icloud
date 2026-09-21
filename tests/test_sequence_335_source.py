from pathlib import Path

EA = Path("mt5/stable/InstitutionalSMC_SequenceEA_v3_35_ConfirmedValueReentry_Demo.mq5")


def _text() -> str:
    return EA.read_text(encoding="utf-8")


def test_v335_requires_closed_m1_reaction_for_reentries():
    text = _text()
    assert '#property version   "3.35"' in text
    assert '#define TZ_SEQUENCE_VERSION "3.35"' in text
    assert "ReentryRequireClosedM1ValueReaction=true" in text
    assert "ReentrySignalMaxAgeBars=20" in text
    assert "TZ35_ReentryEntryReady" in text
    assert "WAITING_FOR_CLOSED_M1_VALUE_REACTION" in text
    assert "microBreak=buy?(r[i].close>r[i+1].high):(r[i].close<r[i+1].low)" in text
    assert "body>=a*ReentryReactionMinBodyATR" in text
    assert 'TZ_SetGate("REENTRY_CONFIRMATION",reentryReason)' in text


def test_v335_rejects_stale_or_invalidated_pd_arrays_and_chase():
    text = _text()
    assert "REENTRY_SIGNAL_STALE" in text
    assert "PD_ARRAY_ACCEPTED_INVALIDATION" in text
    assert "CONFIRMED_VALUE_REACTION_BUT_CHASED" in text
    assert "VALUE_REACTION_LOST_ABOVE_ARRAY" in text
    assert "VALUE_REACTION_LOST_BELOW_ARRAY" in text


def test_v335_terminal_reentry_cap_and_entry_audit():
    text = _text()
    assert 'TZ_SetGate("THESIS","REENTRY_LIMIT_REACHED")' in text
    assert "TZ35_SendEntryDecisionAudit" in text
    assert '\"event\":\"ENTRY_DECISION\"' in text
    for needle in [
        '\"break_bar_ts\"',
        '\"value_reaction_bar_ts\"',
        '\"ote_low\"',
        '\"ote_high\"',
        '\"pd_low\"',
        '\"pd_high\"',
        '\"entry_low\"',
        '\"entry_high\"',
        '\"closed_m1_value_reaction_confirmed\"',
    ]:
        assert needle in text

"""Fail-closed release transformer for Master Sniper contract parity.

This script is intentionally NOT a manifest promoter. It transforms a checked-out
release branch only after verifying exact source anchors. Any source drift aborts.
DEMO / PAPER ONLY until the release gate is completed.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQ_OLD = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_41_BPlusAuthority_Demo.mq5"
SEQ_NEW = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5"
BRIDGE_OLD = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_50_BPlusAuthority.mq5"
BRIDGE_NEW = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_51_SniperContractParity.mq5"
PARITY_INCLUDE_SRC = ROOT / "mt5/include/SniperContractParityV1.mqh"
PARITY_INCLUDE_STABLE = ROOT / "mt5/stable/SniperContractParityV1.mqh"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def require_all(text: str, needles: tuple[str, ...], *, label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise RuntimeError(f"{label}: required anchors missing: {missing}")


def refuse_existing_targets() -> None:
    for path in (SEQ_NEW, BRIDGE_NEW, PARITY_INCLUDE_STABLE):
        if path.exists():
            raise RuntimeError(f"refusing to overwrite immutable target: {path}")


def build_sequence() -> str:
    s = SEQ_OLD.read_text(encoding="utf-8")
    require_all(
        s,
        (
            '#property version   "3.41"',
            '#define TZ_SEQUENCE_VERSION "3.41"',
            '#include <TradeZoneCore\\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>',
            'string g_tzRiskContext="TREND";',
            'void TZ_SendSequenceHeartbeat()',
            'TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzLastModel),',
            'g_tzExecutionAuthority=KV(text,"execution_authority");',
            'TZ38_LoadRiskContract(text,g_plan.grade,g_plan.setup_type);',
            'FileWriteString(h,"execution_authority="+g_tzExecutionAuthority+"\\r\\n");',
        ),
        label="sequence",
    )
    s = replace_once(s, '#property version   "3.41"', '#property version   "3.42"', label="sequence property version")
    s = replace_once(s, '#define TZ_SEQUENCE_VERSION "3.41"', '#define TZ_SEQUENCE_VERSION "3.42"', label="sequence define version")
    s = replace_once(
        s,
        '#include <TradeZoneCore\\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>',
        '#include <TradeZoneCore\\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>\n'
        '#include <TradeZoneCore\\SniperContractParityV1.mqh>',
        label="sequence parity include",
    )
    s = replace_once(
        s,
        'string g_tzRiskContext="TREND";',
        'string g_tzRiskContext="TREND";\n'
        'int g_tzQualifiedMitigations=0;\n'
        'string g_tzSniperContractFingerprint="";',
        label="sequence parity globals",
    )
    s = replace_once(
        s,
        'TZ38_LoadRiskContract(text,g_plan.grade,g_plan.setup_type);',
        'TZ38_LoadRiskContract(text,g_plan.grade,g_plan.setup_type);\n'
        '   string parityGrade=KV(text,"current_grade");\n'
        '   if(parityGrade!="")g_plan.grade=parityGrade;\n'
        '   string qmit=KV(text,"qualified_mitigations");\n'
        '   if(qmit=="")qmit=KV(text,"touch_count");\n'
        '   g_tzQualifiedMitigations=(int)StringToInteger(qmit);\n'
        '   g_tzSniperContractFingerprint=TZ_SniperContractFingerprint(\n'
        '      g_plan.analysis_id,g_plan.zone_id,g_plan.original_direction,g_plan.grade,\n'
        '      g_tzQualifiedMitigations,g_tzRiskContext,g_tzOriginalRiskPct,g_tzExecutionAuthority);',
        label="sequence loaded parity contract",
    )
    s = replace_once(
        s,
        'FileWriteString(h,"execution_authority="+g_tzExecutionAuthority+"\\r\\n");',
        'FileWriteString(h,"execution_authority="+g_tzExecutionAuthority+"\\r\\n");\n'
        '   FileWriteString(h,"direction="+g_plan.original_direction+"\\r\\n");\n'
        '   FileWriteString(h,"current_grade="+g_plan.grade+"\\r\\n");\n'
        '   FileWriteString(h,"qualified_mitigations="+IntegerToString(g_tzQualifiedMitigations)+"\\r\\n");\n'
        '   FileWriteString(h,"contract_fingerprint="+g_tzSniperContractFingerprint+"\\r\\n");',
        label="sequence state parity echo",
    )
    old_fmt = (
        '\"state_persisted\\":true,\\\"analysis_id\\":\\\"%s\\\",\\\"zone_id\\":\\\"%s\\\",'
        '\\\"plan_valid\\":%s,\\\"execution_authority\\":\\\"%s\\\",\\\"last_execution_model\\":\\\"%s\\\",'
    )
    new_fmt = (
        '\"state_persisted\\":true,\\\"analysis_id\\":\\\"%s\\\",\\\"zone_id\\":\\\"%s\\\",'
        '\\\"plan_valid\\":%s,\\\"execution_authority\\":\\\"%s\\\",'
        '\\\"direction\\":\\\"%s\\\",\\\"current_grade\\":\\\"%s\\\",'
        '\\\"qualified_mitigations\\":%d,\\\"risk_context\\":\\\"%s\\\",'
        '\\\"base_risk_pct\\":%s,\\\"contract_fingerprint\\":\\\"%s\\\",'
        '\\\"last_execution_model\\":\\\"%s\\\",'
    )
    s = replace_once(s, old_fmt, new_fmt, label="sequence heartbeat parity format")
    old_args = 'TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzLastModel),'
    new_args = (
        'TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",'
        'TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_plan.original_direction),TZ_JsonEscape(g_plan.grade),'
        'g_tzQualifiedMitigations,TZ_JsonEscape(g_tzRiskContext),DoubleToString(g_tzOriginalRiskPct,8),'
        'TZ_JsonEscape(g_tzSniperContractFingerprint),TZ_JsonEscape(g_tzLastModel),'
    )
    s = replace_once(s, old_args, new_args, label="sequence heartbeat parity args")
    return s


def build_bridge() -> str:
    b = BRIDGE_OLD.read_text(encoding="utf-8")
    require_all(
        b,
        ('#property version "1.50"', '#define TZ_BRIDGE_VERSION "1.50"', '#define TZ_SEQUENCE_EXPECTED "3.41"'),
        label="bridge",
    )
    b = replace_once(b, '#property version "1.50"', '#property version "1.51"', label="bridge property version")
    b = replace_once(b, '#define TZ_BRIDGE_VERSION "1.50"', '#define TZ_BRIDGE_VERSION "1.51"', label="bridge define version")
    b = replace_once(b, '#define TZ_SEQUENCE_EXPECTED "3.41"', '#define TZ_SEQUENCE_EXPECTED "3.42"', label="bridge sequence expectation")
    return b


def build_parity_include() -> str:
    text = PARITY_INCLUDE_SRC.read_text(encoding="utf-8")
    require_all(
        text,
        (
            '#define TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"',
            'string TZ_SniperCanonicalContract(',
            'string TZ_SniperSHA256(const string text)',
            'string TZ_SniperContractFingerprint(',
        ),
        label="parity include",
    )
    return text


def main() -> None:
    refuse_existing_targets()
    seq = build_sequence()
    bridge = build_bridge()
    parity_include = build_parity_include()

    # Write only after every source anchor has validated and every transformed
    # artifact has been built in memory. This prevents a partial release branch.
    SEQ_NEW.write_text(seq, encoding="utf-8")
    BRIDGE_NEW.write_text(bridge, encoding="utf-8")
    PARITY_INCLUDE_STABLE.write_text(parity_include, encoding="utf-8")
    print(f"generated {SEQ_NEW.relative_to(ROOT)}")
    print(f"generated {BRIDGE_NEW.relative_to(ROOT)}")
    print(f"generated {PARITY_INCLUDE_STABLE.relative_to(ROOT)}")
    print("manifest intentionally unchanged; promotion remains a separate release gate")


if __name__ == "__main__":
    main()

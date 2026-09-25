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


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def require_all(text: str, needles: tuple[str, ...], *, label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise RuntimeError(f"{label}: required anchors missing: {missing}")


def transform_sequence() -> None:
    if SEQ_NEW.exists():
        raise RuntimeError(f"refusing to overwrite immutable target: {SEQ_NEW}")
    s = SEQ_OLD.read_text(encoding="utf-8")
    require_all(
        s,
        (
            '#property version   "3.41"',
            '#define TZ_SEQUENCE_VERSION "3.41"',
            'void TZ_SendSequenceHeartbeat()',
            'TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzLastModel),',
            'g_tzExecutionAuthority=KV(text,"execution_authority");',
            'TZ38_LoadRiskContract(text,g_plan.grade,g_plan.setup_type);',
        ),
        label="sequence",
    )
    s = replace_once(s, '#property version   "3.41"', '#property version   "3.42"', label="sequence property version")
    s = replace_once(s, '#define TZ_SEQUENCE_VERSION "3.41"', '#define TZ_SEQUENCE_VERSION "3.42"', label="sequence define version")

    # We have now captured the real heartbeat serializer and the real /mt5/plan load
    # anchors from v3.41. The next transformation must add the missing contract echo
    # fields and a canonical fingerprint at THIS serializer, not invent a second
    # authority channel. Keep fail-closed until the canonical MQL fingerprint function
    # is proven byte-for-byte compatible with app/sniper_contract_parity.py.
    raise RuntimeError("canonical MQL fingerprint parity not yet proven; refusing partial 3.42 transformation")


def transform_bridge() -> None:
    if BRIDGE_NEW.exists():
        raise RuntimeError(f"refusing to overwrite immutable target: {BRIDGE_NEW}")
    b = BRIDGE_OLD.read_text(encoding="utf-8")
    require_all(b, ('#property version "1.50"', '#define TZ_BRIDGE_VERSION "1.50"', '#define TZ_SEQUENCE_EXPECTED "3.41"'), label="bridge")
    b = replace_once(b, '#property version "1.50"', '#property version "1.51"', label="bridge property version")
    b = replace_once(b, '#define TZ_BRIDGE_VERSION "1.50"', '#define TZ_BRIDGE_VERSION "1.51"', label="bridge define version")
    b = replace_once(b, '#define TZ_SEQUENCE_EXPECTED "3.41"', '#define TZ_SEQUENCE_EXPECTED "3.42"', label="bridge sequence expectation")
    return None


def main() -> None:
    # Sequence intentionally runs first and aborts before any file is written while
    # fingerprint equivalence is pending. This makes the current transformer safe.
    transform_sequence()
    transform_bridge()


if __name__ == "__main__":
    main()

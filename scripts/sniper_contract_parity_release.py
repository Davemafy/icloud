"""Fail-closed verifier for the staged Master Sniper parity release candidates.

The native MT5 SHA-256 proof has already unlocked immutable Sequence 3.42 and
DataBridge 1.51 candidate files on the staging branch. This verifier performs no
manifest promotion and never rewrites those immutable candidates. Any drift aborts.
DEMO / PAPER ONLY until every release gate is complete.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQ_OLD = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_41_BPlusAuthority_Demo.mq5"
SEQ_NEW = ROOT / "mt5/stable/InstitutionalSMC_SequenceEA_v3_42_SniperContractParity_Demo.mq5"
BRIDGE_OLD = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_50_BPlusAuthority.mq5"
BRIDGE_NEW = ROOT / "mt5/stable/InstitutionalSMC_DataBridge_v1_51_SniperContractParity.mq5"
PARITY_INCLUDE_SRC = ROOT / "mt5/include/SniperContractParityV1.mqh"
PARITY_INCLUDE_STABLE = ROOT / "mt5/stable/SniperContractParityV1.mqh"
MANIFEST = ROOT / "mt5/stable/manifest.json"

FROZEN_SHA256 = {
    SEQ_NEW: "a5062ddad59a5ad43f035954832022c2f0815f203b86a714d446fa7b9d6c2583",
    BRIDGE_NEW: "d05c0cd1e7a04b2524c272840d770179a05488b42d0e512b12f553256e74522e",
    PARITY_INCLUDE_STABLE: "5002ee0c56900ed1baee056ed4cba882f1a99627824ccf399ecdf3ac24a4eee0",
}


def require_all(text: str, needles: tuple[str, ...], *, label: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise RuntimeError(f"{label}: required anchors missing: {missing}")


def verify_immutable_sources() -> None:
    old_seq = SEQ_OLD.read_text(encoding="utf-8")
    old_bridge = BRIDGE_OLD.read_text(encoding="utf-8")
    require_all(
        old_seq,
        ('#property version   "3.41"', '#define TZ_SEQUENCE_VERSION "3.41"'),
        label="Sequence 3.41 rollback",
    )
    require_all(
        old_bridge,
        ('#property version "1.50"', '#define TZ_BRIDGE_VERSION "1.50"', '#define TZ_SEQUENCE_EXPECTED "3.41"'),
        label="DataBridge 1.50 rollback",
    )


def verify_sequence_candidate() -> None:
    seq = SEQ_NEW.read_text(encoding="utf-8")
    require_all(
        seq,
        (
            '#property version   "3.42"',
            '#define TZ_SEQUENCE_VERSION "3.42"',
            '#include <TradeZoneCore\\SniperContractParityV1.mqh>',
            "void TZ42_RefreshSniperParityFromPlan(string text)",
            "bool TZ42_NewEntryParitySafe()",
            "bool TZ42_RevalidateParityBeforeOrder()",
            'TZ_SetGate("PARITY","SNIPER_CONTRACT_UNVERIFIED")',
            'TZ_SetGate("PARITY","SNIPER_CONTRACT_MISMATCH")',
            "g_tzExpectedSniperContractFingerprint",
            "g_tzSniperContractAuthority",
            "g_tzSniperContractVerified",
            "g_tzFlipSniperContractVerified",
            "sniper_contract_verified=",
            "sniper_contract_fingerprint=",
            r'\"direction\":\"%s\"',
            r'\"current_grade\":\"%s\"',
            r'\"qualified_mitigations\":%d',
            r'\"risk_context\":\"%s\"',
            r'\"base_risk_pct\":%s',
            r'\"contract_fingerprint\":\"%s\"',
            r'\"expected_contract_fingerprint\":\"%s\"',
            r'\"contract_execution_authority\":\"%s\"',
            r'\"contract_parity_status\":\"%s\"',
            "TZ_PreCoreSync();ManagePositions();Evaluate();",
            "if(!TZ42_NewEntryParitySafe())return false;",
            "if(!TZ42_RevalidateParityBeforeOrder())return;",
        ),
        label="Sequence 3.42 candidate",
    )
    if "v3.41" in seq:
        raise RuntimeError("Sequence 3.42 candidate still contains stale v3.41 runtime labels")


def verify_bridge_candidate() -> None:
    bridge = BRIDGE_NEW.read_text(encoding="utf-8")
    require_all(
        bridge,
        (
            '#property version "1.51"',
            '#define TZ_BRIDGE_VERSION "1.51"',
            '#define TZ_SEQUENCE_EXPECTED "3.42"',
        ),
        label="DataBridge 1.51 candidate",
    )


def verify_parity_include() -> None:
    source = PARITY_INCLUDE_SRC.read_text(encoding="utf-8")
    staged = PARITY_INCLUDE_STABLE.read_text(encoding="utf-8")
    if source != staged:
        raise RuntimeError("staged parity include differs from the native-vector-proven source")
    require_all(
        source,
        (
            '#define TZ_SNIPER_PARITY_VERSION "SNIPER_PARITY_V1"',
            "string TZ_SniperCanonicalContract(",
            "string TZ_SniperSHA256(const string text)",
            "string TZ_SniperContractFingerprint(",
        ),
        label="parity include",
    )


def verify_frozen_candidate_hashes() -> None:
    for path, expected in FROZEN_SHA256.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"candidate SHA-256 drift for {path.relative_to(ROOT)}: {actual} != {expected}"
            )


def verify_manifest_still_locked() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = (
        str(manifest.get("release") or ""),
        str(manifest.get("data_bridge_version") or ""),
        str(manifest.get("sequence_ea_version") or ""),
    )
    if expected != ("6.3.31", "1.50", "3.41"):
        raise RuntimeError(f"manifest advanced before candidate gates completed: {expected}")


def main() -> None:
    for path in (SEQ_NEW, BRIDGE_NEW, PARITY_INCLUDE_STABLE):
        if not path.exists():
            raise RuntimeError(f"required immutable candidate missing: {path}")
    verify_immutable_sources()
    verify_sequence_candidate()
    verify_bridge_candidate()
    verify_parity_include()
    verify_frozen_candidate_hashes()
    verify_manifest_still_locked()
    print("Master Sniper parity candidates verified.")
    print("Candidate SHA-256 values match the frozen promotion fingerprints.")
    print("Stable manifest remains locked at 6.3.31 / 1.50 / 3.41.")


if __name__ == "__main__":
    main()

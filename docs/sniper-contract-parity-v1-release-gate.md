# Master Sniper Contract Parity v1 — Release Gate

Status: DEMO / PAPER ONLY — DO NOT MERGE until all gates pass.

## Authoritative contract

The Cloud and Sequence must agree on all fields below for a new entry to be trusted:

- analysis_id
- zone_id
- direction
- current_grade
- qualified_mitigations
- risk_context
- base_risk_pct
- execution_authority
- deterministic contract fingerprint

## Required semantics

1. `/mt5/plan` remains the execution-authority channel.
2. Sequence heartbeat is observability/echo only; it must not become a second authority channel.
3. Missing or legacy contract telemetry is `UNVERIFIED`.
4. A complete disagreement is `SNIPER_CONTRACT_MISMATCH` and blocks new entries.
5. Contract mismatch must not disable management of an already-open position.
6. Numeric wire representations must canonicalize before fingerprinting.
7. The final fingerprint is stamped only after every Cloud plan safety/separation layer has finalized execution authority.
8. Sequence revalidates the current Cloud fingerprint immediately before a normal order send.
9. Accepted-zone flips may use only a source contract that was already parity-verified when the failed zone was captured.
10. Stable rollback truth remains release 6.3.31 / DataBridge 1.50 / Sequence 3.41 until promotion completes.
11. Existing v1.50/v3.41 stable files remain immutable.

## Proven staging evidence

- [x] Native MT5 canonical-string vector 1 PASS.
- [x] Native MT5 standard SHA-256 `abc` vector PASS.
- [x] Native MT5 canonical-string vector 2 PASS.
- [x] Native HASH1/HASH2 match the frozen Python vectors byte-for-byte.
- [x] Immutable Sequence 3.42 parity candidate staged.
- [x] Immutable DataBridge 1.51 compatibility candidate staged.
- [x] Native-vector-proven parity include staged separately from the rollback stack.
- [x] Stable manifest remains 6.3.31 / 1.50 / 3.41.
- [x] Native MetaEditor candidate compile PASS: DataBridge 1.51 and Sequence 3.42 both 0 errors / 0 warnings; working EAs not replaced or attached.
- [x] Live runtime parity PASS after Cloud finalizer hotfix: MATCH / UNVERIFIED / MISMATCH / OVERALL all PASS; no orders sent.

## Promotion gates

- [x] Cloud reconciliation is wired to `app/sniper_contract_parity.py`.
- [x] Final `/mt5/plan` publishes explicit current grade, qualified mitigations, base risk and fingerprint after authority finalization.
- [x] Sequence 3.42 candidate echoes every authoritative field plus local/expected fingerprint status.
- [x] Sequence 3.42 candidate fails closed for normal new entries on UNVERIFIED/MISMATCH and revalidates immediately before order send.
- [x] Accepted-flip source parity is persisted and legacy/unverified flip state fails closed for new flip entries.
- [x] DataBridge 1.51 expects Sequence 3.42.
- [ ] Full Python regression suite passes at the final candidate head.
- [ ] Python compile/syntax checks pass at the final candidate head.
- [ ] MQL structural checks pass at the final candidate head.
- [x] Native MetaEditor compile proves DataBridge 1.51: 0 errors / 0 warnings.
- [x] Native MetaEditor compile proves Sequence 3.42: 0 errors / 0 warnings.
- [ ] Candidate SHA-256 values are frozen for promotion.
- [x] End-to-end runtime test proves MATCH permits the intended new-entry path.
- [x] End-to-end runtime test proves UNVERIFIED fails closed for new entries.
- [x] End-to-end runtime test proves MISMATCH fails closed for new entries.
- [ ] Runtime test proves existing-position management remains available under mismatch/unverified telemetry.
- [ ] Dashboard/version truth shows the promoted versions consistently.
- [ ] Manifest/updater is promoted only after all preceding gates pass.

## Release method

The proven 1.50 / 3.41 files remain immutable rollback truth. The 1.51 / 3.42 candidates and parity include are immutable staging artifacts on the isolated parity branch. `scripts/sniper_contract_parity_release.py` is now a fail-closed candidate verifier: it verifies rollback versions, candidate parity anchors, the native-proven include, and that the stable manifest has not advanced. Candidate compile/runtime validation is performed without replacing the working MT5 EAs. Manifest promotion remains a separate final operation after all gates above pass.

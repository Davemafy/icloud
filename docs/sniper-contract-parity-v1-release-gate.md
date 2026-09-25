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
7. Stable rollback truth remains release 6.3.31 / DataBridge 1.50 / Sequence 3.41 until promotion completes.
8. Existing v1.50/v3.41 stable files remain immutable; create new versioned files for parity.

## Promotion gates

- [ ] Cloud reconciliation is wired to `app/sniper_contract_parity.py`.
- [ ] Sequence heartbeat echoes every authoritative field plus the fingerprint.
- [ ] DataBridge/Sequence compatibility truth is advanced together where required.
- [ ] Python regression suite passes.
- [ ] Python compile/syntax checks pass.
- [ ] MQL structural checks pass.
- [ ] Stable file SHA-256 checks pass.
- [ ] End-to-end runtime test proves MATCH permits the intended new-entry path.
- [ ] End-to-end runtime test proves UNVERIFIED fails closed for new entries.
- [ ] End-to-end runtime test proves MISMATCH fails closed for new entries.
- [ ] Runtime test proves existing-position management remains available under mismatch/unverified telemetry.
- [ ] Dashboard/version truth shows the promoted versions consistently.
- [ ] Manifest/updater is promoted only after all preceding gates pass.

## Release method

Use the repository-native GitHub Actions transformation pattern so Actions reads the complete immutable source locally, generates the next versioned Sequence/DataBridge files, performs controlled Cloud integration, updates tests/checksums, and validates the resulting branch. Do not reconstruct or overwrite large execution-facing source files from truncated connector output.

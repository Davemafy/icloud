# Clinical Review Remediation — Cloud v6.5.18

Status: DEMO / PAPER ONLY

This document records the 2026-09-16 clinical dashboard review, the verified defects, the false-positive interpretations, and the remediation order. The prime constraint is that observability work must not silently change `/mt5/plan`, zone qualification, AI approval, Sequence EA risk sizing, order placement, stop/target management, or execution authority.

## Phase A — implemented in Cloud v6.5.18

### 1. Version-domain clarity

`Cloud v6.x` is the application release namespace. `MT5 stable package 6.x` is the installer/package release namespace. The numbers are not expected to match.

The dashboard now labels the second number as **MT5 stable package**, not a generic stable release. A difference between the two namespaces is therefore not itself a health alert. Desired / installed / running DataBridge and Sequence component versions remain the authoritative MT5 version-truth checks.

### 2. Updater state semantics

`update_result` is the last installer outcome. `pending_reload` and desired/installed/running component truth describe the current runtime state.

The dashboard now explicitly labels the installer result as historical and the reload field as current state, so a historical `INSTALLED_REATTACH_REQUIRED` result cannot be mistaken for a currently pending restart after both components have already become CURRENT.

### 3. Journal boundary corrected

Only real position/deal lifecycle events are Trade History:

- `ENTRY_OPENED`
- `POSITION_MARK`
- `POSITION_EXIT`
- `TP_HIT`
- `SL_HIT`
- `TRADE_CLOSED`

`ML_CANDIDATE` remains shadow/research telemetry and is no longer counted as a trade or displayed as a planned trade. Performance statistics operate only on genuine executed/closed lifecycle records.

When there are zero closed trades, win rate is displayed as unavailable rather than `0%`.

### 4. Candidate repetition clarified

The ML foundation already stores candidate telemetry by a UNIQUE `candidate_id`. Different closed-M1 candidate observations may legitimately exist for the same institutional zone at different timestamps. These observations are research samples, not separate trades.

The dashboard no longer mixes those research observations into Trade History.

### 5. Dual-side map versus execution journal

The dual-branch map may publish both BUY and SELL institutional hypotheses. The execution journal intentionally follows only actual Sequence position/deal lifecycle. A non-selected map zone should therefore not manufacture a fake journal trade merely to make BUY/SELL logging symmetric.

Both sides remain visible in the zone map; Trade History remains execution-only.

### 6. Refresh wording

The browser uses a 3-second state/SSE refresh. That cadence is not a promise that a new trade or candidate event will be created every 3 seconds. The dashboard wording now says **dashboard refreshes every 3s**.

### 7. Confluence / DXY auditability

The selected-zone audit exposes the actual confluence list rather than only a count. It also translates `DXY support=SUPPORT/CONFLICT` into a directional relationship such as `Supports SELL thesis`.

### 8. Trade ID presentation

Raw pipe-delimited internal trade IDs remain available for trace/export, but the human Trade History display uses a readable execution label / position identifier.

### 9. Diagnostic units

`Distance H1 ATR` is relabeled **Distance (× H1 ATR)**.

### 10. Armed-zone semantics

The previously implemented dashboard split remains authoritative for presentation:

- HTF setup quality
- Execution readiness

An A/A+ zone can remain structurally valid while execution readiness is `WAITING FOR LOCATION` and M1 handoff is `NO`.

## Findings that were not confirmed as defects

### Cloud version versus MT5 package version

Not a mismatch. They are separate release domains.

### Journal structurally unable to close trades

Not confirmed. The DataBridge already uses `OnTradeTransaction()` to publish `ENTRY_OPENED`, exit events, and `TRADE_CLOSED`. The observed zero closed trades means no complete paper execution lifecycle had been received at that point; the real defect was that research candidates were being miscounted as trades.

### Same-zone ML candidates equal duplicate trades

Not correct. Candidate observations are research telemetry. Durable institutional identity already exists separately through the zone-reaction lifecycle `reaction_key` (`direction | source_tf | source_ts`). Public display IDs may change when candidates are re-ranked, but the historical institutional reaction record persists.

### Browser 3-second refresh equals 3-second signal polling

Not correct. The 3-second cadence is browser state refresh only.

## Phase B — telemetry-only MT5 hardening (next, separately released)

These items require an MT5 component rebuild/reload even though they do not need to change execution decisions. They should therefore be released separately and verified on DEMO/PAPER before activation.

1. **Chart-state parity** — DataBridge chart comment should show the backend execution-readiness enum (`WAIT_LOCATION`, `M1_READY`, `SAFETY_BLOCKED`, etc.) instead of only `SELL ARMED | BUY ARMED`.
2. **Runtime risk telemetry** — Sequence heartbeat should publish read-only effective runtime inputs: thesis risk %, primary/re-entry shares, flip multiplier, daily loss guard state/limit, max re-entries, current open Sequence exposure, and demo-only status. The dashboard may display them but must not remotely mutate them.
3. **Snapshot receipt-age telemetry** — distinguish source timestamp age from cloud receipt age so transport lag and clock skew can be diagnosed independently without changing the execution stale-snapshot guard.

## Phase C — execution-state identity migration (requires explicit paper validation)

The institutional lifecycle already has a durable `reaction_key`, while the current Sequence persistent-state namespace is keyed from analysis/zone identifiers. Migrating Sequence execution counters to a durable institutional key would alter execution-state persistence semantics.

Therefore it must **not** be hidden inside a dashboard patch. It should be a separately versioned paper-only Sequence release with migration/backward-compatibility tests before promotion.

## Risk-panel rule

The dashboard must not display source-code defaults as if they were live runtime settings. Until the Sequence heartbeat publishes effective runtime risk inputs, risk visibility should be marked incomplete. Any future editable risk control requires an explicit, validated configuration contract and must remain DEMO/PAPER until separately approved.

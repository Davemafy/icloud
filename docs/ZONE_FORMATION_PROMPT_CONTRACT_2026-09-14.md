# Zone Formation Prompt Contract — 2026-09-14

Status: authoritative reference for the DEMO / PAPER ONLY XAU zone map.
Contract ID: `ZONE_FORMATION_PROMPT_2026_09_14_V659`

This contract is derived from the user's institutional XAU master-sniper framework and the 2026-09-16 refinement request. Future zoning changes must preserve these rules unless the user explicitly replaces them.

## Purpose

Find the MOST IMPORTANT institutional price levels where XAUUSD is most likely to react, reverse, or continue today. Do not force a zone simply to fill a BUY or SELL slot.

## Timeframe authority

- XAU D1: context and external structure.
- XAU H4: main institutional source/location.
- XAU H1: refinement of H4 or tactical fallback.
- XAU M15: zone health, mitigation and accepted invalidation.
- XAU M1: entry timing only; it cannot redefine the HTF zone.
- DXY D1 + H1: confirmation only; it cannot create or move an XAU zone.
- News, ATR and spread: safety/context inputs.

## Source requirements

A zone must be anchored to a visible H4/H1 institutional source that either:

1. caused decisive displacement/BOS away, or
2. swept liquidity, rejected, and was followed by decisive displacement.

FVG/imbalance, rejection wick, premium/discount, psychological level, tick-volume expansion and H4/H1 overlap are quality confluences. They do not replace the required structural liquidity.

Equal highs/equal lows are liquidity objects only. They may represent BSL/SSL, inducement or sweep objectives, but they do not create a trading zone by themselves. A valid H4/H1 institutional source is still mandatory.

## Liquidity is mandatory

- SELL supply requires structural BSL physically inside the final marked envelope.
- BUY demand requires structural SSL physically inside the final marked envelope.
- The attached BSL/SSL must leave the required distal sweep reserve inside the same envelope.
- Liquidity must not be invented.
- A PSY level alone never qualifies a zone.

## Professional zone geometry

Trade Zone XAU convention: 1 pip = 10 broker points.

Geometry is source-timeframe specific so the chart remains precise without squeezing a genuine H4 location into an H1-sized box:

| Source | Core | Outer envelope |
| --- | --- | --- |
| H1 tactical | 60–100 pips | 140–220 pips |
| H4 structural | 80–140 pips | 180–260 pips |
| H4>H1 refinement | 60–100 pips H1-refined core | 180–260 pips H4 parent envelope |

Hard sweep rule:

- Minimum distal sweep room = 50 pips.
- SELL reserves at least 50 pips above the attached BSL inside the envelope.
- BUY reserves at least 50 pips below the attached SSL inside the envelope.
- If source + required liquidity + sweep room cannot fit inside the applicable source-timeframe maximum envelope, reject the candidate.
- Do not widen the zone beyond its source-timeframe maximum merely to make liquidity fit.

The core is the tactical execution location. The outer envelope is context, structural sweep room and M15 thesis invalidation; it is not a blind entry area.

## Current-price side rule

This is mandatory for the intraday alert map:

- BUY zone must be below current price, or current price may already be inside/interacting with it.
- SELL zone must be above current price, or current price may already be inside/interacting with it.
- A BUY zone completely above current price is rejected from the BUY alert map.
- A SELL zone completely below current price is rejected from the SELL alert map.
- A wrong-side zone is NOT automatically flipped.

## Selection for today

- Publish at most one PRIMARY BUY and one PRIMARY SELL.
- Never force both primary sides.
- If no valid BUY exists below/interacting with price, PRIMARY BUY = NONE.
- If no valid SELL exists above/interacting with price, PRIMARY SELL = NONE.
- Structural validity is mandatory before ranking.
- A+, A and B+ are new execution grades. B+ is reduced-risk execution authority at 0.25% and still requires every normal M15/M1/AI/safety gate.
- TREND and COUNTERTREND do not use the same qualification rubric.
- TREND grades continuation-source quality: HTF authority, displacement/BOS strength, freshness, premium/discount location and supporting FVG/volume evidence.
- COUNTERTREND grades reversal-location quality: HTF extremity, required structural liquidity inside the envelope, actual sweep/rejection evidence, source response strength, H4>H1 agreement and supporting FVG/volume/PSY evidence.
- Countertrend is not downgraded merely because D1 points the other way; instead it must satisfy the dedicated reversal rubric.
- Base thesis risk uses the context x grade matrix before sequence-share/model multipliers: TREND A+ = 1.00%, TREND A = 0.75%, COUNTERTREND A+ = 0.50%, COUNTERTREND A = 0.25%.
- Historical profit after price leaves a zone must never retroactively upgrade that zone's grade. Strong post-reaction momentum validates lifecycle/execution quality and future re-entry research, not the original pre-entry classification.
- **Zone grade is immutable for the life of an analysis cycle.** Qualified mitigations, raw contacts and touch counts are observation/journal telemetry only. They must never downgrade or upgrade grade, change the context risk allocation, alter ranking, block execution authority, or remove a still-structurally-valid zone.
- A zone is retired/replaced only by its defined structural invalidation or a new institutional analysis cycle. The lifecycle record preserves the original published grade and telemetry separately.
- Among already-valid execution-grade candidates on the correct side of price, TODAY'S REACHABILITY is ranked before freshness and remote HTF authority.
- A nearer valid zone may outrank a remote fresher zone under the deterministic ranking contract; grade remains an explicit quality/risk tiebreaker.
- Freshness remains important after intraday reachability is established; repeated mitigation still downgrades quality.
- H4/H4>H1 authority remains a quality tiebreaker, not permission to ignore a much nearer valid institutional location.
- Distance never creates a zone and never excuses missing BSL/SSL.
- A remote valid HTF source may remain context rather than the primary intraday alert.

## Secondary reserve level

A second level may be published as a BACKUP only. It is not a second active execution zone.

- At most one SECONDARY SELL and one SECONDARY BUY may be shown.
- SECONDARY must pass the same structural source, BSL/SSL, source-timeframe geometry, freshness and M15-health rules as a primary zone.
- SECONDARY must be A+ with no more than one core mitigation, or A with no more than two qualified core mitigations.
- SECONDARY must come from a distinct institutional source and must not overlap the primary envelope.
- For SELL: Level 2 must be a higher supply zone beyond the primary SELL invalidation side.
- For BUY: Level 2 must be a lower demand zone beyond the primary BUY invalidation side.
- While Level 1 is valid, Level 2 is `RESERVE` / context only and has zero M1 execution authority.
- Level 1 invalidation does not instantly activate Level 2.
- After closed-M15 accepted invalidation of Level 1, a fresh analysis must requalify Level 2. It must still be active, on the correct side of price, retain the required structural liquidity and pass all normal safety rules.
- Once requalified as the new primary, the normal M1 sweep -> MSS/BOS -> displacement -> dealing range -> value/OTE/PD-array sequence is still mandatory.
- If no clean non-overlapping reserve exists, SECONDARY = NONE. Do not manufacture a backup zone.

## Chart rendering

The MT5 chart is presentation only; rendering cannot create or authorize zones.

- PRIMARY zones may use a soft filled envelope with a slightly stronger core.
- RESERVE zones use a lighter/dashed presentation and remain visually subordinate to Primary.
- Labels must include direction, role, grade, state and touch count.
- Up to four qualified records may be rendered: Primary SELL, Reserve SELL, Primary BUY, Reserve BUY. These form the four-zone research map: two SELL locations and two BUY locations maximum, never forced.
- Missing records are not forced.

## Mitigation and invalidation

- Raw core contact and qualified mitigation are different facts. Raw contact is diagnostic only and must never downgrade a zone by itself.
- A freshness-degrading mitigation is a completed, directionally correct institutional re-use cycle:
  - SELL = a CLOSED M15 bar below the full envelope arms the cycle -> price later overlaps the tactical core -> a CLOSED M15 bar returns below the full envelope and completes the reaction.
  - BUY = a CLOSED M15 bar above the full envelope arms the cycle -> price later overlaps the tactical core -> a CLOSED M15 bar returns above the full envelope and completes the reaction.
- The core-touch timestamp and the mitigation-qualified timestamp are separate. Grade/freshness changes only at the completed expected-side exit, never at the first wick/contact.
- A SELL core contact approached from ABOVE is not a SELL mitigation. A BUY core contact approached from BELOW is not a BUY mitigation. Wrong-side interactions remain auditable but consume zero freshness.
- Continuous chop/absorption inside one envelope remains one interaction campaign. Repeated core-edge oscillations inside that campaign cannot create additional mitigations.
- A contact with no prior expected-side closed-envelope arm is not a qualified mitigation.
- The mitigation clock starts only after the source is causally available: H1 source at H1 candle close, H4 source at H4 candle close, and H4>H1 refinement after both parent and refinement candles are closed.
- If supplied M15 history begins after that source-ready timestamp, freshness is UNVERIFIED. The structural source may remain visible, but a structural A/A+ source is capped to B+ / WATCH for new execution until full freshness can be proven; the engine must never infer zero touches from missing history.
- Closed M15 accepted invalidation on the distal side terminates the original zone's mitigation ledger permanently. Any later crossing belongs to flip/reclaim lifecycle and cannot resume or change the old zone's freshness count.
- Historical mitigation grading must therefore retain an audit ledger containing approach side, arm time, core-touch time, qualification/exit time, counted YES/NO reason and grade effect.
- A+ execution eligibility is limited to 0–1 qualified mitigation.
- A execution eligibility may persist through a second qualified mitigation at the reduced A risk tier.
- Three-plus qualified mitigations are B+ research context / WATCH ONLY and must not obtain new execution authority.
- Repeated qualified mitigation downgrades quality; it must not move or manufacture the zone.
- A wick-only liquidity raid does not invalidate.
- Invalidation creates only a flip candidate; it is not an instant reverse entry.

## Context x grade research risk

DEMO / PAPER validation sizing uses a fixed validation-capital anchor rather than upward compounding.

- Validation initial capital = 10,000.
- TREND A+ base thesis budget = 1.00% of the sizing base.
- TREND A base thesis budget = 0.75%.
- COUNTERTREND A+ base thesis budget = 0.50%.
- COUNTERTREND A base thesis budget = 0.25%.
- B+ base thesis budget = 0.00%; B+ is WATCH / research context only.
- Sizing base = the lesser of current realized account balance and the 10,000 validation anchor, so losses reduce future size but gains do not compound the experiment.
- Existing primary/re-entry/flip share multipliers and model-specific reductions still apply inside that base thesis budget and may reduce it, never increase it.
- Lot calculation must use the actual entry-to-stop monetary loss per lot when available, floor to broker volume step, and return no trade if the calculated size is below broker minimum. It must never round a sub-minimum risk upward.
- On hedging accounts, TP1/TP2/runner splitting must never create more aggregate volume than the risk-sized total.

## Exact publication-time execution truth

- Structural history and live execution truth are separate. Historical touches used for freshness/grading may pre-date the moment an exact zone geometry was first published.
- Every exact user-facing geometry (zone id + source identity + core + envelope) receives its own publication timestamp and touch baseline.
- Historical contacts that occurred before that exact geometry was published remain research/freshness evidence only. They must never create `M1_READY`, a reaction window, thesis ownership, or execution authority.
- A normal core handoff requires actual live bid/ask overlap with the tactical core after publication, or a later M15 bar whose own open timestamp is after publication and whose range intersects the core.
- An M15 bar already in progress when a new geometry is first published is not trusted for retrospective core contact because its high/low may contain pre-publication price action.
- A requalified/reselected geometry starts a new publication clock even when it shares the same underlying source candle/liquidity identity.
- Outer-zone sweep and pre-zone liquidity-reversal handoffs must also use events that occurred after the exact context geometry was published.
- Dashboard truth must show the publication timestamp, touch baseline at publication, and whether a genuine post-publication live core contact has occurred. `RETEST_ONLY_NO_LIVE_CONTACT` means the zone is structurally valid but cannot claim a historical touch as execution authority.
## M1 execution handoff

The outer envelope is institutional location and sweep room. It is NOT an M1 execution trigger.

For the first primary entry:

- M1 handoff begins only when price reaches the tactical core or a very small core buffer.
- The core buffer is the greater of 5 broker points or 0.10 M15 ATR.
- Being anywhere inside the outer envelope must not set primary `zone_context` or `recent_zone_interaction` by itself.
- After core handoff, execution still requires `sweep -> MSS/BOS -> displacement -> new M1 dealing range -> value/OTE/PD-array retracement -> entry`.
- No chase and no blind entry.

Re-entry is different: after a valid primary exists and the position/thesis is protected, re-entry follows the existing continuation/re-entry contract and does not have to revisit the original core.

### Strategic supplemental M1 entry models

The Master Sniper location contract remains the authority. Supplemental entry models exist only to capture more valid opportunities after institutional location has already been earned; they never manufacture location or bypass the normal execution chain.

- **Momentum pullback:** continuation BOS/displacement followed by a controlled 30-60% retracement into a fresh M1 PD array.
- **VWAP-proxy reclaim:** XAUUSD CFD tick-volume-weighted fair-value proxy used only as a continuation confluence, never represented as centralized exchange VWAP or order flow. It still requires BOS/displacement plus a fresh M1 PD array overlapping the reclaim band.
- **London/NY opening-range breakout/retest:** session opening-range displacement followed by a return to a fresh M1 PD array overlapping the broken opening-range boundary.
- Strategic models are allowed only for a valid `CONTINUATION` thesis and only when the Cloud M15 regime/model flag and the local M1 regime both permit the model. Momentum and ORB require local `TREND` or `EXPANSION`; VWAP reclaim requires local `TREND`.
- A strategic **first entry** still requires recent institutional-zone interaction plus live HTF handoff authority. It then passes the same closed-M1 directional rejection/micro-break confirmation, no-chase, target, minimum-RR, parity, spread/news/snapshot and risk gates as the normal primary.
- A strategic **re-entry** is permitted only while the original thesis is still valid and the normal re-entry contract permits another leg; if positions remain open they must already be protected. It uses the same closed-M1 re-entry confirmation and re-entry cap as ordinary R1/R2.
- Every strategic model must contain real M1 structure break/displacement and a fresh OB/FVG PD array. A session boundary, momentum retracement band or VWAP proxy by itself is never an entry.
- Strategic model risk is multiplied by a conservative research factor (`0.75` at this release). This factor may reduce the normal thesis allocation and may never increase it.
- Strategic first entries inherit the full institutional-zone distal stop floor. If that correct stop destroys minimum RR, the trade is rejected rather than tightening the stop.
- Order-flow imbalance remains disabled until an appropriate centralized/depth feed exists.

## Institutional liquidity objectives

Zone validity and target quality are separate decisions. A valid institutional zone must never be removed, moved or downgraded merely because an old TP map is poor.

For an original SELL, targets are drawn from structural SSL below the legitimate core entry area. For an original BUY, targets are drawn from structural BSL above the legitimate core entry area.

Target hierarchy:

1. TP1 = nearest valid internal/structural liquidity on the profitable side of the full core.
2. TP2 = a deeper H4/D1 or prior-day liquidity pool when available; do not fill the ladder with several tiny nearby H1 pivots simply because they are closest.
3. TP3 = when a valid opposing primary zone exists, front-run its proximal envelope edge with a small spread/M15-ATR buffer. That opposing zone is the natural destination of the current move.
4. Do not automatically target through a still-valid opposing institutional zone. A runner beyond it requires a fresh analysis after M15 accepted invalidation/requalification of that opposing area.
5. If there are fewer valid structural objectives, leave unused targets empty rather than inventing prices.
6. If an already-acquired thesis is flat and a newly qualified active opposing primary appears before its frozen deepest objective, the owner may receive a one-way lifecycle objective cap at the same canonical opposing-zone front-run price. This cap is permitted only when a fresh Sequence heartbeat proves zero open positions.
7. For a flat owner, cap reachability is measured from the current executable market quote, not from the historical ownership anchor. The old anchor is audit/handoff history and may legitimately sit beyond the new opposing-zone cap after price retraces. The cap must still be ahead of the current quote by the normal spread-aware target gap.
8. The cap never rewrites the frozen ownership-zone payload or original objective history, never moves an objective farther away, and never changes a live position target. If positions are open or Sequence position truth is unavailable, reconciliation is deferred.
9. A newly established owner cap cannot be claimed from pre-cap price history. Only quote/bar evidence at or after the cap-set timestamp may complete it. Reaching the cap completes/releases the owner thesis; it does not grant the opposing side an instant entry.

Stop logic remains liquidity/structure based:

- For the FIRST entry of an institutional thesis, the M1 timing anchor may refine entry timing but may never pull the protective stop back inside the full active institutional zone.
- FIRST SELL entry SL = the farther of (a) the actual M1 BSL sweep extreme plus buffer and (b) the full institutional zone distal high plus buffer.
- FIRST BUY entry SL = the farther of (a) the actual M1 SSL sweep extreme minus buffer and (b) the full institutional zone distal low minus buffer.
- The buffer is spread/ATR/broker-stop aware. It must be at least 5 broker points and at least 1.5x the live spread in price terms, and it may be widened by the existing M1 ATR stop buffer or broker minimum stop distance.
- If this structurally correct first-entry stop makes minimum RR fail, the trade is rejected. The system must never tighten the SL back inside the zone merely to manufacture acceptable RR.
- Re-entries after a thesis has already progressed may use their local M1 continuation structure because they are not the original institutional-zone risk event.

Session context changes patience, not zone validity:

- A valid H4/H1 zone remains valid during Asia unless normal structural/M15 invalidation occurs.
- Low Asian volatility is not permission to delete a valid zone or force an artificially close TP.
- During Asia, the system may take the first structural liquidity partial while keeping the deeper H4/D1 or opposing-zone objective open into the next liquid session, provided the thesis remains valid and normal risk rules remain satisfied.
- London/New York participation may accelerate delivery but does not manufacture a zone or a target.

## Persistent reaction lifecycle

A valid institutional zone must keep its historical identity after it interacts and reacts, even if a later analysis selects a different primary zone.

Lifecycle:

`ARMED -> INTERACTING -> REACTION_CONFIRMED -> OBJECTIVE_IN_PROGRESS -> OBJECTIVE_COMPLETE`

- `INTERACTING` begins only after the tactical core is reached.
- `REACTION_CONFIRMED` requires core interaction followed by a favourable move of at least the greater of 0.50 M15 ATR or 10 XAU pips.
- Once reaction is confirmed, later primary-map re-selection must not erase or rewrite that fact.
- Target hits and maximum favourable excursion remain attached to that institutional source in persistent storage.
- If the deepest planned liquidity objective is reached, status becomes `OBJECTIVE_COMPLETE`.
- For a flat acquired owner with a valid one-way opposing-zone objective cap, reaching that post-cap destination also becomes `OBJECTIVE_COMPLETE` while the frozen original ladder remains audit truth.
- If closed-M15 accepted invalidation occurs before a confirmed reaction, status becomes `INVALIDATED`.
- If accepted invalidation occurs only after a valid reaction, history becomes `INVALIDATED_AFTER_REACTION`; the prior successful reaction remains preserved.
- A historical reaction record is observation/journal truth only. It grants no automatic execution authority to an old zone.
- A fresh continuation/re-entry still requires the normal live execution contract and thesis validity.
- Context-grade V2 migration rule: a historical owner whose frozen zone is no longer execution-eligible (notably a pre-V2 B+ owner) must not monopolize execution forever after its campaign is flat. Its execution lock may be retired only when a fresh Sequence heartbeat explicitly reports zero open positions. If Sequence position truth is stale/unavailable or positions remain open, keep the lock fail-closed. Retiring the execution lock must preserve the reaction lifecycle, objective history and audit trail.
- After such a flat legacy lock is retired, the normal no-owner A+/A two-sided authority rules resume; no opposite trade is created automatically and fresh location plus the full M1 sequence remain mandatory.

## Directional target safety

Targets are execution constraints, not decorative levels.

- SELL: every active TP must be below the actual SELL candidate entry by a spread-aware safety gap.
- BUY: every active TP must be above the actual BUY candidate entry by a spread-aware safety gap.
- Primary target export is first sanitized against the entire tactical core: SELL objectives must be below the core low; BUY objectives must be above the core high.
- On every live plan poll, objectives are checked again against the current executable side using at least 1.5× live spread or 5 broker points, whichever is larger.
- Wrong-side targets are removed from the exported plan/telemetry.
- If no directionally valid primary target remains, MT5 receives `WATCH_ONLY`; the candidate cannot execute.
- A flip BUY target must remain above the failed SELL envelope; a flip SELL target must remain below the failed BUY envelope.

## No-owner two-sided execution authority

When there is no acquired thesis lock, the published PRIMARY BUY and PRIMARY SELL remain independent
institutional candidates. A D1-aligned plan selection is a planning preference, not exclusive execution
authority.

- A currently interacting/qualified A+ or A primary may earn M1 authority even when it is counter to D1. Countertrend status reduces risk; it does not weaken the M1 confirmation standard.
- Current executable location ranks before D1 preference. D1 remains context and a tie-breaker when
  otherwise comparable candidates are simultaneously executable.
- The countertrend side must still pass the same HTF source, liquidity, geometry, M15 health, M1
  sweep/MSS/BOS/displacement/value reaction, safety, directional-target and minimum-RR requirements.
- Once one side acquires a legitimate execution handoff and thesis ownership, the existing ownership
  contract becomes sticky and the opposite side is blocked until that thesis is released.
- A MAP CONTEXT label must never by itself prevent an independently valid, currently interacting opposite
  primary from being evaluated for M1 authority while no thesis owner exists.

## Future-change rule

When zoning, execution-handoff, lifecycle, rendering or target code is modified, compare the proposed behavior against this contract first. Do not restore old behavior that forces two zones, promotes equal highs/equal lows into zones without a valid H4/H1 source, publishes BUY above price, publishes SELL below price, automatically chooses a remote HTF zone over a much nearer equally-valid intraday institutional location, grants execution authority to a Level-2 reserve while Level 1 remains valid, treats outer-envelope contact as primary M1 handoff, removes a structurally valid zone because of a weak TP map, erases a confirmed institutional reaction because a later analysis reselects the primary map, selects targets only because they are the nearest prices, targets through an active opposing institutional zone without requalification, lets a frozen acquired-owner objective ignore a newly qualified opposing primary while the campaign is flat, retroactively completes a newly-created owner cap from pre-cap price history, mutates a live position target during owner-cap reconciliation, places a first-entry protective stop inside the full institutional zone merely because a nearer M1 timing anchor exists, lets a strategic Momentum/VWAP/ORB model manufacture authority without valid location + regime + fresh PD-array + closed-M1 confirmation, or allows a target on the wrong side of the actual candidate entry.

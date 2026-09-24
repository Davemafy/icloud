# MASTER SNIPER SYSTEM CONTRACT V6.6

## Authority
This contract is the canonical decision model for the Institutional SMC AI Cloud. It is not a dashboard prompt, zoning patch, or special-case rule. Every analytical and execution-facing subsystem must consume decisions derived from this contract. A legacy rule may add diagnostics but may not contradict or override it.

Historical examples such as a 4275-4290 sell source are regression fixtures only. No price-specific production logic is permitted.

## Inputs / evidence boundary
Use only captured system evidence for the current analysis snapshot:
- XAUUSD D1, H4, H1, M15 for analysis and M1 for execution timing.
- DXY D1, H4, H1 as supporting context only.
- current XAU ATR, spread and captured daily news context.
- no manufactured structure, liquidity, FVG, zone, touch, confirmation or directional fact.

If required evidence is absent or stale, fail closed for execution and expose the missing evidence.

## Canonical pipeline
1. Snapshot/evidence integrity.
2. D1 context: external structure, major swing liquidity, displacement, major institutional sources, premium/discount context.
3. H4 primary institutional map: structure/BOS/CHOCH, external/internal liquidity, displacement, source candles, FVG/imbalance, supply/demand, sweeps/manipulation.
4. H1 tactical refinement: refine valid H4 ideas or provide independent institutional sources when evidence supports them.
5. M15 health: mitigation history, directional approach, rejection/acceptance, zone invalidation, intraday manipulation. M15 does not manufacture an H4/H1 zone.
6. Daily scenario engine: continuation and reversal remain explicit possibilities. Direction is an output of current structure and interaction, never a prerequisite used to fabricate a zone.
7. Zone qualification/ranking and risk class.
8. M1 execution sequence only after price interacts with a qualified zone and required confirmation exists.
9. Trade management, targets, flip/re-entry and journal consume the same canonical thesis and zone IDs.
10. Dashboard/API expose exactly the canonical object and its evidence/audit trail.

## Institutional zone formation
A zone begins at the actual institutional source that caused or clearly participated in meaningful displacement/BOS or a confirmed liquidity-sweep rejection. H4 is primary; H1 refines or independently supplies a tactical source when justified.

Geometry is source-exact:
- core = native source body / native tactical source core;
- envelope = actual source candle high-low;
- no fixed-width 100/150/200/300-point manufacture;
- no ATR padding;
- no remote-liquidity expansion;
- no minimum sweep-room expansion.

Liquidity, FVG, psychological levels, volume and DXY are confluence/context/ranking evidence. They cannot move the source boundaries. External liquidity does not invalidate a valid source merely because it lies outside the candle.

A source must still prove institutional relevance. A random candle is not a zone. The audit must identify source timestamp, timeframe, source kind, displacement/sweep evidence, structure relationship, FVG if present, liquidity relationship, location and mitigation history.

## Four-zone / risk architecture
The system may publish up to four qualified opportunities, without manufacturing a missing class:
- trend A+ -> 100% of configured base risk;
- trend A -> 75%;
- countertrend A+ -> 50%;
- countertrend A -> 25%.

B+ remains watch/research unless the separately versioned risk policy explicitly authorizes execution. Risk classification cannot alter zone geometry.

## Mitigation / touch authority
Raw overlap is diagnostic only. Freshness changes only on a qualified directional mitigation episode. Wrong-side crossings, movement from inside to outside, or contacts occurring after accepted invalidation cannot be counted as fresh mitigations of the original thesis.

Every counted mitigation must expose timestamp, approach side, core contact, completed reaction/exit side, qualification result and grade effect.

## Invalidation
List confirmations that can invalidate the thesis/zone. Geometry invalidation is accepted M15 body closure beyond the true institutional source envelope with follow-through/acceptance as defined by the health engine. Wick-only liquidity raids do not automatically invalidate. Once accepted invalidation occurs, later crossings belong to flip/reclaim logic and cannot continue degrading the original zone.

Structural invalidation may also occur when the higher-timeframe structure that justified the source is demonstrably broken by captured evidence; this must be separately audited from geometric invalidation.

## Direction and market side
Do not delete a structurally valid historical source merely because current price is now above/below it. Market side, distance, ATR reachability, session/news context and directional thesis rank whether it is relevant today. They do not rewrite history.

## Required analysis object
One canonical MasterSniperAnalysis must drive downstream behavior and expose at minimum:
- evidence_complete / missing_evidence;
- D1/H4/H1/M15 structure summaries;
- XAU and DXY context;
- ATR/spread/news context;
- liquidity map and priority pools;
- imbalance/FVG map;
- institutional source ledger;
- qualified zones with exact geometry and source evidence;
- mitigation ledger and invalidation evidence;
- continuation scenario and reversal scenario;
- trend/countertrend classification;
- grade and risk class;
- M1 alert/entry prerequisites;
- SL/invalidation and targets;
- flip/re-entry eligibility;
- human-readable brief and machine audit/version.

No downstream subsystem may independently recompute a contradictory zone or thesis from legacy heuristics.

## Output contract
The public analysis remains brief but must be generated from the canonical object in this order:
1. Daily summary
2. H4 summary
3. H1 summary
4. most important institutional zones with exact prices and reasons
5. best A+ buy/sell alert levels when qualified
6. M1 entry model, SL/invalidation and TP
7. explicit invalidation confirmations

## Non-negotiable tests
- no hard-coded historical price special cases;
- same rules for BUY and SELL;
- source-exact geometry survives downstream processing unchanged;
- external liquidity cannot stretch or erase a source by itself;
- M15/M1 cannot manufacture H4/H1 zones;
- raw touches cannot downgrade freshness;
- post-invalidation crossings cannot downgrade original zone;
- risk cannot change geometry;
- dashboard/API/sequence consume identical canonical zone IDs and thesis version;
- missing required evidence fails closed for execution.
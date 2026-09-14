# Zone Formation Prompt Contract — 2026-09-14

Status: authoritative reference for the DEMO / PAPER ONLY XAU zone map.
Contract ID: `ZONE_FORMATION_PROMPT_2026_09_14_V656`

This contract is derived from the user's institutional XAU master-sniper prompt supplied on 2026-09-14. Future zoning changes must preserve these rules unless the user explicitly replaces them.

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

## Liquidity is mandatory

- SELL supply requires structural BSL physically inside the final marked envelope.
- BUY demand requires structural SSL physically inside the final marked envelope.
- Liquidity must not be invented.
- A PSY level alone never qualifies a zone.

## Zone geometry

Trade Zone XAU convention: 1 pip = 10 broker points.

- Core: 100–200 pips.
- Envelope: 300–400 pips.
- Minimum distal sweep room: 50 pips.
- SELL reserves at least 50 pips above the BSL inside the envelope.
- BUY reserves at least 50 pips below the SSL inside the envelope.
- If source + required liquidity + sweep room cannot fit inside the envelope contract, reject the candidate.

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
- A/A+ execution quality is preferred over B+ WATCH quality.
- Among already-valid A/A+ candidates on the correct side of price, TODAY'S REACHABILITY is ranked before freshness and remote HTF authority.
- A nearer valid A/A+ zone must be allowed to outrank a remote valid A/A+ zone even when the remote zone has 0 touches and the nearer one has 1 touch.
- Freshness remains important after intraday reachability is established; repeated mitigation still downgrades quality.
- H4/H4>H1 authority remains a quality tiebreaker, not permission to ignore a much nearer valid institutional location.
- Distance never creates a zone and never excuses missing BSL/SSL.
- A remote valid HTF source may remain context rather than the primary intraday alert.

## Secondary reserve level

A second level may be published as a BACKUP only. It is not a second active execution zone.

- At most one SECONDARY SELL and one SECONDARY BUY may be shown.
- SECONDARY must pass the same structural source, BSL/SSL, geometry, freshness and M15-health rules as a primary zone.
- SECONDARY must be A or A+ and have no more than one core mitigation.
- SECONDARY must come from a distinct institutional source and must not overlap the primary envelope.
- For SELL: Level 2 must be a higher supply zone beyond the primary SELL invalidation side.
- For BUY: Level 2 must be a lower demand zone beyond the primary BUY invalidation side.
- While Level 1 is valid, Level 2 is `RESERVE` / context only and has zero M1 execution authority.
- Level 1 invalidation does not instantly activate Level 2.
- After closed-M15 accepted invalidation of Level 1, a fresh analysis must requalify Level 2. It must still be active, on the correct side of price, retain the required structural liquidity and pass all normal safety rules.
- Once requalified as the new primary, the normal M1 sweep -> MSS/BOS -> displacement -> dealing range -> value/OTE/PD-array sequence is still mandatory.
- If no clean non-overlapping reserve exists, SECONDARY = NONE. Do not manufacture a backup zone.

## Mitigation and invalidation

- Fresh 0–1 touch zones rank highest within comparable intraday relevance.
- Repeated mitigation downgrades quality; it must not move or manufacture the zone.
- Closed M15 body acceptance beyond the outer envelope invalidates the original zone.
- A wick-only liquidity raid does not invalidate.
- Invalidation creates only a flip candidate; it is not an instant reverse entry.

## M1 execution handoff

The wide outer envelope is institutional location and sweep room. It is NOT an M1 execution trigger.

For the first primary entry:

- M1 handoff begins only when price reaches the tactical core or a very small core buffer.
- The core buffer is the greater of 5 broker points or 0.10 M15 ATR.
- Being anywhere inside the 300–400 pip envelope must not set primary `zone_context` or `recent_zone_interaction` by itself.
- After core handoff, execution still requires `sweep -> MSS/BOS -> displacement -> new M1 dealing range -> value/OTE/PD-array retracement -> entry`.
- No chase and no blind entry.

Re-entry is different: after a valid primary exists and the position/thesis is protected, re-entry follows the existing continuation/re-entry contract and does not have to revisit the original core.

## Directional target safety

Targets are execution constraints, not decorative levels.

- SELL: every active TP must be below the actual SELL candidate entry by a spread-aware safety gap.
- BUY: every active TP must be above the actual BUY candidate entry by a spread-aware safety gap.
- Primary target export is first sanitized against the entire tactical core: SELL objectives must be below the core low; BUY objectives must be above the core high.
- On every live plan poll, objectives are checked again against the current executable side using at least 1.5× live spread or 5 broker points, whichever is larger.
- Wrong-side targets are removed from the exported plan/telemetry.
- If no directionally valid primary target remains, MT5 receives `WATCH_ONLY`; the candidate cannot execute.
- A flip BUY target must remain above the failed SELL envelope; a flip SELL target must remain below the failed BUY envelope.

## Future-change rule

When zoning or execution-handoff code is modified, compare the proposed behavior against this contract first. Do not restore old behavior that forces two zones, publishes BUY above price, publishes SELL below price, automatically chooses a remote HTF zone over a much nearer equally-valid intraday institutional location, grants execution authority to a Level-2 reserve while Level 1 remains valid, treats broad-envelope contact as primary M1 handoff, or allows a target on the wrong side of the actual candidate entry.

# Trade Zone — Developer-Ready Zone Geometry Specification V659

Status: IMPLEMENTATION CONTRACT  
Scope: DEMO / PAPER ONLY  
Authoritative parent: `ZONE_FORMATION_PROMPT_2026_09_14_V659`

## 1. Objective

Tighten XAUUSD institutional zones so the chart shows precise tactical locations while preserving the structural liquidity the setup is designed to raid. Zone creation remains source-driven; liquidity never manufactures a zone.

## 2. Non-negotiable invariants

1. A zone requires an H4/H1 institutional source produced by displacement/BOS or liquidity sweep + rejection + decisive follow-through.
2. Equal highs/equal lows are liquidity objects only. They may qualify as BSL/SSL, inducement or objectives, but are never promoted into standalone zones.
3. SELL requires structural BSL inside the final envelope.
4. BUY requires structural SSL inside the final envelope.
5. Minimum distal sweep reserve is 50 XAU pips inside the same final envelope.
6. SELL reserve is above attached BSL; BUY reserve is below attached SSL.
7. If source + liquidity + sweep reserve cannot fit within the source-timeframe maximum envelope, reject the candidate. Never widen the maximum to save it.
8. M15 closed-body acceptance beyond the outer envelope invalidates. Wick-only raids do not.
9. M1 cannot create, resize, move or re-rank HTF zones.
10. Publish at most one Primary and one Reserve per side. Missing levels are not forced.
11. Reserve has zero M1 execution authority while its Primary remains valid.

## 3. XAU unit convention

`1 XAU pip = 10 broker points`.

For the current Deriv convention with `point = 0.01`, one XAU pip is `0.10` price units.

All internal geometry may remain in broker points, but API/dashboard labels must expose pips.

## 4. Geometry matrix

| `source_tf` | Core minimum | Core maximum | Envelope minimum | Envelope maximum |
| --- | ---: | ---: | ---: | ---: |
| `H1` | 60 pips | 100 pips | 140 pips | 220 pips |
| `H4` | 80 pips | 140 pips | 180 pips | 260 pips |
| `H4>H1` | 60 pips | 100 pips | 180 pips | 260 pips |

`H4>H1` means H1 refines the tactical core, while H4 retains structural authority over the outer envelope.

## 5. Core normalization algorithm

Inputs: candidate source body, direction, `source_tf`, broker `point`.

```text
contract = geometry[source_tf]
min_price = contract.core_min_pips * 10 * point
max_price = contract.core_max_pips * 10 * point
body_width = abs(candidate.core_high - candidate.core_low)
width = clamp(body_width, min_price, max_price)

if SELL:
    core_high = candidate.core_high
    core_low  = core_high - width
else BUY:
    core_low  = candidate.core_low
    core_high = core_low + width
```

Do not center-shift the core away from the source to chase liquidity.

## 6. Liquidity attachment algorithm

Required type:

```text
SELL -> BSL
BUY  -> SSL
```

Eligible structural liquidity source TFs: D1, H4, H1.

For each eligible level:

```text
sweep_price = 50 pips * 10 points/pip * point

SELL:
    liquidity_price >= core_low
    hard_high = max(core_high, liquidity_price + sweep_price)
    hard_high - core_low <= envelope_max_price

BUY:
    liquidity_price <= core_high
    hard_low = min(core_low, liquidity_price - sweep_price)
    core_high - hard_low <= envelope_max_price
```

Selection order after qualification:

1. liquidity already inside the original source candle/range;
2. stronger structural TF (`D1`, then `H4`, then `H1`);
3. smaller distance from the tactical core edge;
4. smaller current-price distance.

No eligible liquidity -> reject `MISSING_BSL_IN_MARKED_ZONE` or `MISSING_SSL_IN_MARKED_ZONE`.

## 7. Envelope construction

Envelope must contain all three objects:

- institutional source;
- attached structural BSL/SSL;
- 50-pip distal sweep reserve.

Then normalize envelope width to the source-timeframe min/max range without violating those three objects.

Any impossible fit -> reject `ZONE_GEOMETRY_CANNOT_FIT_SWEEP`.

## 8. Equal-high / equal-low handling

Required behavior:

```text
EQH/EQL detected
    -> may create/update liquidity object
    -> may be attached as structural BSL/SSL when normal liquidity rules qualify it
    -> may contribute to sweep/objective context
    -> MUST NOT instantiate PromptSource
    -> MUST NOT instantiate PromptCandidate
    -> MUST NOT bypass displacement/source validation
```

This explicitly prevents liquidity pools from being promoted into trading zones merely because they are visually equal.

## 9. Primary and Reserve publication

Per direction:

```text
Primary = highest-ranked valid zone on correct side of current price
Reserve = best distinct A/A+ valid source beyond Primary invalidation side
```

SELL Reserve must be completely above Primary envelope.  
BUY Reserve must be completely below Primary envelope.

Reserve properties:

```text
state = RESERVE
execution_authority = false
m1_handoff = false while Primary valid
fresh_requalification_required = true after Primary invalidation
```

Maximum public map: 4 records total.

```text
SELL Primary
SELL Reserve
BUY Primary
BUY Reserve
```

Do not manufacture missing records.

## 10. Alert-side rule

```text
BUY valid for today's alert map when:
    envelope is below current price OR current price is interacting with it

SELL valid for today's alert map when:
    envelope is above current price OR current price is interacting with it
```

Wrong-side candidates are rejected, not automatically flipped.

## 11. Rendering contract

Rendering is visual only and cannot affect zone qualification or execution authority.

Primary:

- soft/muted filled envelope;
- stronger core;
- solid border;
- label: `DIRECTION PRIMARY | GRADE | STATE | Tn`.

Reserve:

- visually subordinate;
- dotted envelope / dashed core;
- preferably outline-only or materially softer than Primary;
- label: `DIRECTION RESERVE | GRADE | RESERVE | Tn`.

Active thesis may retain gold label emphasis.

## 12. API/dashboard fields

`execution_policy.public_zone_map` must expose:

```json
{
  "prompt_contract_ref": "ZONE_FORMATION_PROMPT_2026_09_14_V659",
  "width_display_unit": "pips",
  "xau_points_per_pip": 10,
  "geometry_by_source_tf": {
    "H1": {"core_width_pips": [60, 100], "envelope_width_pips": [140, 220]},
    "H4": {"core_width_pips": [80, 140], "envelope_width_pips": [180, 260]},
    "H4>H1": {"core_width_pips": [60, 100], "envelope_width_pips": [180, 260]}
  },
  "min_sweep_room_pips": 50,
  "equal_high_low_are_liquidity_objects_only": true,
  "max_primary_per_side": 1,
  "max_reserve_per_side": 1,
  "reserve_zone_is_not_forced": true
}
```

Each published side record also exposes its actual core/envelope widths plus its applicable contract.

## 13. Acceptance tests

The release is acceptable only if all of the following hold:

1. H1 candidate with a 30-pip source body normalizes core to 60 pips.
2. H1 candidate with a 130-pip body caps core at 100 pips.
3. H4 candidate with a 50-pip body normalizes core to 80 pips.
4. H4 candidate with a 180-pip body caps core at 140 pips.
5. H4>H1 candidate uses 60–100 core and 180–260 envelope.
6. SELL BSL with <50 pips available above it is rejected.
7. BUY SSL with <50 pips available below it is rejected.
8. Liquidity outside the original source may be included only when the final envelope remains within the relevant max and still contains the source.
9. EQH/EQL alone cannot produce a `PromptCandidate`.
10. Wrong-side BUY/SELL candidates remain rejected.
11. Reserve cannot become executable while Primary remains valid.
12. MT5 render feed returns at most four records.
13. Reserve rendering is visually lighter/subordinate to Primary.
14. M1 execution handoff still requires tactical core proximity; broad envelope contact alone is insufficient.
15. No code path introduced by V659 sends an order or changes risk. DEMO/PAPER safety remains intact.

## 14. Versioning/deployment

Cloud release: bump cloud code version.  
MT5 visual package: publish a new stable release because the renderer support file changes and the DataBridge must be recompiled against it.  
Sequence EA logic/version need not change because this specification changes deterministic cloud zoning and chart presentation, not Sequence execution logic.

Deployment order:

1. merge cloud + renderer source changes;
2. allow Railway/main deployment;
3. verify `/health` reports the new cloud version;
4. pin stable MT5 manifest `ref` to the source commit;
5. update support/DataBridge SHA256 values;
6. publish stable release;
7. updater installs support files, recompiles DataBridge, and safe-reloads MT5 only when runtime reports restart-safe;
8. verify dashboard desired/installed/running version truth and chart rendering.

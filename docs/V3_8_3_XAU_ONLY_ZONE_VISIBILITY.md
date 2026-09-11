# v3.8.3 — XAU-only Zones and Zone Visibility

DXY D1/H4/H1 is analysis-only. It supplies intermarket bias/implication and may qualify or downgrade an XAU zone, but it must never create a DXY execution POI, DXY trading zone, or DXY target.

All cloud view/execution zones carry `instrument=XAUUSD` by default and the validator rejects any non-XAU/GOLD zone. `/mt5/plan` serializes XAU/GOLD zones only.

Sequence EA v2.11 improves visibility: the nearest published zone is included in the M1 chart price scale by default and a text guide shows direction, range, distance, and whether price is in-zone. Existing zone rectangles are still drawn even when the current EA mode is NO_TRADE because of a news blackout; they are styled as WATCH while execution is locked.

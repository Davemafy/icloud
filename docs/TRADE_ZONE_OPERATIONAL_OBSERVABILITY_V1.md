# Trade Zone Cloud — operational clarity v1 (paper-only candidate)

This change is staged on a feature branch, **not deployed to Railway**. It does not modify `mt5/stable/`, `/mt5/plan`, the Sequence EA 3.78, strategy risk, zone construction, owner state, or execution gates. Cloud version stays 6.5.143 until a separately approved release.

## Read-only dashboard improvement
The `/dashboard/operational-clarity` route provides:
- Frozen thesis-ownership identity and lifecycle (historical **not fresh-entry permission**).
- Current HTF-zone reacquisition, macro handoff, fresh M1 location and Sequence gate stage/reason.
- First **evidenced** prerequisite holding the entry. If every prerequisite passes, it still says **AWAIT_SEQUENCE_ORDER_GATE**; it does not authorize execution.
- Institutional journal records and performance shown distinctly from standalone Session Sniper.
- Session Sniper performance **NOT CONNECTED** until authenticated independent VPS journal ingestion is implemented.
- Combined account-wide risk **NOT VERIFIED** and enforcement flag **false** until a shared MT5 guard and position reconciliation exist.

The dashboard refreshes the read-only panel every 10 seconds; failures display unavailable rather than fabricated values. Python tests prove that owner matches are not entry permission and no zero Session Sniper P/L is invented.

## Required follow-on safety release
A shared risk checker cannot protect an account if only one of two independent EAs obeys it. Before any `enforcement_active=true` result:
1. Agree combined account risk budget and handling of manual/external positions, zero/missing SL, partial fills, and hedging.
2. Implement atomic account-wide MT5 pre-order coordination with unique strategy/magic IDs and position/order snapshots. Check both EAs at the final order gate; this necessarily requires **separate reviewed releases** for Sequence and Session Sniper.
3. Continue managing open positions locally during cloud loss and safely fail-closed on missing exposure data for *new* orders.
4. Test parallel same-symbol orders, partial 70/30 splits, restart recovery, and MT5 rejection scenarios on DEMO.
5. Add authenticated Session Sniper CSV/event ingestion with idempotent event IDs; reconcile journal totals to actual broker history.

The present candidate intentionally does **not** claim that such an account-wide guard is installed. No manual VPS action is required for these cloud-only candidate files.

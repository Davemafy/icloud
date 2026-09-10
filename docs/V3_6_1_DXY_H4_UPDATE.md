# v3.6.1 DXY H4 update

DXY H4 is now part of the required historical-context protocol.

- FULL_HISTORY: DXY D1=280, H4=600, H1=600 by default.
- LIVE_UPDATE: DXY D1/H4/H1 each include the recent `LiveBarsPerTF` window.
- ATR(14) is included for DXY H4 through the existing timeframe serializer.
- Cloud history readiness requires DXY H4 for protocol-v3 history.
- AI receives DXY D1/H4/H1 and returns a DXY H4 structural bias.
- Deterministic DXY implication is conservative: H4 and H1 must agree before SUPPORTS/CONFLICTS is asserted.
- Dashboard historical-context card shows DXY D1/H4/H1 counts.

Compile and use `mt5/InstitutionalSMC_DataBridge_v1_21_HistorySync_DXYH4.mq5`.

# v3.7 Intraday/Scalp Zone Engine — superseded

This document describes the previous v3.7 M15-heavy zone-generation experiment and is retained only as version history.

**Do not use it as the current execution contract.** v3.8 replaces that architecture with:

`H4/H1 PRIMARY INSTITUTIONAL ZONE -> M15 ONE-TIME ZONE QUALIFICATION -> ZONE PUBLISHED -> M1 EXECUTION`

Current rules are in `V3_8_H4H1_PRIMARY_M15_QUALIFICATION.md` and `SMC_FRAMEWORK_V3_FULL.md`.

In v3.8:
- standalone M15 execution zones are disabled;
- H4/H1 supply-demand/POI structure creates the candidate zone;
- M15 can only qualify that parent zone during analysis;
- M15 has no live veto or delay after publication;
- M1 remains the sole execution authority.

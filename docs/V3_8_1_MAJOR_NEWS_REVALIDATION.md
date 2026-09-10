# v3.8.1 Major-News Revalidation

For every high-impact USD news timestamp, simultaneous releases are grouped into one repricing cluster.

- **T-10 minutes:** MT5 Data Bridge sends `FULL_HISTORY` (`PRE_NEWS:*`). The cloud reruns the H4/H1 institutional zone analysis with M15 used only for one-time zone qualification. New M1 entries are blacked out from this point.
- **Release:** no new entry is allowed during the blackout. Existing demo positions continue the deterministic structural SL, break-even, and dynamic trailing logic; the EA never loosens a stop because of news.
- **T+10 minutes:** MT5 sends a fresh `FULL_HISTORY` (`POST_NEWS:*`) after repricing. The cloud reruns the zone analysis, retiring invalidated zones and publishing the valid replacement map. M1 execution may resume only from the new approved plan.

The pre-news analysis does not add an M15 execution wait. M15 use ends when the H4/H1-derived zone is qualified and published; M1 remains the sole execution timeframe.

Default settings:

```text
NEWS_PRE_ANALYSIS_MINUTES=10
NEWS_POST_ANALYSIS_MINUTES=10
NEWS_PRE_BLACKOUT_MINUTES=10
NEWS_POST_COOLDOWN_MINUTES=10
PRE_NEWS_CATCHUP_MINUTES=9
POST_NEWS_CATCHUP_MINUTES=30
```

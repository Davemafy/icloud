#property strict
#property version   "3.24"
#property description "DEMO/PAPER shadow ML observer for Trade Zone V6.4. Observation only; never places, modifies, or closes trades."

#define Evaluate ML24_Core_Evaluate_Disabled
#define OnInit ML24_Core_OnInit_Disabled
#define OnDeinit ML24_Core_OnDeinit_Disabled
#define OnTimer ML24_Core_OnTimer_Disabled
#define OnTick ML24_Core_OnTick_Disabled
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#undef Evaluate
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick

#define ML24_VERSION "3.24"

input bool EnableMLObservation=true;
input bool ObserveRejectedCandidates=true;
input int RejectedSampleEveryBars=1;
input int ObservationLookbackBars=120;
input double ObservationZoneDistanceATR=1.50;
input int ObserverPollSeconds=15;
input int ObserverHttpTimeoutMs=2500;
input bool EnableAlternativePrimary=true;
input bool EnableMomentumPullbackModel=true;
input bool EnableVWAPProxyModel=true;
input bool EnableOpeningRangeRetestModel=true;
input double MomentumRetraceMin=0.30;
input double MomentumRetraceMax=0.60;
input double VWAPBandATR=0.15;
input int VWAPLookbackBars=60;
input int OpeningRangeMinutes=30;
input int ORBMaxMinutesAfterOpen=240;
input double ORBRetestBandATR=0.12;
input double ORBMinBreakATR=0.55;

// Companion observer: attach to a SECOND XAUUSD M1 chart while v3.23 stays
// attached as the execution EA. The observer has zero execution authority.
datetime ml24_last_bar=0,ml24_last_heartbeat=0,ml24_last_plan_poll=0;
int ml24_reject_cursor=0,ml24_packets_sent=0,ml24_post_errors=0;
string ml24_cloud_regime="UNKNOWN",ml24_live_block_reason="";
bool ml24_live_block=false,ml24_profile_ready=false;
bool ml24_allow_ict=false,ml24_allow_reentry=false,ml24_allow_momentum=false,ml24_allow_vwap=false,ml24_allow_orb=false,ml24_allow_flip=false;

#include "ML24_CoreHelpers.mqh"
#include "ML24_ORBAndTelemetry.mqh"
#include "ML24_Observe.mqh"
#include "ML24_Runtime.mqh"

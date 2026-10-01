#property strict
#property version   "3.62"
#property description "DEMO/PAPER XAU comprehensive M1 entry engine repair: campaign persistence, reconstruction, continuation and breakout."

// Research wrapper around the validated v3.21 execution core.
// DEMO/PAPER ONLY. Real accounts remain hard-blocked.
// v3.50 implements the two user-defined primary execution models inside a valid
// premium/discount institutional zone.
//
// MODEL 1: M1 liquidity sweep -> M1 MICRO MSS -> fresh M1 OB/FVG from the MSS leg
// -> pullback into that OB/FVG -> CLOSED M1 candle in thesis direction -> entry.
//
// MODEL 2: closed directional M1 real-body engulfing pattern formed at/in the valid
// institutional zone -> entry.
//
// Both models may re-arm for R1/R2 while the thesis remains valid and risk budget
// remains. Existing positions must be flat or protected before another sniper cycle.
// M15 validates zone health/invalidation only. No M5/M15 MSS, OTE, ATR displacement,
// dealing-range or fixed-dollar runway gate is required for these primary sniper cycles.
// Initial SL for BOTH models, including their R1/R2 cycles, remains beyond the FULL
// institutional zone with the existing buffer. Actual-entry minimum RR still applies.
//
// v3.62 comprehensive entry-engine repair:
// - stable campaign state across analysis refreshes;
// - pre-handoff Model-1 event reconstruction;
// - original-zone reacquisition + displacement OB/FVG continuation;
// - institutional breakout -> acceptance -> retest;
// - closed M1 micro structure shift is mandatory for every entry family;
// - trade-management behavior remains unchanged.
#define Evaluate TZ27_StrictBaseEvaluate
#define OnInit TZ27_SeqCore_OnInit
#define OnDeinit TZ27_SeqCore_OnDeinit
#define OnTimer TZ27_SeqCore_OnTimer
#define OnTick TZ27_SeqCore_OnTick
#define ManagePositions TZ21_BaseManagePositions
#define BuildFlip TZ21_BaseBuildFlip
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#include <TradeZoneCore\SniperContractParityV1.mqh>
#undef Evaluate
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick
#undef ManagePositions
#undef BuildFlip

#define TZ_SEQUENCE_VERSION "3.62"

input bool PaperResearchMode=true;
input double ResearchMaxSpreadPoints=50.0;
input bool ResearchUseDailyLossGuard=false;
input int ResearchRecentZoneBars=240;
input bool ResearchAllowContinuationRescue=false;
input double ResearchLiquidityReversalRiskMultiplier=0.50;
input double ResearchZoneSweepRiskMultiplier=1.00;
input bool ResearchAllowEscapePullback=false;
input double ResearchEscapeRiskMultiplier=0.50;
input int ResearchEscapeLookbackBars=90;
input double ResearchEscapeDisplacementATR=0.70;
input double ResearchEscapeRetraceMin=0.25;
input double ResearchEscapeRetraceMax=0.55;
input double ResearchEscapeMaxChaseATR=0.12;
input int ResearchFlipCandidateMaxMinutes=120;

// v3.60 is a consolidated primary-entry engine, not another incremental gate patch.
// One scanner owns BOTH execution and diagnostics, so dashboard stage and order logic
// cannot disagree. The institutional zone grants location authority; the M1 PD array
// is allowed to form immediately outside the HTF envelope after the sweep/MSS leg.
//
// MODEL 1: zone interaction -> M1 micro-liquidity sweep -> nearest M1 micro MSS ->
// fresh causal OB/FVG -> bounded pullback window -> latest closed M1 directional candle.
// MODEL 2: directional M1 real-body engulfing with very recent zone interaction.
//
// Removed primary over-constraints: 5-bar liquidity pivot, sweep-candle close-back,
// HTF-zone overlap requirement for the M1 OB/FVG, exact r[2] pullback timing, and the
// redundant requirement that the final directional candle re-break/hold the MSS level.
input int SimpleMicroMSSLookbackBars=18;
input int SniperPullbackMaxBars=12;
input int SniperConfirmMaxBars=3;
input int SniperEngulfContextBars=6;
input bool SniperAllowSameBarRetestConfirm=true;
input int SniperContactLeadBars=24;

input bool EnableInstitutionalBreakoutModel=true;
input double BreakoutRiskMultiplier=0.75;
input double ContinuationReentryRiskMultiplier=0.75;
input int BreakoutLookbackBars=120;
input int BreakoutBalanceBars=12;
input double BreakoutCompressionMaxATR=2.50;
input double BreakoutMinBreakATR=0.50;
input double BreakoutBoundaryBandATR=0.12;
input int BreakoutRetestMaxBars=18;
input int BreakoutAcceptanceBars=3;
input double BreakoutMaxChaseATR=0.75;

// v3.47 strategic multi-model opportunity layer.
// These are supplementary execution patterns only. They never create HTF authority,
// never bypass recent institutional location, and never bypass the universal closed-M1
// value reaction, full-zone first-entry stop, target, RR, parity, spread or risk gates.
input bool EnableAlternativePrimary=false;
input bool EnableMomentumPullbackModel=false;
input bool EnableVWAPProxyModel=false;
input bool EnableOpeningRangeRetestModel=false;
input double AlternativeModelRiskMultiplier=0.75;
input int AlternativeZoneInteractionBars=120;
input double MomentumRetraceMin=0.30;
input double MomentumRetraceMax=0.60;
input double MomentumMinDisplacementATR=0.70;
input int MomentumLookbackBars=48;
input double VWAPBandATR=0.15;
input int VWAPLookbackBars=60;
input double VWAPMinDisplacementATR=0.60;
input int OpeningRangeMinutes=30;
input int ORBMaxMinutesAfterOpen=240;
input double ORBRetestBandATR=0.12;
input double ORBMinBreakATR=0.60;

// v3.35 re-entry hardening: value is necessary but no longer sufficient.
// A re-entry must be based on a recent directional break, an un-invalidated PD array,
// then a CLOSED M1 same-direction rejection from the OTE/PD overlap before market entry.
input bool ReentryRequireClosedM1ValueReaction=true;
input int ReentrySignalMaxAgeBars=20;
input int ReentryValueReactionLookbackBars=6;
input double ReentryReactionMinBodyATR=0.20;
input double ReentryReactionMaxChaseATR=0.25;

// v3.36 hardens INITIAL post-handoff entries (L0/S0), not only R1/R2.
// A liquidity/zone-sweep handoff is observation authority, never permission to market-enter
// merely because price touched an OTE/PD overlap.
input bool PostHandoffRequireClosedM1ValueReaction=true;
input int PostHandoffSignalMaxAgeBars=12;
input int PostHandoffValueReactionLookbackBars=6;
input double PostHandoffReactionMinBodyATR=0.25;
input double PostHandoffReactionMaxChaseATR=0.15;

// v3.40 preserves the v3.39 universal professional confirmation floor and adds
// a failed-zone breaker path for accepted-zone flips. The old invalidated zone
// may act as the PD array only after accepted M15 invalidation, opposite-side
// retest, M1 structure break/displacement, and a closed directional reaction.
// No instant reverse and no chase.
//
// v3.39 universal professional confirmation floor.
// Every entry model must see a CLOSED M1 rejection from its OTE/PD value overlap,
// in thesis direction, with a micro-structure break before an order can be sent.
// Model-specific settings may be stricter, never looser than this floor.
input int ProfessionalEntryValueReactionLookbackBars=6;
input double ProfessionalEntryReactionMinBodyATR=0.25;
input double ProfessionalEntryReactionMaxChaseATR=0.15;

// Context x grade research risk. Quality grade and D1 alignment are independent
// axes. B+ remains a reduced-risk execution grade subject to every normal gate.
input double ResearchValidationInitialCapital=10000.0;
input double ResearchRiskPctTrendAPlus=1.00;
input double ResearchRiskPctTrendA=0.75;
input double ResearchRiskPctCountertrendAPlus=0.50;
input double ResearchRiskPctCountertrendA=0.25;
input double ResearchRiskPctBPlus=0.25;

datetime g_tzLastStateWrite=0,g_tzLastHeartbeat=0,g_tzLastAuthorityPoll=0,g_tzGateTs=0;
string g_tzLoadedStateKey="";
string g_tzLastModel="";
string g_tzExecutionAuthority="NONE";
string g_tzLRDirection="";
string g_tzLRLabel="";
string g_tzGateStage="BOOT";
string g_tzGateReason="INITIALIZING";
string g_tzCandidateModel="NONE";
string g_tzTracePdType="";
double g_tzTraceLiquidityLevel=0.0,g_tzTraceSweepPrice=0.0,g_tzTraceMssLevel=0.0,g_tzTracePdLow=0.0,g_tzTracePdHigh=0.0;
datetime g_tzTraceContactTs=0,g_tzTraceSweepTs=0,g_tzTraceMssBreakTs=0,g_tzTracePdTs=0,g_tzTracePullbackTs=0,g_tzTraceConfirmTs=0;
bool g_tzTraceReconstructedPreHandoff=false;
double g_tzLRPrice=0.0,g_tzLRRiskMultiplier=0.50;
datetime g_tzExecutionHandoffTs=0,g_tzLastCloudSync=0;
string g_tzRuntimeThesisKey="";
bool g_tzCloudLiveBlocked=false;
string g_tzCloudLiveBlockReason="";

double g_tzRequiredRunway=0.0,g_tzRunwayTarget=0.0,g_tzRunwayEntryLimit=0.0,g_tzLastActualRunway=0.0;
string g_tzRunwayGateMode="UNSET";
bool g_tzEntrySpecificRunwayRuntimeReady=false;

string g_tzCloudRegime="UNKNOWN",g_tzLocalRegime="UNKNOWN";
bool g_tzAllowMomentum=false,g_tzAllowVWAP=false,g_tzAllowORB=false,g_tzAllowBreakout=false;

string g_tzRiskModel="CONTEXT_GRADE_MATRIX_10000_V2";
string g_tzRiskEpoch="CONTEXT_GRADE_10000_V2";
double g_tzValidationInitialCapital=10000.0;
string g_tzRiskContext="TREND";
int g_tzQualifiedMitigations=0;
string g_tzSniperContractFingerprint="";
string g_tzExpectedSniperContractFingerprint="";
string g_tzSniperContractAuthority="NONE";
string g_tzSniperParityStatus="UNVERIFIED";
bool g_tzSniperContractVerified=false;
double g_tzOriginalRiskPct=0.0,g_tzFlipRiskPct=0.0,g_tzAcceptedFlipRiskPct=0.0;
double g_tzGradeRiskPct=0.0; // legacy telemetry alias = original base thesis risk
double g_tzLastRiskBase=0.0,g_tzLastRiskMoney=0.0,g_tzLastIntendedLots=0.0,g_tzLastActualLots=0.0;
bool g_tzLastSplitPartial=false;

void TZ42_RefreshSniperParityFromPlan(string text)
{
   string parityGrade=KV(text,"current_grade");
   if(parityGrade!="")g_plan.grade=parityGrade;
   string qmit=KV(text,"qualified_mitigations");
   if(qmit=="")qmit=KV(text,"touch_count");
   g_tzQualifiedMitigations=(int)StringToInteger(qmit);
   g_tzSniperContractAuthority=KV(text,"execution_authority");
   if(g_tzSniperContractAuthority=="")g_tzSniperContractAuthority="NONE";
   g_tzExpectedSniperContractFingerprint=KV(text,"contract_fingerprint");
   g_tzSniperContractFingerprint=TZ_SniperContractFingerprint(
      g_plan.analysis_id,g_plan.zone_id,g_plan.original_direction,g_plan.grade,
      g_tzQualifiedMitigations,g_tzRiskContext,g_tzOriginalRiskPct,g_tzSniperContractAuthority);
   g_tzSniperContractVerified=(
      g_tzExpectedSniperContractFingerprint!="" &&
      g_tzExpectedSniperContractFingerprint==g_tzSniperContractFingerprint
   );
   g_tzSniperParityStatus=(
      g_tzExpectedSniperContractFingerprint==""?"UNVERIFIED":
      g_tzSniperContractVerified?"MATCH":"MISMATCH"
   );
}

bool TZ42_NewEntryParitySafe()
{
   if(IsTester()||OperatingMode!=LIVE_CLOUD)return true;
   if(g_tzExpectedSniperContractFingerprint=="")
   {
      TZ_SetGate("PARITY","SNIPER_CONTRACT_UNVERIFIED");
      return false;
   }
   if(!g_tzSniperContractVerified)
   {
      TZ_SetGate("PARITY","SNIPER_CONTRACT_MISMATCH");
      return false;
   }
   return true;
}

bool TZ42_RevalidateParityBeforeOrder()
{
   if(IsTester()||OperatingMode!=LIVE_CLOUD)return true;
   string text;
   if(!HttpGet("/mt5/plan",text))
   {
      TZ_SetGate("PARITY","SNIPER_CONTRACT_REVALIDATION_UNAVAILABLE");
      return false;
   }
   if(KV(text,"live_block")=="1")
   {
      TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"+KV(text,"live_block_reason"));
      return false;
   }
   string fresh=KV(text,"contract_fingerprint");
   if(fresh=="")
   {
      TZ_SetGate("PARITY","SNIPER_CONTRACT_UNVERIFIED");
      return false;
   }
   if(!g_tzSniperContractVerified||fresh!=g_tzExpectedSniperContractFingerprint)
   {
      TZ_SetGate("PARITY","SNIPER_CONTRACT_MISMATCH");
      return false;
   }
   return true;
}

bool TZ40_FailedZoneBreakerPD(
   bool buy,double oteLo,double oteHi,
   double &pdLo,double &pdHi,double &eLo,double &eHi,string &pdType)
{
   double x1=0.0,x2=0.0;
   double coreLo=MathMin(g_plan.core_low,g_plan.core_high);
   double coreHi=MathMax(g_plan.core_low,g_plan.core_high);
   if(coreLo>0&&coreHi>coreLo&&Intersect(coreLo,coreHi,oteLo,oteHi,x1,x2))
   {
      pdLo=coreLo;pdHi=coreHi;eLo=x1;eHi=x2;pdType="BREAKER-CORE";
      return true;
   }

   double zoneLo=MathMin(g_plan.zone_low,g_plan.zone_high);
   double zoneHi=MathMax(g_plan.zone_low,g_plan.zone_high);
   if(zoneLo<=0||zoneHi<=zoneLo)return false;

   // Use only the proximal half first encountered on an opposite-side retest:
   // failed BUY -> SELL breaker uses the lower half; failed SELL -> BUY uses upper half.
   double mid=(zoneLo+zoneHi)*0.5;
   double breakerLo=(buy?mid:zoneLo);
   double breakerHi=(buy?zoneHi:mid);
   if(!Intersect(breakerLo,breakerHi,oteLo,oteHi,x1,x2))return false;

   pdLo=breakerLo;pdHi=breakerHi;eLo=x1;eHi=x2;pdType="BREAKER-PROXIMAL";
   return true;
}

// v3.40 accepted-zone flip builder.
// A failed zone is itself a legitimate breaker PD array after accepted invalidation.
// Fresh FVG/OB remains preferred; breaker fallback prevents a valid retest + MSS/
// displacement from being discarded solely because no second post-break FVG/OB
// happens to overlap OTE.
bool BuildFlip(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;
   if(!g_flipCandidate||g_flipAcceptedAt==0)return false;

   int ret=-1;
   int mx=MathMin(FlipRetestMaxBars,ArraySize(r)-8);
   for(int i=3;i<=mx;i++)
   {
      if(r[i].time<g_flipAcceptedAt)continue;
      if(!TouchZone(r[i]))continue;
      bool fromFlipSide=buy
         ?(r[i].open>=g_plan.zone_high||r[i].high>=g_plan.zone_high)
         :(r[i].open<=g_plan.zone_low||r[i].low<=g_plan.zone_low);
      if(fromFlipSide){ret=i;break;}
   }
   if(RequireFlipRetest&&ret<3)return false;
   if(ret<3)ret=mx;

   int bp;double bos;
   if(!OlderPivot(r,ret+2,SwingLookback,buy,bp,bos))return false;

   int br=-1;
   for(int j=ret-1;j>=3;j--)
   {
      bool broke=buy?(r[j].close>bos):(r[j].close<bos);
      if(broke&&StrongDisp(r,j,a,FlipBreakDisplacementATR,buy)){br=j;break;}
   }
   if(br<3)return false;

   double anchor=buy?r[ret].low:r[ret].high;
   double imp=buy?r[br].high:r[br].low;
   for(int j=br;j>=1;j--)
   {
      if(buy)imp=MathMax(imp,r[j].high);
      else imp=MathMin(imp,r[j].low);
   }
   if(MathAbs(imp-anchor)<a)return false;

   double ol,oh;OTE(buy,anchor,imp,ol,oh);
   int pi=-1;double pl=0.0,ph=0.0,el=0.0,eh=0.0;string pt="";
   if(!FindFreshPD(r,buy,ret,br,ol,oh,pi,pl,ph,pt,el,eh))
   {
      if(!TZ40_FailedZoneBreakerPD(buy,ol,oh,pl,ph,el,eh,pt))return false;
      pi=ret;
   }

   sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=true;
   sig.anchor_idx=ret;sig.break_idx=br;sig.pd_idx=pi;
   sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=imp;
   sig.ote_low=ol;sig.ote_high=oh;sig.pd_low=pl;sig.pd_high=ph;
   sig.entry_low=el;sig.entry_high=eh;
   sig.pd_type=(StringFind(pt,"BREAKER-")==0?"FLIP-"+pt:"FLIP-"+pt);
   return true;
}

string TZ38_DefaultRiskContext(string setupType)
{
   return setupType=="REVERSAL"?"COUNTERTREND":"TREND";
}

string TZ38_OppositeRiskContext(string context)
{
   return context=="COUNTERTREND"?"TREND":"COUNTERTREND";
}

double TZ38_DefaultContextRiskPct(string grade,string context)
{
   if(grade=="A+")
      return context=="COUNTERTREND"?ResearchRiskPctCountertrendAPlus:ResearchRiskPctTrendAPlus;
   if(grade=="A")
      return context=="COUNTERTREND"?ResearchRiskPctCountertrendA:ResearchRiskPctTrendA;
   if(grade=="B+")return ResearchRiskPctBPlus;
   return 0.0;
}

void TZ38_LoadRiskContract(string text,string grade,string setupType)
{
   string model=KV(text,"risk_model");if(model!="")g_tzRiskModel=model;
   string epoch=KV(text,"risk_epoch");if(epoch!="")g_tzRiskEpoch=epoch;
   double cap=StringToDouble(KV(text,"validation_initial_capital"));
   if(cap>0)g_tzValidationInitialCapital=cap;
   else if(g_tzValidationInitialCapital<=0)g_tzValidationInitialCapital=ResearchValidationInitialCapital;

   string context=KV(text,"risk_context");
   if(context!="TREND"&&context!="COUNTERTREND")context=TZ38_DefaultRiskContext(setupType);
   g_tzRiskContext=context;

   double original=StringToDouble(KV(text,"original_risk_pct"));
   if(original<=0)original=StringToDouble(KV(text,"grade_risk_pct")); // rolling-upgrade compatibility
   if(original<=0)original=TZ38_DefaultContextRiskPct(grade,context);

   double flipPct=StringToDouble(KV(text,"flip_risk_pct"));
   if(flipPct<=0)flipPct=TZ38_DefaultContextRiskPct(grade,TZ38_OppositeRiskContext(context));

   g_tzOriginalRiskPct=original;
   g_tzFlipRiskPct=flipPct;
   g_tzGradeRiskPct=original;
}

double TZ37_RiskBase()
{
   double cap=(g_tzValidationInitialCapital>0?g_tzValidationInitialCapital:ResearchValidationInitialCapital);
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   if(cap<=0||bal<=0)return 0.0;
   return MathMin(cap,bal);
}

double TZ38_ThesisBudget(bool flip,string grade)
{
   if(grade!="A+"&&grade!="A"&&grade!="B+")return 0.0;
   double pct=0.0;
   if(flip)
   {
      pct=(g_tzAcceptedFlipRiskPct>0?g_tzAcceptedFlipRiskPct:g_tzFlipRiskPct);
      if(pct<=0)pct=TZ38_DefaultContextRiskPct(grade,TZ38_OppositeRiskContext(g_tzRiskContext));
   }
   else
   {
      pct=g_tzOriginalRiskPct;
      if(pct<=0)pct=TZ38_DefaultContextRiskPct(grade,g_tzRiskContext);
   }
   double base=TZ37_RiskBase();
   g_tzLastRiskBase=base;
   double x=base*pct/100.0;
   if(flip)x*=FlipRiskMultiplier;
   return x;
}

double TZ37_FloorVolume(double v)
{
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double mx=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double st=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(mn<=0||mx<=0||st<=0||v<=0)return 0.0;
   double out=MathFloor(MathMin(v,mx)/st+1e-9)*st;
   if(out+1e-9<mn)return 0.0;
   return NormalizeDouble(out,8);
}

double TZ37_LotsForRisk(bool buy,double entry,double sl,double money)
{
   if(money<=0||entry<=0||sl<=0||MathAbs(entry-sl)<=_Point)return 0.0;
   double perLot=0.0,profit=0.0;
   ENUM_ORDER_TYPE type=buy?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   if(OrderCalcProfit(type,_Symbol,1.0,entry,sl,profit))perLot=MathAbs(profit);
   if(perLot<=0)
   {
      double tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
      double ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tv<=0||ts<=0)return 0.0;
      perLot=(MathAbs(entry-sl)/ts)*tv;
   }
   if(perLot<=0)return 0.0;
   return TZ37_FloorVolume(money/perLot);
}

// v3.46 initial-stop hardening.
// The first entry belongs to the institutional zone that authorized the thesis.
// A micro PD-array/signal anchor may improve timing, but it must never tighten the
// first-entry SL back inside that institutional zone. For first entries only,
// SELL SL must be above the full zone_high plus a spread/ATR/broker buffer, and
// BUY SL must be below the full zone_low minus the same buffer. Re-entries retain
// their local structural stop because they occur only after thesis continuation.
double TZ46_ZoneStopBuffer(double m1Atr)
{
   double point=MathMax(_Point,1e-9);
   MqlTick tk;double spreadBuffer=0.0;
   if(SymbolInfoTick(_Symbol,tk))
      spreadBuffer=MathMax(0.0,tk.ask-tk.bid)*1.50;
   double atrBuffer=(m1Atr>0?m1Atr*SLBufferATR:0.0);
   long stopLevel=(long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double brokerBuffer=MathMax(point,(double)stopLevel*point);
   return MathMax(MathMax(point*5.0,spreadBuffer),MathMax(atrBuffer,brokerBuffer));
}

double TZ46_InitialZoneProtectedStop(
   bool buy,double microStop,double zoneLow,double zoneHigh,double m1Atr
)
{
   if(zoneLow<=0||zoneHigh<=0||zoneHigh<=zoneLow)return 0.0;
   double buffer=TZ46_ZoneStopBuffer(m1Atr);
   double zoneStop=buy?(zoneLow-buffer):(zoneHigh+buffer);
   double out=buy?MathMin(microStop,zoneStop):MathMax(microStop,zoneStop);
   return NormalizeDouble(out,_Digits);
}

// v3.49: skip planned objectives already behind the actual entry.
int TZ49_OpenDirectionalTargets(
   bool flip,bool buy,double entry,double &t1,double &t2,double &t3,double &run
)
{
   double r1,r2,r3,rr;int raw=Targets(flip,buy,r1,r2,r3,rr);
   t1=0.0;t2=0.0;t3=0.0;run=0.0;if(raw<=0)return 0;
   double xs[4]={r1,r2,r3,rr};
   double vals[4]={0.0,0.0,0.0,0.0};int n=0;
   double gap=MathMax(_Point*5.0,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
   for(int i=0;i<4;i++)
   {
      double x=xs[i];if(x<=0)continue;
      bool ahead=buy?(x>entry+gap):(x<entry-gap);
      if(ahead)vals[n++]=x;
   }
   for(int i=0;i<n;i++)
      for(int j=i+1;j<n;j++)
      {
         bool doSwap=buy?(vals[j]<vals[i]):(vals[j]>vals[i]);
         if(doSwap){double z=vals[i];vals[i]=vals[j];vals[j]=z;}
      }
   if(n>0)t1=vals[0];
   if(n>1)t2=vals[1];
   if(n>2)t3=vals[2];
   if(n>3)run=vals[3];
   return n;
}

bool TZ49_DeepestDirectionalTarget(bool flip,bool buy,double entry,double &target)
{
   double t1,t2,t3,run;int n=TZ49_OpenDirectionalTargets(flip,buy,entry,t1,t2,t3,run);
   if(n<=0){target=0.0;return false;}
   target=(run>0?run:(t3>0?t3:(t2>0?t2:t1)));
   return target>0;
}

bool TZ37_SendOrders(bool buy,double entry,double sl,double lots,bool flip,string tag,string pd)
{
   g_tzLastActualLots=0.0;g_tzLastSplitPartial=false;
   double total=TZ37_FloorVolume(lots);if(total<=0)return false;
   double t1,t2,t3,run;int nt=TZ49_OpenDirectionalTargets(flip,buy,entry,t1,t2,t3,run);if(nt<=0||t1<=0)return false;
   trade.SetExpertMagicNumber(MagicNumber);trade.SetDeviationInPoints(MaxSlippagePoints);

   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      string c="SMCV6 "+tag+" "+pd;
      bool sent=buy?trade.Buy(total,_Symbol,0,sl,t1,c):trade.Sell(total,_Symbol,0,sl,t1,c);
      if(sent)g_tzLastActualLots=total;
      return sent;
   }

   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double st=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(mn<=0||st<=0)return false;

   double l1=0.0,l2=0.0,lr=0.0;
   bool useT2=(t2>0);
   if(total+1e-9<2.0*mn)
   {
      l1=total;
   }
   else if(!useT2||total+1e-9<3.0*mn)
   {
      double s2=MathMax(1e-9,TP1VolumePct+RunnerVolumePct);
      l1=TZ37_FloorVolume(total*TP1VolumePct/s2);
      if(l1<mn)l1=mn;
      lr=TZ37_FloorVolume(total-l1);
      if(lr<mn){lr=mn;l1=TZ37_FloorVolume(total-lr);}
      if(l1<mn){l1=total;lr=0.0;}
   }
   else
   {
      double s3=TP1VolumePct+TP2VolumePct+RunnerVolumePct;if(s3<=0)s3=100.0;
      double rem=total-3.0*mn;
      double a1=MathFloor((rem*TP1VolumePct/s3)/st+1e-9)*st;
      double a2=MathFloor((rem*TP2VolumePct/s3)/st+1e-9)*st;
      double ar=MathFloor((rem-a1-a2)/st+1e-9)*st;
      l1=NormalizeDouble(mn+a1,8);
      l2=NormalizeDouble(mn+a2,8);
      lr=NormalizeDouble(mn+MathMax(0.0,ar),8);
      double left=MathFloor((total-l1-l2-lr)/st+1e-9)*st;
      if(left>0)lr=NormalizeDouble(lr+left,8);
   }

   bool any=false,allok=true;
   if(l1>=mn)
   {
      string c1="SMCV6 "+tag+" T1";
      bool sent1=buy?trade.Buy(l1,_Symbol,0,sl,t1,c1):trade.Sell(l1,_Symbol,0,sl,t1,c1);
      if(sent1){any=true;g_tzLastActualLots+=l1;}else allok=false;
   }
   if(l2>=mn&&t2>0)
   {
      string c2="SMCV6 "+tag+" T2";
      bool sent2=buy?trade.Buy(l2,_Symbol,0,sl,t2,c2):trade.Sell(l2,_Symbol,0,sl,t2,c2);
      if(sent2){any=true;g_tzLastActualLots+=l2;}else allok=false;
   }
   if(lr>=mn)
   {
      string cr="SMCV6 "+tag+" RUN";
      bool sentr=buy?trade.Buy(lr,_Symbol,0,sl,0,cr):trade.Sell(lr,_Symbol,0,sl,0,cr);
      if(sentr){any=true;g_tzLastActualLots+=lr;}else allok=false;
   }
   g_tzLastActualLots=NormalizeDouble(g_tzLastActualLots,8);
   g_tzLastSplitPartial=(any&&!allok);
   return any;
}

// v3.34 trade-management hardening.
// The validated base manager calculated R from abs(entry-current SL). Once BE moved
// current SL to entry that value became zero, so the old manager returned early and
// the runner could never graduate from BE into its M5 structural/ATR trail.
// Persist the ORIGINAL risk distance before any SL modification and always calculate
// BE / runner thresholds from that immutable basis.
string TZ34_RiskKey(ulong positionId)
{
   return StringFormat("TZ.RISK.%I64d.%I64d",(long)AccountInfoInteger(ACCOUNT_LOGIN),(long)positionId);
}

double TZ34_HistoryInitialRisk(ulong positionId,double openPrice)
{
   if(positionId==0||!HistorySelectByPosition(positionId))return 0.0;
   double found=0.0;
   for(int i=0;i<HistoryOrdersTotal();i++)
   {
      ulong order=HistoryOrderGetTicket(i);if(!order)continue;
      if(HistoryOrderGetString(order,ORDER_SYMBOL)!=_Symbol)continue;
      if((ulong)HistoryOrderGetInteger(order,ORDER_MAGIC)!=MagicNumber)continue;
      double osl=HistoryOrderGetDouble(order,ORDER_SL);
      double op=HistoryOrderGetDouble(order,ORDER_PRICE_OPEN);if(op<=0)op=openPrice;
      double d=MathAbs(op-osl);
      if(osl>0&&d>_Point){found=d;break;}
   }
   return found;
}

double TZ34_InitialRiskDistance(ulong ticket,double openPrice,double currentSL)
{
   ulong positionId=(ulong)PositionGetInteger(POSITION_IDENTIFIER);if(positionId==0)positionId=ticket;
   string key=TZ34_RiskKey(positionId);
   if(GlobalVariableCheck(key))
   {
      double saved=GlobalVariableGet(key);
      if(saved>_Point)return saved;
   }

   // Normal path: first management tick sees the untouched original SL.
   double d=(currentSL>0?MathAbs(openPrice-currentSL):0.0);
   if(d<=_Point)d=TZ34_HistoryInitialRisk(positionId,openPrice);
   if(d>_Point)GlobalVariableSet(key,d);
   return d;
}

void ManagePositions()
{
   MqlRates m1[],m5[];ArraySetAsSeries(m1,true);ArraySetAsSeries(m5,true);
   if(CopyRates(_Symbol,PERIOD_M1,0,30,m1)<20)return;
   bool hm5=CopyRates(_Symbol,RunnerTrailTF,0,30,m5)>=20;
   double a5=hm5?ATR(m5,ATRPeriod,1):0;
   MqlTick tk;if(!SymbolInfoTick(_Symbol,tk))return;

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);if(!ticket)continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol||(ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue;

      ENUM_POSITION_TYPE ty=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      bool buy=(ty==POSITION_TYPE_BUY);
      double o=PositionGetDouble(POSITION_PRICE_OPEN);
      double sl=PositionGetDouble(POSITION_SL);
      double tp=PositionGetDouble(POSITION_TP);
      double mark=buy?tk.bid:tk.ask;
      string comment=PositionGetString(POSITION_COMMENT);

      double initialRisk=TZ34_InitialRiskDistance(ticket,o,sl);
      if(initialRisk<=_Point)continue;
      double rnow=buy?(mark-o)/initialRisk:(o-mark)/initialRisk;
      double desired=sl;bool change=false;

      // BE remains conditional on +R progress AND fresh M1 structural progress.
      if(rnow>=BreakEvenArmAtR&&StructuralProgress(buy,m1))
      {
         double be=o;
         if((buy&&(sl==0||be>desired))||(!buy&&(sl==0||be<desired)))
         {desired=be;change=true;}
      }

      // Runner: after the configured R threshold, trail behind M5 structure and ATR.
      if(StringFind(comment," RUN")>=0&&hm5&&a5>0&&rnow>=RunnerTrailStartR)
      {
         int lookback=MathMin(RunnerTrailLookbackBars,ArraySize(m5)-2);
         double st=buy?m5[1].low:m5[1].high;
         for(int k=1;k<=lookback;k++)
         {
            if(buy)st=MathMin(st,m5[k].low);
            else st=MathMax(st,m5[k].high);
         }
         double structural=buy?st-a5*RunnerStructureATRBuffer:st+a5*RunnerStructureATRBuffer;
         double atrTrail=buy?mark-a5*RunnerTrailATRMultiple:mark+a5*RunnerTrailATRMultiple;
         double dyn=buy?MathMax(structural,atrTrail):MathMin(structural,atrTrail);
         if((buy&&(desired==0||dyn>desired))||(!buy&&(desired==0||dyn<desired)))
         {desired=dyn;change=true;}
      }

      if(!change)continue;
      desired=NormalizeDouble(desired,_Digits);

      // Respect broker stop-distance and never loosen an already protected stop.
      long stopLevel=(long)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
      double minStop=MathMax(_Point,(double)stopLevel*_Point);
      if(buy)desired=MathMin(desired,NormalizeDouble(tk.bid-minStop,_Digits));
      else desired=MathMax(desired,NormalizeDouble(tk.ask+minStop,_Digits));

      if((buy&&sl>0&&desired<=sl+_Point)||(!buy&&sl>0&&desired>=sl-_Point))continue;
      if(!trade.PositionModify(ticket,desired,tp))
         Print("SMC Research v3.45 management modify failed ticket=",ticket,
               " desiredSL=",desired," retcode=",trade.ResultRetcode());
   }
}

// Accepted-zone flip state is deliberately independent of the current cloud plan.
// The cloud may re-rank immediately after invalidation; we must retain the failed
// zone long enough to observe the opposite-side retest without granting an entry.
Plan g_tzFlipPlan;
bool g_tzFlipPlanStored=false;
datetime g_tzFlipAcceptedAt=0;
string g_tzFlipSourceAnalysis="";
string g_tzFlipSourceZone="";
int g_tzAcceptedFlipEntries=0;
int g_tzAcceptedFlipReentries=0;
bool g_tzFlipSniperContractVerified=false;
string g_tzFlipSourceContractFingerprint="";

void TZ_SetGate(string stage,string reason)
{
   g_tzGateStage=stage;g_tzGateReason=reason;
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();g_tzGateTs=now;
}

void TZ28_ClearAcceptedFlip(string reason)
{
   g_tzFlipPlanStored=false;g_tzFlipAcceptedAt=0;g_tzFlipSourceAnalysis="";g_tzFlipSourceZone="";
   g_tzAcceptedFlipEntries=0;g_tzAcceptedFlipReentries=0;g_tzAcceptedFlipRiskPct=0.0;
   g_tzFlipSniperContractVerified=false;g_tzFlipSourceContractFingerprint="";
   ZeroMemory(g_tzFlipPlan);
   FileDelete("TradeZone\\accepted_flip_state.txt");
   g_tzExecutionAuthority="NONE";
   TZ_SetGate("FLIP_RELEASED",reason);
}

void TZ28_SaveAcceptedFlip()
{
   if(IsTester())return;
   FolderCreate("TradeZone");
   if(!g_tzFlipPlanStored)
   {
      FileDelete("TradeZone\\accepted_flip_state.txt");
      return;
   }
   int h=FileOpen("TradeZone\\accepted_flip_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return;
   FileWriteString(h,"active=1\r\n");
   FileWriteString(h,"accepted_at="+IntegerToString((int)g_tzFlipAcceptedAt)+"\r\n");
   FileWriteString(h,"analysis_id="+g_tzFlipPlan.analysis_id+"\r\n");
   FileWriteString(h,"zone_id="+g_tzFlipPlan.zone_id+"\r\n");
   FileWriteString(h,"ea_mode="+g_tzFlipPlan.ea_mode+"\r\n");
   FileWriteString(h,"grade="+g_tzFlipPlan.grade+"\r\n");
   FileWriteString(h,"setup_type="+g_tzFlipPlan.setup_type+"\r\n");
   FileWriteString(h,"zone_state="+g_tzFlipPlan.zone_state+"\r\n");
   FileWriteString(h,"original_direction="+g_tzFlipPlan.original_direction+"\r\n");
   FileWriteString(h,"flip_direction="+g_tzFlipPlan.flip_direction+"\r\n");
   FileWriteString(h,"core_method="+g_tzFlipPlan.core_method+"\r\n");
   FileWriteString(h,"core_low="+DoubleToString(g_tzFlipPlan.core_low,_Digits)+"\r\n");
   FileWriteString(h,"core_high="+DoubleToString(g_tzFlipPlan.core_high,_Digits)+"\r\n");
   FileWriteString(h,"zone_low="+DoubleToString(g_tzFlipPlan.zone_low,_Digits)+"\r\n");
   FileWriteString(h,"zone_high="+DoubleToString(g_tzFlipPlan.zone_high,_Digits)+"\r\n");
   FileWriteString(h,"original_target1="+DoubleToString(g_tzFlipPlan.original_t1,_Digits)+"\r\n");
   FileWriteString(h,"original_target2="+DoubleToString(g_tzFlipPlan.original_t2,_Digits)+"\r\n");
   FileWriteString(h,"original_target3="+DoubleToString(g_tzFlipPlan.original_t3,_Digits)+"\r\n");
   FileWriteString(h,"original_runner="+DoubleToString(g_tzFlipPlan.original_run,_Digits)+"\r\n");
   FileWriteString(h,"flip_target1="+DoubleToString(g_tzFlipPlan.flip_t1,_Digits)+"\r\n");
   FileWriteString(h,"flip_target2="+DoubleToString(g_tzFlipPlan.flip_t2,_Digits)+"\r\n");
   FileWriteString(h,"flip_target3="+DoubleToString(g_tzFlipPlan.flip_t3,_Digits)+"\r\n");
   FileWriteString(h,"flip_runner="+DoubleToString(g_tzFlipPlan.flip_run,_Digits)+"\r\n");
   FileWriteString(h,"min_displacement_atr="+DoubleToString(g_tzFlipPlan.min_disp_atr,4)+"\r\n");
   FileWriteString(h,"min_rr="+DoubleToString(g_tzFlipPlan.min_rr,4)+"\r\n");
   FileWriteString(h,"flip_risk_pct="+DoubleToString(g_tzAcceptedFlipRiskPct,4)+"\r\n");
   FileWriteString(h,"flip_entries="+IntegerToString(g_tzAcceptedFlipEntries)+"\r\n");
   FileWriteString(h,"flip_reentries="+IntegerToString(g_tzAcceptedFlipReentries)+"\r\n");
   FileWriteString(h,"sniper_contract_verified="+(g_tzFlipSniperContractVerified?"1":"0")+"\r\n");
   FileWriteString(h,"sniper_contract_fingerprint="+g_tzFlipSourceContractFingerprint+"\r\n");
   FileClose(h);
}

void TZ28_LoadAcceptedFlip()
{
   if(IsTester())return;
   string active=TZ_ReadLocalKV("accepted_flip_state.txt","active");
   if(active!="1")return;
   Plan p;ZeroMemory(p);
   p.analysis_id=TZ_ReadLocalKV("accepted_flip_state.txt","analysis_id");
   p.zone_id=TZ_ReadLocalKV("accepted_flip_state.txt","zone_id");
   p.ea_mode=TZ_ReadLocalKV("accepted_flip_state.txt","ea_mode");
   p.grade=TZ_ReadLocalKV("accepted_flip_state.txt","grade");
   p.setup_type=TZ_ReadLocalKV("accepted_flip_state.txt","setup_type");
   p.zone_state=TZ_ReadLocalKV("accepted_flip_state.txt","zone_state");
   p.original_direction=TZ_ReadLocalKV("accepted_flip_state.txt","original_direction");
   p.flip_direction=TZ_ReadLocalKV("accepted_flip_state.txt","flip_direction");
   p.core_method=TZ_ReadLocalKV("accepted_flip_state.txt","core_method");
   p.core_low=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","core_low"));
   p.core_high=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","core_high"));
   p.zone_low=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","zone_low"));
   p.zone_high=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","zone_high"));
   p.original_t1=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","original_target1"));
   p.original_t2=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","original_target2"));
   p.original_t3=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","original_target3"));
   p.original_run=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","original_runner"));
   p.flip_t1=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","flip_target1"));
   p.flip_t2=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","flip_target2"));
   p.flip_t3=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","flip_target3"));
   p.flip_run=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","flip_runner"));
   p.min_disp_atr=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","min_displacement_atr"));
   p.min_rr=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","min_rr"));
   g_tzAcceptedFlipRiskPct=StringToDouble(TZ_ReadLocalKV("accepted_flip_state.txt","flip_risk_pct"));
   if(g_tzAcceptedFlipRiskPct<=0)
      g_tzAcceptedFlipRiskPct=TZ38_DefaultContextRiskPct(p.grade,TZ38_OppositeRiskContext(TZ38_DefaultRiskContext(p.setup_type)));
   p.valid=(p.analysis_id!=""&&p.zone_id!=""&&p.zone_low>0&&p.zone_high>p.zone_low);
   datetime accepted=(datetime)StringToInteger(TZ_ReadLocalKV("accepted_flip_state.txt","accepted_at"));
   if(!p.valid||accepted<=0){TZ28_ClearAcceptedFlip("PERSISTED_FLIP_INVALID");return;}
   g_tzFlipPlan=p;g_tzFlipPlanStored=true;g_tzFlipAcceptedAt=accepted;
   g_tzFlipSourceAnalysis=p.analysis_id;g_tzFlipSourceZone=p.zone_id;
   g_tzAcceptedFlipEntries=(int)StringToInteger(TZ_ReadLocalKV("accepted_flip_state.txt","flip_entries"));
   g_tzAcceptedFlipReentries=(int)StringToInteger(TZ_ReadLocalKV("accepted_flip_state.txt","flip_reentries"));
   g_tzFlipSniperContractVerified=(TZ_ReadLocalKV("accepted_flip_state.txt","sniper_contract_verified")=="1");
   g_tzFlipSourceContractFingerprint=TZ_ReadLocalKV("accepted_flip_state.txt","sniper_contract_fingerprint");
   TZ_SetGate("FLIP_CANDIDATE","PERSISTED_ACCEPTED_ZONE_FLIP_RESTORED");
}

void TZ28_ArmAcceptedFlip()
{
   if(!EnableZoneFlip||g_tzFlipPlanStored||!g_plan.valid)return;
   bool accepted=(g_plan.zone_state=="FAILED_FLIP_CANDIDATE");
   if(!accepted)accepted=M15Acceptance();
   if(!accepted)return;
   g_tzFlipPlan=g_plan;g_tzFlipPlanStored=true;
   g_tzFlipAcceptedAt=(g_flipAcceptedAt>0?g_flipAcceptedAt:TimeCurrent());
   g_tzFlipSourceAnalysis=g_plan.analysis_id;g_tzFlipSourceZone=g_plan.zone_id;
   g_tzFlipSniperContractVerified=g_tzSniperContractVerified;
   g_tzFlipSourceContractFingerprint=g_tzSniperContractFingerprint;
   g_tzAcceptedFlipEntries=0;g_tzAcceptedFlipReentries=0;
   g_tzAcceptedFlipRiskPct=(g_tzFlipRiskPct>0?g_tzFlipRiskPct:TZ38_DefaultContextRiskPct(g_plan.grade,TZ38_OppositeRiskContext(TZ38_DefaultRiskContext(g_plan.setup_type))));
   g_tzExecutionAuthority="NONE";
   TZ_SetGate("FLIP_CANDIDATE","M15_ACCEPTED_INVALIDATION_WAIT_OPPOSITE_RETEST");
   TZ28_SaveAcceptedFlip();
   Print("SMC Research v3.34: accepted invalidation captured BEFORE authority release. zone=",g_tzFlipSourceZone,
         " -> flip=",g_tzFlipPlan.flip_direction,". No instant reverse entry.");
}

bool TZ28_FlipSafetyGuards()
{
   if(!IsTester()&&!IsDemo()){TZ_SetGate("SAFETY","NON_DEMO_ACCOUNT");return false;}
   if(!g_tzFlipPlanStored||!g_tzFlipPlan.valid){TZ_SetGate("FLIP_CANDIDATE","NO_PERSISTED_FAILED_ZONE");return false;}
   if(!IsTester()&&OperatingMode==LIVE_CLOUD&&!g_tzFlipSniperContractVerified)
   {TZ_SetGate("PARITY","SNIPER_CONTRACT_UNVERIFIED_FLIP_SOURCE");return false;}
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(g_tzAcceptedFlipEntries==0&&ResearchFlipCandidateMaxMinutes>0&&
      now-g_tzFlipAcceptedAt>ResearchFlipCandidateMaxMinutes*60)
   {TZ28_ClearAcceptedFlip("FLIP_CANDIDATE_EXPIRED");return false;}
   if(!IsTester()&&OperatingMode==LIVE_CLOUD)
   {
      string text;
      if(!HttpGet("/mt5/plan",text)){TZ_SetGate("SAFETY","FLIP_CLOUD_SAFETY_UNAVAILABLE");return false;}
      if(KV(text,"live_block")=="1"){TZ_SetGate("SAFETY","FLIP_CLOUD_LIVE_BLOCK:"+KV(text,"live_block_reason"));return false;}
   }
   MqlTick t;if(!SymbolInfoTick(_Symbol,t)){TZ_SetGate("MARKET","NO_TICK");return false;}
   double spread=(t.ask-t.bid)/_Point;
   double maxSpread=PaperResearchMode?ResearchMaxSpreadPoints:MaxSpreadPoints;
   if(maxSpread>0&&spread>maxSpread){TZ_SetGate("SPREAD","SPREAD_TOO_HIGH");return false;}
   if(!PaperResearchMode||ResearchUseDailyLossGuard)
   {
      double maxLoss=AccountInfoDouble(ACCOUNT_BALANCE)*ThesisRiskPct/100.0*MaxDailyLossR;
      if(TodayPnL()<=-maxLoss){TZ_SetGate("RISK","DAILY_LOSS_GUARD");return false;}
   }
   return true;
}

string TZ28_DiagnoseFlipStage(MqlRates &r[],double a,bool buy)
{
   if(!g_tzFlipPlanStored)return "FLIP_CANDIDATE";
   int ret=-1;int mx=MathMin(FlipRetestMaxBars,ArraySize(r)-8);
   for(int i=3;i<=mx;i++)
   {
      if(r[i].time<g_tzFlipAcceptedAt)continue;
      if(!TouchZone(r[i]))continue;
      bool fromFlipSide=buy?(r[i].open>=g_plan.zone_high||r[i].high>=g_plan.zone_high):(r[i].open<=g_plan.zone_low||r[i].low<=g_plan.zone_low);
      if(fromFlipSide){ret=i;break;}
   }
   if(ret<3)return "FLIP_RETEST";
   int bp;double bos;if(!OlderPivot(r,ret+2,SwingLookback,buy,bp,bos))return "FLIP_MSS_BOS";
   bool broke=false,disp=false;
   for(int j=ret-1;j>=3;j--)
   {
      bool b=buy?(r[j].close>bos):(r[j].close<bos);
      if(!b)continue;broke=true;
      if(StrongDisp(r,j,a,FlipBreakDisplacementATR,buy)){disp=true;break;}
   }
   if(!broke)return "FLIP_MSS_BOS";
   if(!disp)return "FLIP_DISPLACEMENT";
   return "FLIP_VALUE_PD_ARRAY";
}

void TZ28_EvaluateAcceptedFlip()
{
   // Accepted invalidation is observation-only until the post-failure M1 pattern earns a handoff.
   g_tzExecutionAuthority="NONE";
   if(!TZ28_FlipSafetyGuards())return;
   Plan livePlan=g_plan;bool liveFlipCandidate=g_flipCandidate;datetime liveAccepted=g_flipAcceptedAt;
   g_plan=g_tzFlipPlan;g_flipCandidate=true;g_flipAcceptedAt=g_tzFlipAcceptedAt;
   bool releaseAfter=false;string releaseReason="";
   do
   {
      MqlRates r[];ArraySetAsSeries(r,true);
      if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160){TZ_SetGate("DATA","INSUFFICIENT_M1_BARS");break;}
      datetime cb=r[1].time;if(cb==g_lastTradeBar){TZ_SetGate("BAR","ALREADY_TRADED_THIS_BAR");break;}
      double a=ATR(r,ATRPeriod,1);if(a<=0){TZ_SetGate("DATA","M1_ATR_UNAVAILABLE");break;}
      MqlTick tk;if(!SymbolInfoTick(_Symbol,tk)){TZ_SetGate("MARKET","NO_TICK");break;}
      bool flipBuy=(g_plan.flip_direction=="BUY"),havePos=AnyOurPosition();
      double mark=flipBuy?tk.bid:tk.ask;
      if(g_tzAcceptedFlipEntries>0&&ObjectiveReached(true,flipBuy,mark))
      {releaseAfter=true;releaseReason="FLIP_OBJECTIVE_COMPLETE";break;}

      Signal sig;ZeroMemory(sig);string tag="";double share=0;g_tzCandidateModel="ACCEPTED_ZONE_FLIP";
      if(!havePos&&g_tzAcceptedFlipEntries==0)
      {
         if(BuildFlip(r,a,flipBuy,sig)){tag="F0";share=PrimaryRiskShare;}
      }
      else if(EnableReentries&&g_tzAcceptedFlipEntries>0&&g_tzAcceptedFlipReentries<MaxReentriesPerThesis&&
              (!havePos||AllProtected())&&!ObjectiveReached(true,flipBuy,mark))
      {
         if(BuildReentry(r,a,flipBuy,sig))
         {sig.flip=true;tag="FR"+IntegerToString(g_tzAcceptedFlipReentries+1);share=(g_tzAcceptedFlipReentries==0?Reentry1RiskShare:Reentry2RiskShare);}
      }

      if(!sig.valid)
      {
         string stage=(g_tzAcceptedFlipEntries==0?TZ28_DiagnoseFlipStage(r,a,flipBuy):"FLIP_REENTRY");
         g_tzExecutionAuthority="NONE";
         TZ_SetGate(stage,"WAITING_FOR_VALID_"+stage);
         break;
      }

      int flipShiftIdx=-1;double flipShiftLevel=0.0;string flipShiftReason="";
      if(!TZ62_UniversalM1ShiftReady(r,sig.buy,sig,flipShiftReason,flipShiftIdx,flipShiftLevel))
      {g_tzExecutionAuthority="NONE";TZ_SetGate("M1_MICRO_SHIFT","FLIP_"+flipShiftReason);break;}

      // Authority is observation permission only. Every accepted-zone flip model,
      // including FR re-entries, must now confirm a CLOSED M1 rejection from value
      // plus a same-direction micro break before any order can be sent.
      g_tzExecutionAuthority="ACCEPTED_ZONE_FLIP_HANDOFF";
      double entry=sig.buy?tk.ask:tk.bid;
      int flipReactionIdx=-1;string flipConfirmationReason="";
      if(!TZ39_FlipEntryReady(r,a,sig.buy,sig,entry,tag,flipConfirmationReason,flipReactionIdx))
      {
         TZ_SetGate("FLIP_CONFIRMATION",flipConfirmationReason);
         break;
      }
      if(!TZ_TargetDirectionValid(true,sig.buy,entry)){TZ_SetGate("TARGET","NO_OPEN_FLIP_TARGET_BEYOND_ENTRY");break;}
      string seq=g_tzFlipSourceAnalysis+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;
      if(seq==g_lastSequence){TZ_SetGate("DUPLICATE","FLIP_SEQUENCE_ALREADY_SENT");break;}
      double microSl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;
      double sl=(tag=="F0")
         ?TZ46_InitialZoneProtectedStop(sig.buy,microSl,g_tzFlipPlan.zone_low,g_tzFlipPlan.zone_high,a)
         :NormalizeDouble(microSl,_Digits);
      entry=NormalizeDouble(entry,_Digits);
      if(sl<=0){TZ_SetGate("RISK","FLIP_ZONE_DISTAL_STOP_UNAVAILABLE");break;}
      if((sig.buy&&sl>=entry)||(!sig.buy&&sl<=entry)){TZ_SetGate("RISK","INVALID_FLIP_STOP_SIDE");break;}
      double risk=TZ38_ThesisBudget(true,g_tzFlipPlan.grade)*share;g_tzLastRiskMoney=risk;double lots=TZ37_LotsForRisk(sig.buy,entry,sl,risk);g_tzLastIntendedLots=lots;
      if(lots<=0){TZ_SetGate("RISK","FLIP_LOT_SIZE_ZERO");break;}
      if(TZ37_SendOrders(sig.buy,entry,sl,lots,true,tag,sig.pd_type))
      {
         if(tag=="F0")g_tzAcceptedFlipEntries++;else g_tzAcceptedFlipReentries++;
         g_flipPrimaryEntries=g_tzAcceptedFlipEntries;g_flipReentries=g_tzAcceptedFlipReentries;
         g_lastSequence=seq;g_lastTradeBar=cb;g_tzLastModel="ACCEPTED_ZONE_FLIP_"+sig.pd_type;
         TZ_SetGate("ORDER_SENT","DEMO_ACCEPTED_ZONE_FLIP_OPENED");
         TZ28_SaveAcceptedFlip();
         Print("SMC Research v3.45 ",tag," opened from accepted-zone flip. authority=",g_tzExecutionAuthority,
               " sourceZone=",g_tzFlipSourceZone," entry=",entry," sl=",sl," riskMoney=",risk);
      }
      else TZ_SetGate("ORDER","MT5_FLIP_ORDER_SEND_FAILED");
   }
   while(false);
   g_tzFlipPlan=g_plan;
   g_plan=livePlan;g_flipCandidate=liveFlipCandidate;g_flipAcceptedAt=liveAccepted;
   if(releaseAfter)TZ28_ClearAcceptedFlip(releaseReason);
}

string TZ_JsonEscape(string s)
{
   StringReplace(s,"\\","\\\\");
   StringReplace(s,"\"","\\\"");
   StringReplace(s,"\r"," ");
   StringReplace(s,"\n"," ");
   return s;
}

string TZ_ReadLocalKV(string fileName,string key)
{
   int h=FileOpen("TradeZone\\"+fileName,FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return "";
   string needle=key+"=",value="";
   while(!FileIsEnding(h))
   {
      string line=FileReadString(h);
      if(StringFind(line,needle)==0){value=StringSubstr(line,StringLen(needle));break;}
   }
   FileClose(h);
   StringTrimLeft(value);StringTrimRight(value);return value;
}

uint TZ_Hash(string s)
{
   uint h=2166136261;
   for(int i=0;i<StringLen(s);i++){h^=(uint)StringGetCharacter(s,i);h*=16777619;}
   return h;
}

string TZ_StatePrefix()
{
   string ownerActive=TZ30_OwnerKV("owner_mirror_active");
   string campaign=TZ30_OwnerKV("owner_mirror_campaign_key");
   string ownerId=TZ30_OwnerKV("owner_mirror_zone_id");
   string acquired=TZ30_OwnerKV("owner_mirror_acquired_at");
   string seed="";
   if(ownerActive=="1"&&campaign!="") seed="CAMPAIGN|"+campaign;
   else if(ownerActive=="1"&&ownerId!="") seed="OWNER|"+ownerId+"|"+acquired;
   else if(g_tzRuntimeThesisKey!="") seed=g_tzRuntimeThesisKey;
   else if(g_plan.zone_id!="") seed="ZONE|"+g_plan.zone_id;
   else if(g_plan.analysis_id!="") seed="ANALYSIS|"+g_plan.analysis_id;
   if(seed=="")return "";
   return "TZ."+IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN))+"."+_Symbol+"."+IntegerToString((int)TZ_Hash(seed));
}

int TZ_OpenPositionCount()
{
   int n=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);if(!t)continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol && (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber)n++;
   }
   return n;
}

void TZ_LoadPersistentState()
{
   string p=TZ_StatePrefix();if(p==""||p==g_tzLoadedStateKey)return;g_tzLoadedStateKey=p;
   if(GlobalVariableCheck(p+".P"))g_primaryEntries=(int)GlobalVariableGet(p+".P");
   if(GlobalVariableCheck(p+".R"))g_reentries=(int)GlobalVariableGet(p+".R");
   if(GlobalVariableCheck(p+".FP"))g_flipPrimaryEntries=(int)GlobalVariableGet(p+".FP");
   if(GlobalVariableCheck(p+".FR"))g_flipReentries=(int)GlobalVariableGet(p+".FR");
   if(GlobalVariableCheck(p+".BAR"))g_lastTradeBar=(datetime)GlobalVariableGet(p+".BAR");
   if(GlobalVariableCheck(p+".FLIP"))g_flipCandidate=(GlobalVariableGet(p+".FLIP")>0.5);
   if(GlobalVariableCheck(p+".FAT"))g_flipAcceptedAt=(datetime)GlobalVariableGet(p+".FAT");
}

void TZ_SavePersistentState()
{
   string p=TZ_StatePrefix();if(p=="")return;
   GlobalVariableSet(p+".P",(double)g_primaryEntries);GlobalVariableSet(p+".R",(double)g_reentries);
   GlobalVariableSet(p+".FP",(double)g_flipPrimaryEntries);GlobalVariableSet(p+".FR",(double)g_flipReentries);
   GlobalVariableSet(p+".BAR",(double)g_lastTradeBar);GlobalVariableSet(p+".FLIP",g_flipCandidate?1.0:0.0);
   GlobalVariableSet(p+".FAT",(double)g_flipAcceptedAt);
}

bool TZ_Post(string path,string body,string &response)
{
   if(CloudApiKey=="")return false;
   string url=CloudBaseUrl+path,headers="Content-Type: application/json\r\nX-API-Key: "+CloudApiKey+"\r\n";
   char data[],result[];string rh;StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);
   if(ArraySize(data)>0)ArrayResize(data,ArraySize(data)-1);ResetLastError();
   int code=WebRequest("POST",url,headers,HttpTimeoutMs,data,result,rh);
   response=CharArrayToString(result,0,-1,CP_UTF8);return code==200;
}

void TZ30_SaveOwnerMirrorFromPlan(string text)
{
   if(IsTester())return;
   if(KV(text,"owner_mirror_contract")!="MT5_EXECUTION_OWNER_MIRROR_V1")return;
   FolderCreate("TradeZone");
   if(KV(text,"owner_mirror_active")!="1")
   {
      // A cloud-confirmed owner release is a tombstone on the MT5 side. Never
      // leave an old active mirror that could be echoed back after a restart.
      FileDelete("TradeZone\\execution_owner_state.txt");
      return;
   }
   int h=FileOpen("TradeZone\\execution_owner_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return;
   string keys[]={
      "owner_mirror_contract","owner_mirror_active","owner_mirror_saved_at",
      "owner_mirror_analysis_id","owner_mirror_zone_id","owner_mirror_direction",
      "owner_mirror_source_tf","owner_mirror_source_ts","owner_mirror_grade",
      "owner_mirror_status","owner_mirror_authority","owner_mirror_acquired_at","owner_mirror_campaign_key",
      "owner_mirror_core_low","owner_mirror_core_high","owner_mirror_zone_low","owner_mirror_zone_high",
      "owner_mirror_target1","owner_mirror_target2","owner_mirror_target3",
      "owner_mirror_target1_hit_at","owner_mirror_target2_hit_at","owner_mirror_target3_hit_at",
      "owner_mirror_reaction_confirmed_at","owner_mirror_best_price",
      "owner_mirror_zone_payload_b64"
   };
   for(int i=0;i<ArraySize(keys);i++)
      FileWriteString(h,keys[i]+"="+KV(text,keys[i])+"\r\n");
   FileClose(h);
}

string TZ30_OwnerKV(string key){return TZ_ReadLocalKV("execution_owner_state.txt",key);}
string TZ30_OwnerNum(string key)
{
   string v=TZ30_OwnerKV(key);
   return v==""?"0":v;
}

void TZ27_LoadExecutionAuthority(bool force=false)
{
   if(IsTester()){g_tzExecutionAuthority="HTF_CORE_HANDOFF";return;}
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(!force && now-g_tzLastAuthorityPoll<MathMax(2,PollSeconds))return;
   g_tzLastAuthorityPoll=now;
   string text;if(!HttpGet("/mt5/plan",text)){g_tzExecutionAuthority="NONE";TZ_SetGate("AUTHORITY","PLAN_HTTP_UNAVAILABLE");return;}
   TZ30_SaveOwnerMirrorFromPlan(text);
   if(KV(text,"analysis_id")!=g_plan.analysis_id){g_tzExecutionAuthority="NONE";TZ_SetGate("AUTHORITY","ANALYSIS_ID_MISMATCH");return;}
   g_tzExecutionAuthority=KV(text,"execution_authority");if(g_tzExecutionAuthority=="")g_tzExecutionAuthority="NONE";
   g_tzLRDirection=KV(text,"liquidity_reversal_direction");
   g_tzLRLabel=KV(text,"liquidity_reversal_label");
   g_tzLRPrice=StringToDouble(KV(text,"liquidity_reversal_price"));
   double rm=StringToDouble(KV(text,"liquidity_reversal_risk_multiplier"));
   g_tzLRRiskMultiplier=(rm>0&&rm<=1.0?rm:ResearchLiquidityReversalRiskMultiplier);
   TZ38_LoadRiskContract(text,g_plan.grade,g_plan.setup_type);
   TZ42_RefreshSniperParityFromPlan(text);
   TZ48_LoadRunwayContract(text);
}


bool TZ47_TextFlag(string text,string key,bool def=false)
{
   string v=KV(text,key);if(v=="")return def;StringToLower(v);
   return (v=="1"||v=="true"||v=="yes"||v=="on");
}


void TZ48_LoadRunwayContract(string text)
{
   g_tzRequiredRunway=StringToDouble(KV(text,"required_runway"));
   g_tzRunwayTarget=StringToDouble(KV(text,"usable_runway_target"));
   g_tzRunwayEntryLimit=StringToDouble(KV(text,"runway_entry_limit"));
   g_tzRunwayGateMode=KV(text,"runway_gate_mode");
   if(g_tzRunwayGateMode=="")g_tzRunwayGateMode="UNSET";
   g_tzEntrySpecificRunwayRuntimeReady=(KV(text,"entry_specific_runway_runtime_ready")=="1");
}

bool TZ48_EntrySpecificRunwayValid(
   bool buy,double entry,double openTarget,double &actualRunway,double &requiredRunway
)
{
   actualRunway=0.0;
   requiredRunway=g_tzRequiredRunway;
   if(openTarget<=0||entry<=0)
   {
      TZ_SetGate("TARGET","ENTRY_RUNWAY_TARGET_OR_ENTRY_MISSING");
      return false;
   }
   if(OperatingMode==LIVE_CLOUD&&requiredRunway<=0)
   {
      TZ_SetGate("TARGET","ENTRY_RUNWAY_CONTRACT_MISSING");
      return false;
   }
   if(requiredRunway<=0)return true; // tester/local compatibility only

   actualRunway=buy?(openTarget-entry):(entry-openTarget);
   g_tzLastActualRunway=actualRunway;
   double eps=MathMax(_Point*0.5,1e-9);
   if(actualRunway+eps<requiredRunway)
   {
      TZ_SetGate(
         "TARGET",
         "ENTRY_SPECIFIC_RUNWAY_NOT_MET:"+DoubleToString(actualRunway,5)+
         "/"+DoubleToString(requiredRunway,5)
      );
      return false;
   }
   return true;
}

bool TZ31_RefreshCloudState(bool force=false)
{
   if(IsTester())
   {
      if(!RefreshPlan())return false;
      g_tzExecutionAuthority="HTF_CORE_HANDOFF";
      g_tzCloudRegime="TESTER";
      g_tzAllowMomentum=EnableMomentumPullbackModel;
      g_tzAllowVWAP=EnableVWAPProxyModel;
      g_tzAllowORB=EnableOpeningRangeRetestModel;
      g_tzAllowBreakout=EnableInstitutionalBreakoutModel;
      g_tzCloudLiveBlocked=false;g_tzCloudLiveBlockReason="";
      return true;
   }
   if(OperatingMode!=LIVE_CLOUD)return RefreshPlan();
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(!force && g_plan.valid && now-g_tzLastCloudSync<MathMax(2,PollSeconds))return true;

   string text;
   if(!HttpGet("/mt5/plan",text))
   {
      g_tzExecutionAuthority="NONE";TZ_SetGate("AUTHORITY","PLAN_HTTP_UNAVAILABLE");return false;
   }
   g_tzLastCloudSync=now;

   // Safety must suspend ORDER permission, not plan synchronization. Always load
   // the exact frozen plan, authority, risk and parity truth before evaluating a
   // live spread/snapshot/news block.
   TZ30_SaveOwnerMirrorFromPlan(text);

   Plan p;if(!ParsePlanText(text,p))
   {
      g_tzExecutionAuthority="NONE";TZ_SetGate("PLAN","PLAN_PARSE_FAILED");return false;
   }

   string ownerActive=KV(text,"owner_mirror_active");
   string ownerId=KV(text,"owner_mirror_zone_id");
   string ownerAcquired=KV(text,"owner_mirror_acquired_at");
   string ownerCampaign=KV(text,"owner_mirror_campaign_key");
   string newThesisKey=(ownerActive=="1"&&ownerCampaign!="")
      ?("CAMPAIGN|"+ownerCampaign)
      :(ownerActive=="1"&&ownerId!="")
         ?("OWNER|"+ownerId+"|"+ownerAcquired)
         :("ZONE|"+p.zone_id);
   if(g_tzRuntimeThesisKey!=""&&newThesisKey!=g_tzRuntimeThesisKey)ResetPlanState();
   g_tzRuntimeThesisKey=newThesisKey;
   g_lastAnalysis=p.analysis_id;
   g_plan=p;

   g_tzExecutionAuthority=KV(text,"execution_authority");
   if(g_tzExecutionAuthority=="")g_tzExecutionAuthority="NONE";
   g_tzExecutionHandoffTs=(datetime)StringToInteger(KV(text,"execution_handoff_ts"));
   g_tzLRDirection=KV(text,"liquidity_reversal_direction");
   g_tzLRLabel=KV(text,"liquidity_reversal_label");
   g_tzLRPrice=StringToDouble(KV(text,"liquidity_reversal_price"));
   double rm=StringToDouble(KV(text,"liquidity_reversal_risk_multiplier"));
   g_tzLRRiskMultiplier=(rm>0&&rm<=1.0?rm:ResearchLiquidityReversalRiskMultiplier);
   TZ38_LoadRiskContract(text,g_plan.grade,g_plan.setup_type);
   TZ42_RefreshSniperParityFromPlan(text);
   TZ48_LoadRunwayContract(text);

   g_tzCloudRegime=KV(text,"market_regime");if(g_tzCloudRegime=="")g_tzCloudRegime="UNKNOWN";
   g_tzAllowMomentum=EnableMomentumPullbackModel&&TZ47_TextFlag(text,"model_momentum_pullback",false);
   g_tzAllowVWAP=EnableVWAPProxyModel&&TZ47_TextFlag(text,"model_vwap_proxy_reclaim",false);
   g_tzAllowORB=EnableOpeningRangeRetestModel&&TZ47_TextFlag(text,"model_opening_range_retest",false);
   g_tzAllowBreakout=EnableInstitutionalBreakoutModel&&TZ47_TextFlag(text,"model_institutional_breakout",false);

   g_tzCloudLiveBlocked=(KV(text,"live_block")=="1");
   g_tzCloudLiveBlockReason=KV(text,"live_block_reason");
   if(g_tzCloudLiveBlocked)
      TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"+g_tzCloudLiveBlockReason);

   if(g_plan.zone_state=="FAILED_FLIP_CANDIDATE")
   {
      g_flipCandidate=true;
      if(g_flipAcceptedAt==0)g_flipAcceptedAt=TimeCurrent();
   }
   return true;
}

void TZ_WriteSequenceState()
{
   if(IsTester())return;datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(now-g_tzLastStateWrite<5)return;g_tzLastStateWrite=now;
   int openCount=TZ_OpenPositionCount();bool safe=(openCount==0);FolderCreate("TradeZone");
   int h=FileOpen("TradeZone\\sequence_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);if(h==INVALID_HANDLE)return;
   FileWriteString(h,"ts="+IntegerToString((int)now)+"\r\n");
   FileWriteString(h,"version="+TZ_SEQUENCE_VERSION+"\r\n");
   FileWriteString(h,"restart_safe="+(safe?"1":"0")+"\r\n");
   FileWriteString(h,"active_sequence="+(openCount>0?"1":"0")+"\r\n");
   FileWriteString(h,"open_positions="+IntegerToString(openCount)+"\r\n");
   FileWriteString(h,"analysis_id="+g_plan.analysis_id+"\r\n");
   FileWriteString(h,"zone_id="+g_plan.zone_id+"\r\n");
   FileWriteString(h,"plan_valid="+(g_plan.valid?"1":"0")+"\r\n");
   FileWriteString(h,"execution_authority="+g_tzExecutionAuthority+"\r\n");
   FileWriteString(h,"direction="+g_plan.original_direction+"\r\n");
   FileWriteString(h,"current_grade="+g_plan.grade+"\r\n");
   FileWriteString(h,"qualified_mitigations="+IntegerToString(g_tzQualifiedMitigations)+"\r\n");
   FileWriteString(h,"contract_fingerprint="+g_tzSniperContractFingerprint+"\r\n");
   FileWriteString(h,"expected_contract_fingerprint="+g_tzExpectedSniperContractFingerprint+"\r\n");
   FileWriteString(h,"contract_execution_authority="+g_tzSniperContractAuthority+"\r\n");
   FileWriteString(h,"contract_parity_status="+g_tzSniperParityStatus+"\r\n");
   FileWriteString(h,"last_execution_model="+g_tzLastModel+"\r\n");
   FileWriteString(h,"gate_stage="+g_tzGateStage+"\r\n");
   FileWriteString(h,"gate_reason="+g_tzGateReason+"\r\n");
   FileWriteString(h,"candidate_model="+g_tzCandidateModel+"\r\n");
   FileWriteString(h,"campaign_key="+TZ30_OwnerKV("owner_mirror_campaign_key")+"\r\n");
   FileWriteString(h,"trace_contact_ts="+IntegerToString((int)g_tzTraceContactTs)+"\r\n");
   FileWriteString(h,"trace_reconstructed_pre_handoff="+(g_tzTraceReconstructedPreHandoff?"1":"0")+"\r\n");
   FileWriteString(h,"trace_liquidity_level="+DoubleToString(g_tzTraceLiquidityLevel,5)+"\r\n");
   FileWriteString(h,"trace_sweep_price="+DoubleToString(g_tzTraceSweepPrice,5)+"\r\n");
   FileWriteString(h,"trace_sweep_ts="+IntegerToString((int)g_tzTraceSweepTs)+"\r\n");
   FileWriteString(h,"trace_mss_level="+DoubleToString(g_tzTraceMssLevel,5)+"\r\n");
   FileWriteString(h,"trace_mss_break_ts="+IntegerToString((int)g_tzTraceMssBreakTs)+"\r\n");
   FileWriteString(h,"trace_pd_type="+g_tzTracePdType+"\r\n");
   FileWriteString(h,"trace_pd_low="+DoubleToString(g_tzTracePdLow,5)+"\r\n");
   FileWriteString(h,"trace_pd_high="+DoubleToString(g_tzTracePdHigh,5)+"\r\n");
   FileWriteString(h,"trace_pd_ts="+IntegerToString((int)g_tzTracePdTs)+"\r\n");
   FileWriteString(h,"trace_pullback_ts="+IntegerToString((int)g_tzTracePullbackTs)+"\r\n");
   FileWriteString(h,"trace_confirm_ts="+IntegerToString((int)g_tzTraceConfirmTs)+"\r\n");
   FileWriteString(h,"cloud_regime="+g_tzCloudRegime+"\r\n");
   FileWriteString(h,"local_regime="+g_tzLocalRegime+"\r\n");
   FileWriteString(h,"allow_momentum="+(g_tzAllowMomentum?"1":"0")+"\r\n");
   FileWriteString(h,"allow_vwap="+(g_tzAllowVWAP?"1":"0")+"\r\n");
   FileWriteString(h,"allow_orb="+(g_tzAllowORB?"1":"0")+"\r\n");
   FileWriteString(h,"allow_breakout="+(g_tzAllowBreakout?"1":"0")+"\r\n");
   FileWriteString(h,"risk_model="+g_tzRiskModel+"\r\n");
   FileWriteString(h,"risk_epoch="+g_tzRiskEpoch+"\r\n");
   FileWriteString(h,"validation_initial_capital="+DoubleToString(g_tzValidationInitialCapital,2)+"\r\n");
   FileWriteString(h,"grade_risk_pct="+DoubleToString(g_tzGradeRiskPct,2)+"\r\n");
   FileWriteString(h,"risk_context="+g_tzRiskContext+"\r\n");
   FileWriteString(h,"original_risk_pct="+DoubleToString(g_tzOriginalRiskPct,2)+"\r\n");
   FileWriteString(h,"flip_risk_pct="+DoubleToString(g_tzFlipRiskPct,2)+"\r\n");
   FileWriteString(h,"last_risk_base="+DoubleToString(g_tzLastRiskBase,2)+"\r\n");
   FileWriteString(h,"last_risk_money="+DoubleToString(g_tzLastRiskMoney,2)+"\r\n");
   FileWriteString(h,"last_intended_lots="+DoubleToString(g_tzLastIntendedLots,4)+"\r\n");
   FileWriteString(h,"last_actual_lots="+DoubleToString(g_tzLastActualLots,4)+"\r\n");
   FileWriteString(h,"required_runway="+DoubleToString(g_tzRequiredRunway,5)+"\r\n");
   FileWriteString(h,"runway_target="+DoubleToString(g_tzRunwayTarget,5)+"\r\n");
   FileWriteString(h,"runway_entry_limit="+DoubleToString(g_tzRunwayEntryLimit,5)+"\r\n");
   FileWriteString(h,"runway_gate_mode="+g_tzRunwayGateMode+"\r\n");
   FileWriteString(h,"last_actual_entry_runway="+DoubleToString(g_tzLastActualRunway,5)+"\r\n");
   FileWriteString(h,"gate_ts="+IntegerToString((int)g_tzGateTs)+"\r\n");
   FileWriteString(h,"primary_entries="+IntegerToString(g_primaryEntries)+"\r\n");
   FileWriteString(h,"reentries="+IntegerToString(g_reentries)+"\r\n");
   FileWriteString(h,"flip_primary_entries="+IntegerToString(g_flipPrimaryEntries)+"\r\n");
   FileWriteString(h,"flip_reentries="+IntegerToString(g_flipReentries)+"\r\n");FileClose(h);
}

void TZ_SendSequenceHeartbeat()
{
   if(IsTester()||OperatingMode!=LIVE_CLOUD)return;datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(now-g_tzLastHeartbeat<15)return;g_tzLastHeartbeat=now;int openCount=TZ_OpenPositionCount();bool safe=(openCount==0);
   string updater=TZ_ReadLocalKV("updater_status.txt","updater_version"),stable=TZ_ReadLocalKV("updater_status.txt","stable_release");
   string installedBridge=TZ_ReadLocalKV("updater_status.txt","installed_bridge_version"),installedSequence=TZ_ReadLocalKV("updater_status.txt","installed_sequence_version");
   string desiredBridge=TZ_ReadLocalKV("updater_status.txt","desired_bridge_version"),desiredSequence=TZ_ReadLocalKV("updater_status.txt","desired_sequence_version");
   string pending=TZ_ReadLocalKV("updater_status.txt","pending_reload"),updateResult=TZ_ReadLocalKV("updater_status.txt","result");
   string body=StringFormat(
      "{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_SequenceEA\",\"version\":\"%s\",\"symbol\":\"%s\",\"account_login\":%I64d,"
      "\"details\":{\"paper_only\":true,\"research_mode\":true,\"restart_safe\":%s,\"active_sequence\":%s,\"open_positions\":%d,"
      "\"state_persisted\":true,\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"plan_valid\":%s,\"execution_authority\":\"%s\",\"direction\":\"%s\",\"current_grade\":\"%s\",\"qualified_mitigations\":%d,\"risk_context\":\"%s\",\"base_risk_pct\":%s,\"contract_fingerprint\":\"%s\",\"expected_contract_fingerprint\":\"%s\",\"contract_execution_authority\":\"%s\",\"contract_parity_status\":\"%s\",\"last_execution_model\":\"%s\","
      "\"owner_mirror_contract\":\"%s\",\"owner_mirror_active\":%s,\"owner_mirror_saved_at\":%I64d,"
      "\"owner_mirror_analysis_id\":\"%s\",\"owner_mirror_zone_id\":\"%s\",\"owner_mirror_direction\":\"%s\","
      "\"owner_mirror_source_tf\":\"%s\",\"owner_mirror_source_ts\":%I64d,\"owner_mirror_grade\":\"%s\","
      "\"owner_mirror_status\":\"%s\",\"owner_mirror_authority\":\"%s\",\"owner_mirror_acquired_at\":%I64d,"
      "\"owner_mirror_core_low\":%s,\"owner_mirror_core_high\":%s,\"owner_mirror_zone_low\":%s,\"owner_mirror_zone_high\":%s,"
      "\"owner_mirror_target1\":%s,\"owner_mirror_target2\":%s,\"owner_mirror_target3\":%s,"
      "\"owner_mirror_target1_hit_at\":%I64d,\"owner_mirror_target2_hit_at\":%I64d,\"owner_mirror_target3_hit_at\":%I64d,"
      "\"owner_mirror_reaction_confirmed_at\":%I64d,\"owner_mirror_best_price\":%s,\"owner_mirror_zone_payload_b64\":\"%s\","
      "\"execution_handoff_ts\":%I64d,"
      "\"gate_stage\":\"%s\",\"gate_reason\":\"%s\",\"candidate_model\":\"%s\",\"trace_liquidity_level\":%s,\"trace_sweep_price\":%s,\"trace_sweep_ts\":%I64d,\"trace_mss_level\":%s,\"trace_mss_break_ts\":%I64d,\"trace_pd_type\":\"%s\",\"trace_pd_low\":%s,\"trace_pd_high\":%s,\"trace_pd_ts\":%I64d,\"trace_pullback_ts\":%I64d,\"trace_confirm_ts\":%I64d,\"cloud_regime\":\"%s\",\"local_regime\":\"%s\",\"allow_momentum\":%s,\"allow_vwap\":%s,\"allow_orb\":%s,\"gate_ts\":%I64d,"
      "\"primary_entries\":%d,\"reentries\":%d,\"flip_primary_entries\":%d,\"flip_reentries\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\",\"installed_sequence_version\":\"%s\","
      "\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\",\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_plan.original_direction),TZ_JsonEscape(g_plan.grade),g_tzQualifiedMitigations,TZ_JsonEscape(g_tzRiskContext),DoubleToString(g_tzOriginalRiskPct,8),TZ_JsonEscape(g_tzSniperContractFingerprint),TZ_JsonEscape(g_tzExpectedSniperContractFingerprint),TZ_JsonEscape(g_tzSniperContractAuthority),TZ_JsonEscape(g_tzSniperParityStatus),TZ_JsonEscape(g_tzLastModel),
      TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_contract")),
      TZ30_OwnerKV("owner_mirror_active")=="1"?"true":"false",
      (long)StringToInteger(TZ30_OwnerKV("owner_mirror_saved_at")),
      TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_analysis_id")),TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_zone_id")),TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_direction")),
      TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_source_tf")),(long)StringToInteger(TZ30_OwnerKV("owner_mirror_source_ts")),TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_grade")),
      TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_status")),TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_authority")),(long)StringToInteger(TZ30_OwnerKV("owner_mirror_acquired_at")),
      TZ30_OwnerNum("owner_mirror_core_low"),TZ30_OwnerNum("owner_mirror_core_high"),TZ30_OwnerNum("owner_mirror_zone_low"),TZ30_OwnerNum("owner_mirror_zone_high"),
      TZ30_OwnerNum("owner_mirror_target1"),TZ30_OwnerNum("owner_mirror_target2"),TZ30_OwnerNum("owner_mirror_target3"),
      (long)StringToInteger(TZ30_OwnerKV("owner_mirror_target1_hit_at")),(long)StringToInteger(TZ30_OwnerKV("owner_mirror_target2_hit_at")),(long)StringToInteger(TZ30_OwnerKV("owner_mirror_target3_hit_at")),
      (long)StringToInteger(TZ30_OwnerKV("owner_mirror_reaction_confirmed_at")),TZ30_OwnerNum("owner_mirror_best_price"),TZ_JsonEscape(TZ30_OwnerKV("owner_mirror_zone_payload_b64")),
      (long)g_tzExecutionHandoffTs,
      TZ_JsonEscape(g_tzGateStage),TZ_JsonEscape(g_tzGateReason),TZ_JsonEscape(g_tzCandidateModel),DoubleToString(g_tzTraceLiquidityLevel,5),DoubleToString(g_tzTraceSweepPrice,5),(long)g_tzTraceSweepTs,DoubleToString(g_tzTraceMssLevel,5),(long)g_tzTraceMssBreakTs,TZ_JsonEscape(g_tzTracePdType),DoubleToString(g_tzTracePdLow,5),DoubleToString(g_tzTracePdHigh,5),(long)g_tzTracePdTs,(long)g_tzTracePullbackTs,(long)g_tzTraceConfirmTs,TZ_JsonEscape(g_tzCloudRegime),TZ_JsonEscape(g_tzLocalRegime),g_tzAllowMomentum?"true":"false",g_tzAllowVWAP?"true":"false",g_tzAllowORB?"true":"false",(long)g_tzGateTs,
      g_primaryEntries,g_reentries,g_flipPrimaryEntries,g_flipReentries,TZ_JsonEscape(updater),TZ_JsonEscape(stable),TZ_JsonEscape(installedBridge),TZ_JsonEscape(installedSequence),
      TZ_JsonEscape(desiredBridge),TZ_JsonEscape(desiredSequence),TZ_JsonEscape(pending),TZ_JsonEscape(updateResult));
   string r;TZ_Post("/mt5/heartbeat",body,r);
}

void TZ_PreCoreSync()
{
   if(IsTester())return;
   if(OperatingMode==LIVE_CLOUD)TZ31_RefreshCloudState(false);
   TZ_LoadPersistentState();
}

bool TZ_RecentZoneInteraction(MqlRates &r[],int bars)
{
   int n=MathMin(bars,ArraySize(r)-2);for(int i=1;i<=n;i++)if(r[i].high>=g_plan.zone_low&&r[i].low<=g_plan.zone_high)return true;return false;
}

double TZ47_Efficiency(MqlRates &r[],int n)
{
   n=MathMin(n,ArraySize(r)-2);if(n<3)return 0.0;
   double path=0.0;for(int i=1;i<=n;i++)path+=MathAbs(r[i].close-r[i+1].close);
   if(path<=0)return 0.0;
   return MathMin(1.0,MathAbs(r[1].close-r[n+1].close)/path);
}

string TZ47_LocalRegime(MqlRates &r[])
{
   if(ArraySize(r)<80)return "UNKNOWN";
   double fast=ATR(r,7,1),slow=ATR(r,28,1),eff=TZ47_Efficiency(r,24);
   if(fast<=0||slow<=0)return "UNKNOWN";
   double vr=fast/slow;
   if(vr>=1.45&&eff<=0.28)return "EXHAUSTION";
   if(vr>=1.22&&eff>=0.34)return "EXPANSION";
   if(vr<=0.76)return "COMPRESSION";
   if(eff>=0.46)return "TREND";
   return "RANGE";
}

bool TZ47_RegimeAllows(string model,string localRegime)
{
   if(model=="MOMENTUM")return g_tzAllowMomentum&&(localRegime=="TREND"||localRegime=="EXPANSION");
   if(model=="VWAP")return g_tzAllowVWAP&&localRegime=="TREND";
   if(model=="ORB")return g_tzAllowORB&&(localRegime=="TREND"||localRegime=="EXPANSION");
   return false;
}

double TZ47_VWAP(MqlRates &r[],int start,int count)
{
   int end=MathMin(start+count,ArraySize(r));if(start<0||start>=end)return 0.0;
   double pv=0.0,w=0.0;
   for(int i=start;i<end;i++)
   {
      double wt=(double)r[i].tick_volume;if(wt<=0)wt=1.0;
      double tp=(r[i].high+r[i].low+r[i].close)/3.0;
      pv+=tp*wt;w+=wt;
   }
   return w>0?pv/w:0.0;
}

bool TZ47_BuildMomentumPullback(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;if(a<=0||ArraySize(r)<100)return false;
   int mx=MathMin(MathMax(12,MomentumLookbackBars),ArraySize(r)-8);
   double rmin=MathMin(MomentumRetraceMin,MomentumRetraceMax);
   double rmax=MathMax(MomentumRetraceMin,MomentumRetraceMax);
   for(int br=4;br<=mx;br++)
   {
      int bp=-1;double bos=0.0;
      if(!OlderPivot(r,br+2,MathMin(br+35,ArraySize(r)-3),buy,bp,bos))continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);
      if(!broke||!StrongDisp(r,br,a,MomentumMinDisplacementATR,buy))continue;

      int ap=-1;double anchor=0.0;
      if(!OlderPivot(r,br+2,MathMin(br+45,ArraySize(r)-3),!buy,ap,anchor)||ap<=br)continue;
      double imp=buy?r[br].high:r[br].low;
      for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
      double d=MathAbs(imp-anchor);if(d<a*0.75)continue;

      double vl,vh;
      if(buy){vl=imp-d*rmax;vh=imp-d*rmin;}
      else{vl=imp+d*rmin;vh=imp+d*rmax;}
      if(vl>vh){double x=vl;vl=vh;vh=x;}

      int pi=-1;double pl=0.0,ph=0.0,el=0.0,eh=0.0;string pt="";
      if(!FindFreshPD(r,buy,ap,br,vl,vh,pi,pl,ph,pt,el,eh))continue;

      sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=false;
      sig.anchor_idx=ap;sig.break_idx=br;sig.pd_idx=pi;
      sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=imp;
      sig.ote_low=vl;sig.ote_high=vh;sig.pd_low=pl;sig.pd_high=ph;
      sig.entry_low=el;sig.entry_high=eh;sig.pd_type="MOM-"+pt;
      return true;
   }
   return false;
}

bool TZ47_BuildVWAPReclaim(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;if(a<=0||ArraySize(r)<VWAPLookbackBars+50)return false;
   int half=MathMax(20,VWAPLookbackBars/2);
   double recent=TZ47_VWAP(r,1,VWAPLookbackBars);
   double older=TZ47_VWAP(r,1+half,VWAPLookbackBars);
   if(recent<=0||older<=0)return false;
   if(buy&&recent<=older)return false;
   if(!buy&&recent>=older)return false;

   double band=MathMax(_Point*5.0,a*VWAPBandATR),vl=recent-band,vh=recent+band;
   int mx=MathMin(24,ArraySize(r)-8);
   for(int br=3;br<=mx;br++)
   {
      int bp=-1;double bos=0.0;
      if(!OlderPivot(r,br+2,MathMin(br+35,ArraySize(r)-3),buy,bp,bos))continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);
      if(!broke||!StrongDisp(r,br,a,VWAPMinDisplacementATR,buy))continue;

      int ap=-1;double anchor=0.0;
      if(!OlderPivot(r,br+2,MathMin(br+45,ArraySize(r)-3),!buy,ap,anchor)||ap<=br)continue;
      int pi=-1;double pl=0.0,ph=0.0,el=0.0,eh=0.0;string pt="";
      if(!FindFreshPD(r,buy,ap,br,vl,vh,pi,pl,ph,pt,el,eh))continue;

      sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=false;
      sig.anchor_idx=ap;sig.break_idx=br;sig.pd_idx=pi;
      sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=buy?r[br].high:r[br].low;
      sig.ote_low=vl;sig.ote_high=vh;sig.pd_low=pl;sig.pd_high=ph;
      sig.entry_low=el;sig.entry_high=eh;sig.pd_type="VWAP-"+pt;
      return true;
   }
   return false;
}

int TZ47_DaysInMonth(int year,int mon)
{
   if(mon==2)return ((year%4==0&&year%100!=0)||year%400==0)?29:28;
   if(mon==4||mon==6||mon==9||mon==11)return 30;
   return 31;
}

datetime TZ47_NthSundayUTC(int year,int mon,int nth,int hour)
{
   MqlDateTime d;ZeroMemory(d);d.year=year;d.mon=mon;d.day=1;d.hour=hour;
   datetime t=StructToTime(d);TimeToStruct(t,d);int first=1+((7-d.day_of_week)%7);
   d.day=first+7*(nth-1);return StructToTime(d);
}

datetime TZ47_LastSundayUTC(int year,int mon,int hour)
{
   MqlDateTime d;ZeroMemory(d);d.year=year;d.mon=mon;d.day=TZ47_DaysInMonth(year,mon);d.hour=hour;
   datetime t=StructToTime(d);TimeToStruct(t,d);d.day-=d.day_of_week;return StructToTime(d);
}

bool TZ47_UKSummer(datetime utc)
{
   MqlDateTime d;TimeToStruct(utc,d);
   return utc>=TZ47_LastSundayUTC(d.year,3,1)&&utc<TZ47_LastSundayUTC(d.year,10,1);
}

bool TZ47_USSummer(datetime utc)
{
   MqlDateTime d;TimeToStruct(utc,d);
   return utc>=TZ47_NthSundayUTC(d.year,3,2,7)&&utc<TZ47_NthSundayUTC(d.year,11,1,6);
}

datetime TZ47_ServerToUTC(datetime serverTime)
{
   datetime serverNow=TimeTradeServer();if(serverNow<=0)serverNow=TimeCurrent();
   datetime utcNow=TimeGMT();if(utcNow<=0)return serverTime;
   long offset=(long)(serverNow-utcNow);
   return (datetime)((long)serverTime-offset);
}

datetime TZ47_TodayUTCStart(datetime nowUtc,int hour,int minute)
{
   MqlDateTime d;TimeToStruct(nowUtc,d);d.hour=hour;d.min=minute;d.sec=0;return StructToTime(d);
}

bool TZ47_ORBounds(MqlRates &r[],datetime startUtc,int minutes,double &hi,double &lo)
{
   datetime endUtc=startUtc+minutes*60;bool any=false;hi=-DBL_MAX;lo=DBL_MAX;
   for(int i=1;i<ArraySize(r);i++)
   {
      datetime t=TZ47_ServerToUTC(r[i].time);
      if(t<startUtc||t>=endUtc)continue;
      hi=MathMax(hi,r[i].high);lo=MathMin(lo,r[i].low);any=true;
   }
   return any&&hi>lo&&hi!=-DBL_MAX&&lo!=DBL_MAX;
}

bool TZ47_BuildORBSession(MqlRates &r[],double a,bool buy,datetime startUtc,string name,Signal &sig)
{
   datetime nowUtc=TimeGMT();if(nowUtc<=0||a<=0)return false;
   datetime endUtc=startUtc+OpeningRangeMinutes*60;
   if(nowUtc<endUtc||nowUtc>endUtc+ORBMaxMinutesAfterOpen*60)return false;

   double orHi,orLo;if(!TZ47_ORBounds(r,startUtc,OpeningRangeMinutes,orHi,orLo))return false;
   double boundary=buy?orHi:orLo;
   double breakBuf=MathMax(_Point*5.0,a*0.05);
   int br=-1;
   for(int i=ArraySize(r)-2;i>=3;i--)
   {
      datetime t=TZ47_ServerToUTC(r[i].time);
      if(t<endUtc||t>nowUtc)continue;
      bool broke=buy?(r[i].close>orHi+breakBuf):(r[i].close<orLo-breakBuf);
      if(broke&&StrongDisp(r,i,a,ORBMinBreakATR,buy)){br=i;break;}
   }
   if(br<3)return false;

   int ap=-1;double anchor=0.0;
   if(!OlderPivot(r,br+2,MathMin(br+45,ArraySize(r)-3),!buy,ap,anchor)||ap<=br)return false;
   double band=MathMax(_Point*5.0,a*ORBRetestBandATR),vl=boundary-band,vh=boundary+band;

   int pi=-1;double pl=0.0,ph=0.0,el=0.0,eh=0.0;string pt="";
   if(!FindFreshPD(r,buy,ap,br,vl,vh,pi,pl,ph,pt,el,eh))return false;

   sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=false;
   sig.anchor_idx=ap;sig.break_idx=br;sig.pd_idx=pi;
   sig.anchor_price=anchor;sig.break_level=boundary;sig.impulse_extreme=buy?r[br].high:r[br].low;
   sig.ote_low=vl;sig.ote_high=vh;sig.pd_low=pl;sig.pd_high=ph;
   sig.entry_low=el;sig.entry_high=eh;sig.pd_type=name+"-ORB-"+pt;
   return true;
}

bool TZ47_BuildOpeningRangeRetest(MqlRates &r[],double a,bool buy,Signal &sig)
{
   datetime nowUtc=TimeGMT();if(nowUtc<=0)return false;
   bool ukSummer=TZ47_UKSummer(nowUtc),usSummer=TZ47_USSummer(nowUtc);
   datetime london=TZ47_TodayUTCStart(nowUtc,ukSummer?7:8,0);
   datetime ny=TZ47_TodayUTCStart(nowUtc,usSummer?12:13,20);
   if(TZ47_BuildORBSession(r,a,buy,ny,"NY",sig))return true;
   return TZ47_BuildORBSession(r,a,buy,london,"LONDON",sig);
}

bool TZ47_TryAlternativePrimary(MqlRates &r[],double a,bool buy,string localRegime,bool recentZone,Signal &sig,string &tag,string &model)
{
   if(!EnableAlternativePrimary||g_plan.setup_type!="CONTINUATION"||!recentZone)return false;
   if(TZ47_RegimeAllows("ORB",localRegime)&&TZ47_BuildOpeningRangeRetest(r,a,buy,sig))
   {sig.reentry=false;tag="OR0";model="OPENING_RANGE_RETEST";return true;}
   if(TZ47_RegimeAllows("MOMENTUM",localRegime)&&TZ47_BuildMomentumPullback(r,a,buy,sig))
   {sig.reentry=false;tag="MP0";model="MOMENTUM_PULLBACK";return true;}
   if(TZ47_RegimeAllows("VWAP",localRegime)&&TZ47_BuildVWAPReclaim(r,a,buy,sig))
   {sig.reentry=false;tag="VW0";model="VWAP_PROXY_RECLAIM";return true;}
   return false;
}

bool TZ47_TryAlternativeReentry(MqlRates &r[],double a,bool buy,string localRegime,Signal &sig,string &tag,string &model)
{
   if(TZ47_RegimeAllows("ORB",localRegime)&&TZ47_BuildOpeningRangeRetest(r,a,buy,sig))
   {sig.reentry=true;tag="ORR"+IntegerToString(g_reentries+1);model="OPENING_RANGE_REENTRY";return true;}
   if(TZ47_RegimeAllows("MOMENTUM",localRegime)&&TZ47_BuildMomentumPullback(r,a,buy,sig))
   {sig.reentry=true;tag="MR"+IntegerToString(g_reentries+1);model="MOMENTUM_REENTRY";return true;}
   if(TZ47_RegimeAllows("VWAP",localRegime)&&TZ47_BuildVWAPReclaim(r,a,buy,sig))
   {sig.reentry=true;tag="VR"+IntegerToString(g_reentries+1);model="VWAP_RECLAIM_REENTRY";return true;}
   return false;
}

string TZ47_SetupName(string tag)
{
   if(tag=="P0")return "PRIMARY";
   if(tag=="F0")return "ZONE_FLIP";
   if(tag=="FR1")return "FLIP_REENTRY_1";
   if(tag=="FR2")return "FLIP_REENTRY_2";
   if(tag=="MP0")return "MOMENTUM_PULLBACK";
   if(tag=="VW0")return "VWAP_PROXY_RECLAIM";
   if(tag=="OR0")return "OPENING_RANGE_RETEST";
   if(tag=="B0")return "INSTITUTIONAL_BREAKOUT";
   if(StringFind(tag,"MR")==0)return "MOMENTUM_REENTRY_"+StringSubstr(tag,2);
   if(StringFind(tag,"VR")==0)return "VWAP_RECLAIM_REENTRY_"+StringSubstr(tag,2);
   if(StringFind(tag,"ORR")==0)return "OPENING_RANGE_REENTRY_"+StringSubstr(tag,3);
   if(tag=="L0")return "LIQUIDITY_REVERSAL";
   if(tag=="S0")return "ZONE_SWEEP_CONTINUATION";
   if(tag=="C0")return "CONTINUATION_RESCUE";
   if(tag=="E0")return "ESCAPE_PULLBACK";
   if(StringFind(tag,"R")==0)return "REENTRY_"+StringSubstr(tag,1);
   return tag;
}

bool TZ_ResearchGuards()
{
   if(!IsTester()&&!IsDemo()){TZ_SetGate("SAFETY","NON_DEMO_ACCOUNT");return false;}
   if(!g_plan.valid){TZ_SetGate("PLAN","PLAN_INVALID");return false;}
   if(g_tzCloudLiveBlocked){TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"+g_tzCloudLiveBlockReason);return false;}
   if(!TZ42_NewEntryParitySafe())return false;
   if(g_plan.ea_mode!="DUAL_BRANCH"){TZ_SetGate("AUTHORITY","PLAN_WATCH_ONLY");return false;}
   if(g_tzExecutionAuthority!="HTF_CORE_HANDOFF"&&
      g_tzExecutionAuthority!="HTF_ZONE_CONTACT_HANDOFF"&&
      g_tzExecutionAuthority!="HTF_ZONE_SWEEP_HANDOFF"&&
      g_tzExecutionAuthority!="LIQUIDITY_REVERSAL_HANDOFF")
   {TZ_SetGate("AUTHORITY","NO_CLOUD_EXECUTION_AUTHORITY");return false;}
   MqlTick t;if(!SymbolInfoTick(_Symbol,t)){TZ_SetGate("MARKET","NO_TICK");return false;}double spread=(t.ask-t.bid)/_Point;
   double maxSpread=PaperResearchMode?ResearchMaxSpreadPoints:MaxSpreadPoints;
   if(maxSpread>0&&spread>maxSpread){TZ_SetGate("SPREAD","SPREAD_TOO_HIGH");return false;}
   if(!PaperResearchMode||ResearchUseDailyLossGuard)
   {
      double maxLoss=AccountInfoDouble(ACCOUNT_BALANCE)*ThesisRiskPct/100.0*MaxDailyLossR;
      if(TodayPnL()<=-maxLoss){TZ_SetGate("RISK","DAILY_LOSS_GUARD");return false;}
   }
   TZ_SetGate("MICRO_SEARCH","AUTHORITY_AND_SAFETY_OK");return true;
}

bool TZ_TargetDirectionValid(bool flip,bool buy,double entry)
{
   double t1,t2,t3,run;int n=Targets(flip,buy,t1,t2,t3,run);if(n<=0)return false;
   double minGap=MathMax(_Point*5.0,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));double targets[4]={t1,t2,t3,run};bool any=false;
   for(int i=0;i<4;i++){double x=targets[i];if(x<=0)continue;if(buy&&x>entry+minGap)any=true;if(!buy&&x<entry-minGap)any=true;}return any;
}

bool TZ60_BarTouchesRange(MqlRates &b,double lo,double hi)
{
   double x1=MathMin(lo,hi),x2=MathMax(lo,hi);
   return b.high>=x1&&b.low<=x2;
}

bool TZ60_DirectionalClose(MqlRates &b,bool buy)
{
   return buy?(b.close>b.open):(b.close<b.open);
}

bool TZ60_FindNearestMicroSwing(
   MqlRates &r[],int eventIdx,bool highSide,int maxDepth,int &idx,double &level
)
{
   idx=-1;level=0.0;
   int start=MathMax(eventIdx+1,2);
   int finish=MathMin(eventIdx+MathMax(3,maxDepth),ArraySize(r)-2);
   if(start>finish)return false;

   // Nearest one-bar INTERNAL M1 swing. Zone context does the heavy filtering;
   // the entry engine must not quietly promote this back to a 5-bar HTF fractal.
   for(int i=start;i<=finish;i++)
   {
      bool pivot=highSide
         ?(r[i].high>r[i-1].high && r[i].high>=r[i+1].high)
         :(r[i].low<r[i-1].low && r[i].low<=r[i+1].low);
      if(pivot){idx=i;level=highSide?r[i].high:r[i].low;return true;}
   }

   // One-way approach fallback: the nearest three pre-event candles define the
   // protected micro structure. This preserves a usable micro level in clean drives.
   int fallbackEnd=MathMin(eventIdx+3,finish);
   idx=start;level=highSide?r[start].high:r[start].low;
   for(int i=start+1;i<=fallbackEnd;i++)
   {
      if(highSide && r[i].high>level){idx=i;level=r[i].high;}
      if(!highSide && r[i].low<level){idx=i;level=r[i].low;}
   }
   return idx>=0;
}

void TZ60_ResetTrace()
{
   g_tzTracePdType="";
   g_tzTraceLiquidityLevel=0.0;g_tzTraceSweepPrice=0.0;g_tzTraceMssLevel=0.0;
   g_tzTracePdLow=0.0;g_tzTracePdHigh=0.0;
   g_tzTraceContactTs=0;g_tzTraceSweepTs=0;g_tzTraceMssBreakTs=0;g_tzTracePdTs=0;g_tzTracePullbackTs=0;g_tzTraceConfirmTs=0;
   g_tzTraceReconstructedPreHandoff=false;
}

void TZ60_SetTrace(
   double liquidity,double sweep,datetime sweepTs,double mss,datetime mssTs,
   string pdType,double pdLo,double pdHi,datetime pdTs,datetime pullbackTs,datetime confirmTs
)
{
   g_tzTraceLiquidityLevel=liquidity;g_tzTraceSweepPrice=sweep;g_tzTraceSweepTs=sweepTs;
   g_tzTraceMssLevel=mss;g_tzTraceMssBreakTs=mssTs;g_tzTracePdType=pdType;
   g_tzTracePdLow=pdLo;g_tzTracePdHigh=pdHi;g_tzTracePdTs=pdTs;
   g_tzTracePullbackTs=pullbackTs;g_tzTraceConfirmTs=confirmTs;
   g_tzTraceReconstructedPreHandoff=(g_tzExecutionHandoffTs>0&&sweepTs>0&&sweepTs<g_tzExecutionHandoffTs);
}

bool TZ60_FindAnyCausalPD(
   MqlRates &r[],bool buy,int sweepIdx,int breakIdx,
   int &pdIdx,double &pdLo,double &pdHi,string &pdType
)
{
   pdIdx=-1;pdLo=0.0;pdHi=0.0;pdType="";

   // FVG created by/on the MSS displacement leg. It does NOT have to overlap the
   // HTF zone; the sweep already proved the institutional location.
   if(EnableFVG)
   {
      for(int i=breakIdx;i>=3;i--)
      {
         if(i+1>=ArraySize(r)||i-1<1)continue;
         if(buy&&r[i+1].high<r[i-1].low)
         {pdIdx=i;pdLo=r[i+1].high;pdHi=r[i-1].low;pdType="FVG";return true;}
         if(!buy&&r[i+1].low>r[i-1].high)
         {pdIdx=i;pdLo=r[i-1].high;pdHi=r[i+1].low;pdType="FVG";return true;}
      }
   }

   // Last opposing candle before the MSS break. Use the rejection side of the
   // candle (wick included), not body-only geometry which was too narrow.
   if(EnableOrderBlock)
   {
      int last=MathMin(sweepIdx-1,breakIdx+8);
      for(int i=breakIdx+1;i<=last;i++)
      {
         bool opposing=buy?(r[i].close<r[i].open):(r[i].close>r[i].open);
         if(!opposing)continue;
         if(buy){pdLo=r[i].low;pdHi=r[i].open;}
         else {pdLo=r[i].open;pdHi=r[i].high;}
         if(pdLo>pdHi){double x=pdLo;pdLo=pdHi;pdHi=x;}
         pdIdx=i;pdType="OB";return true;
      }
   }
   return false;
}

bool TZ60_FindRetestedCausalPD(
   MqlRates &r[],bool buy,int sweepIdx,int breakIdx,
   int &pdIdx,double &pdLo,double &pdHi,string &pdType,int &pullbackIdx
)
{
   pdIdx=-1;pdLo=0.0;pdHi=0.0;pdType="";pullbackIdx=-1;
   int confirmWindow=MathMax(1,SniperConfirmMaxBars);
   int pullbackWindow=MathMax(confirmWindow,SniperPullbackMaxBars);

   if(EnableFVG)
   {
      for(int i=breakIdx;i>=3;i--)
      {
         if(i+1>=ArraySize(r)||i-1<1)continue;
         double lo=0.0,hi=0.0;bool ok=false;
         if(buy&&r[i+1].high<r[i-1].low){lo=r[i+1].high;hi=r[i-1].low;ok=true;}
         if(!buy&&r[i+1].low>r[i-1].high){lo=r[i-1].high;hi=r[i+1].low;ok=true;}
         if(!ok)continue;

         // FVG is fully formed at i-1. A retest must be newer than that.
         int oldest=MathMin(i-2,breakIdx-1);
         oldest=MathMin(oldest,1+confirmWindow);
         for(int pb=1;pb<=oldest;pb++)
         {
            if(!SniperAllowSameBarRetestConfirm&&pb==1)continue;
            if(breakIdx-pb>pullbackWindow)continue;
            if(TZ60_BarTouchesRange(r[pb],lo,hi))
            {pdIdx=i;pdLo=lo;pdHi=hi;pdType="FVG";pullbackIdx=pb;return true;}
         }
      }
   }

   if(EnableOrderBlock)
   {
      int last=MathMin(sweepIdx-1,breakIdx+8);
      for(int i=breakIdx+1;i<=last;i++)
      {
         bool opposing=buy?(r[i].close<r[i].open):(r[i].close>r[i].open);
         if(!opposing)continue;
         double lo=buy?r[i].low:r[i].open;
         double hi=buy?r[i].open:r[i].high;
         if(lo>hi){double x=lo;lo=hi;hi=x;}

         int oldest=MathMin(breakIdx-1,1+confirmWindow);
         for(int pb=1;pb<=oldest;pb++)
         {
            if(!SniperAllowSameBarRetestConfirm&&pb==1)continue;
            if(breakIdx-pb>pullbackWindow)continue;
            if(TZ60_BarTouchesRange(r[pb],lo,hi))
            {pdIdx=i;pdLo=lo;pdHi=hi;pdType="OB";pullbackIdx=pb;return true;}
         }
      }
   }
   return false;
}

bool TZ60_RecentZoneContext(MqlRates &r[],int bars)
{
   int n=MathMin(MathMax(2,bars),ArraySize(r)-2);
   for(int i=1;i<=n;i++)if(TouchZone(r[i]))return true;
   return false;
}

bool TZ62_FindZoneContactBeforeEvent(MqlRates &r[],int eventIdx,int leadBars,int &contactIdx)
{
   contactIdx=-1;
   int start=MathMax(1,eventIdx),end=MathMin(ArraySize(r)-2,eventIdx+MathMax(1,leadBars));
   for(int i=start;i<=end;i++)if(TouchZone(r[i])){contactIdx=i;return true;}
   return false;
}

bool TZ60_BuildEngulfing(MqlRates &r[],bool buy,bool reentry,Signal &sig)
{
   sig.valid=false;if(ArraySize(r)<8)return false;
   if(!TZ60_RecentZoneContext(r,MathMax(SniperEngulfContextBars,SniperConfirmMaxBars+3)))return false;
   if(!TZ60_DirectionalClose(r[1],buy))return false;
   int mx=MathMin(MathMax(1,SniperConfirmMaxBars),ArraySize(r)-3);
   for(int cur=1;cur<=mx;cur++)
   {
      int prev=cur+1;
      bool prevOpp=buy?(r[prev].close<r[prev].open):(r[prev].close>r[prev].open);
      if(!prevOpp||!TZ60_DirectionalClose(r[cur],buy))continue;
      double prevLo=MathMin(r[prev].open,r[prev].close),prevHi=MathMax(r[prev].open,r[prev].close);
      double nowLo=MathMin(r[cur].open,r[cur].close),nowHi=MathMax(r[cur].open,r[cur].close);
      double tol=MathMax(_Point*2.0,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
      if(!(nowLo<=prevLo+tol&&nowHi>=prevHi-tol))continue;
      int contact=-1;if(!TZ62_FindZoneContactBeforeEvent(r,prev,SniperEngulfContextBars,contact))continue;
      sig.valid=true;sig.buy=buy;sig.reentry=reentry;sig.flip=false;
      sig.anchor_idx=prev;sig.break_idx=cur;sig.pd_idx=prev;
      sig.anchor_price=buy?MathMin(r[cur].low,r[prev].low):MathMax(r[cur].high,r[prev].high);
      sig.break_level=buy?prevHi:prevLo;sig.impulse_extreme=buy?r[cur].high:r[cur].low;
      sig.ote_low=prevLo;sig.ote_high=prevHi;sig.pd_low=prevLo;sig.pd_high=prevHi;
      sig.entry_low=nowLo;sig.entry_high=nowHi;sig.pd_type="ZONE_ENGULFING";
      TZ60_SetTrace(0.0,sig.anchor_price,r[prev].time,sig.break_level,r[cur].time,"ENGULFING",prevLo,prevHi,r[prev].time,r[cur].time,r[1].time);
      g_tzTraceContactTs=r[contact].time;return true;
   }
   return false;
}

string TZ60_StageName(int rank)
{
   if(rank<=0)return "M1_SWEEP";
   if(rank==1)return "M1_MICRO_MSS";
   if(rank==2)return "M1_OB_FVG";
   if(rank==3)return "M1_PD_PULLBACK";
   return "M1_DIRECTIONAL_CLOSE";
}

bool TZ60_ScanPrimaryEngine(
   MqlRates &r[],bool buy,bool reentry,bool recentZone,
   Signal &sig,string &model,string &stage
)
{
   sig.valid=false;model="NONE";stage="LOCATION";TZ60_ResetTrace();
   if(!recentZone)return false;

   // Model 2 is independent. An incomplete Model 1 must never block a valid
   // engulfing entry that has recent institutional-zone context.
   if(TZ60_BuildEngulfing(r,buy,reentry,sig))
   {model="ZONE_ENGULFING";stage="READY";return true;}

   int maxSweep=MathMin(SweepWindowBars,ArraySize(r)-12);
   int microDepth=MathMax(6,MathMin(SimpleMicroMSSLookbackBars,60));
   double buf=SweepBufferPoints*_Point;
   int bestRank=0;
   double bestLiquidity=0.0,bestSweep=0.0,bestMss=0.0,bestPdLo=0.0,bestPdHi=0.0;
   datetime bestContactTs=0,bestSweepTs=0,bestMssTs=0,bestPdTs=0,bestPbTs=0;
   string bestPdType="";

   for(int sw=4;sw<=maxSweep;sw++)
   {
      int contact=-1;
      if(!TZ62_FindZoneContactBeforeEvent(r,sw,SniperContactLeadBars,contact))continue;

      // Liquidity is also MICRO M1 structure. A wick through it is enough;
      // the later MSS is the reversal confirmation, so sweep-candle close-back
      // is deliberately NOT a second hidden requirement.
      int li=-1;double liquidity=0.0;
      if(!TZ60_FindNearestMicroSwing(r,sw,!buy,microDepth,li,liquidity))continue;
      bool swept=buy?(r[sw].low<liquidity-buf):(r[sw].high>liquidity+buf);
      if(!swept)continue;

      double sweepPrice=buy?r[sw].low:r[sw].high;
      int rank=1;
      if(rank>bestRank)
      {
         bestRank=rank;bestLiquidity=liquidity;bestSweep=sweepPrice;bestContactTs=r[contact].time;bestSweepTs=r[sw].time;
         bestMss=0.0;bestMssTs=0;bestPdType="";bestPdLo=0.0;bestPdHi=0.0;bestPdTs=0;bestPbTs=0;
      }

      int ms=-1;double mss=0.0;
      if(!TZ60_FindNearestMicroSwing(r,sw,buy,microDepth,ms,mss))continue;

      int br=-1;
      for(int j=sw-1;j>=2;j--)
      {
         bool broke=buy?(r[j].close>mss):(r[j].close<mss);
         if(broke){br=j;break;}
      }
      if(br<2)continue;
      rank=2;
      if(rank>bestRank)
      {
         bestRank=rank;bestLiquidity=liquidity;bestSweep=sweepPrice;bestContactTs=r[contact].time;bestSweepTs=r[sw].time;
         bestMss=mss;bestMssTs=r[br].time;bestPdType="";bestPdLo=0.0;bestPdHi=0.0;bestPdTs=0;bestPbTs=0;
      }

      int api=-1;double apl=0.0,aph=0.0;string apt="";
      if(!TZ60_FindAnyCausalPD(r,buy,sw,br,api,apl,aph,apt))continue;
      rank=3;
      if(rank>bestRank)
      {
         bestRank=rank;bestLiquidity=liquidity;bestSweep=sweepPrice;bestContactTs=r[contact].time;bestSweepTs=r[sw].time;
         bestMss=mss;bestMssTs=r[br].time;bestPdType=apt;bestPdLo=apl;bestPdHi=aph;
         bestPdTs=(api>=0&&api<ArraySize(r)?r[api].time:0);bestPbTs=0;
      }

      int pi=-1,pb=-1;double pl=0.0,ph=0.0;string pt="";
      if(!TZ60_FindRetestedCausalPD(r,buy,sw,br,pi,pl,ph,pt,pb))continue;
      rank=4;
      if(rank>bestRank)
      {
         bestRank=rank;bestLiquidity=liquidity;bestSweep=sweepPrice;bestContactTs=r[contact].time;bestSweepTs=r[sw].time;
         bestMss=mss;bestMssTs=r[br].time;bestPdType=pt;bestPdLo=pl;bestPdHi=ph;
         bestPdTs=(pi>=0&&pi<ArraySize(r)?r[pi].time:0);bestPbTs=r[pb].time;
      }

      // The latest CLOSED M1 candle is the only executable confirmation. This
      // prevents historical-pattern chasing after restart/re-attach. No extra
      // "structureHeld" re-break is imposed: the MSS already occurred.
      if(!TZ60_DirectionalClose(r[1],buy))continue;

      sig.valid=true;sig.buy=buy;sig.reentry=reentry;sig.flip=false;
      sig.anchor_idx=sw;sig.break_idx=br;sig.pd_idx=pi;
      sig.anchor_price=sweepPrice;sig.break_level=mss;
      sig.impulse_extreme=buy?r[br].high:r[br].low;
      sig.ote_low=pl;sig.ote_high=ph;sig.pd_low=pl;sig.pd_high=ph;
      sig.entry_low=MathMin(r[1].open,r[1].close);sig.entry_high=MathMax(r[1].open,r[1].close);
      sig.pd_type="MASTER_SNIPER_PD_"+pt;
      model="MASTER_SNIPER_PD_RETEST";stage="READY";
      TZ60_SetTrace(liquidity,sweepPrice,r[sw].time,mss,r[br].time,pt,pl,ph,
                    (pi>=0&&pi<ArraySize(r)?r[pi].time:0),r[pb].time,r[1].time);
      g_tzTraceContactTs=r[contact].time;return true;
   }

   stage=TZ60_StageName(bestRank);
   TZ60_SetTrace(bestLiquidity,bestSweep,bestSweepTs,bestMss,bestMssTs,bestPdType,
                 bestPdLo,bestPdHi,bestPdTs,bestPbTs,0);
   g_tzTraceContactTs=bestContactTs;
   return false;
}


bool TZ62_FindPostEventMicroShift(MqlRates &r[],bool buy,int eventIdx,int &shiftIdx,double &shiftLevel)
{
   shiftIdx=-1;shiftLevel=0.0;if(eventIdx<2||eventIdx>=ArraySize(r)-2)return false;
   int depth=MathMax(6,MathMin(SimpleMicroMSSLookbackBars,60)),ms=-1;
   if(!TZ60_FindNearestMicroSwing(r,eventIdx,buy,depth,ms,shiftLevel))return false;
   for(int j=eventIdx-1;j>=1;j--){bool broke=buy?(r[j].close>shiftLevel):(r[j].close<shiftLevel);if(broke){shiftIdx=j;return true;}}
   return false;
}

bool TZ62_UniversalM1ShiftReady(MqlRates &r[],bool buy,Signal &sig,string &reason,int &shiftIdx,double &shiftLevel)
{
   shiftIdx=-1;shiftLevel=0.0;
   if(sig.pd_type=="ZONE_ENGULFING")
   {
      if(!TZ62_FindPostEventMicroShift(r,buy,sig.anchor_idx,shiftIdx,shiftLevel)){reason="ENGULFING_WAITING_FOR_M1_MICRO_STRUCTURE_SHIFT";return false;}
      sig.break_idx=shiftIdx;sig.break_level=shiftLevel;g_tzTraceMssLevel=shiftLevel;g_tzTraceMssBreakTs=r[shiftIdx].time;
      reason="ENGULFING_M1_MICRO_STRUCTURE_SHIFT_CONFIRMED";return true;
   }
   if(sig.break_idx>=1&&sig.break_idx<ArraySize(r)&&sig.break_level>0)
   {
      bool crossed=buy?(r[sig.break_idx].close>sig.break_level):(r[sig.break_idx].close<sig.break_level);
      if(crossed){shiftIdx=sig.break_idx;shiftLevel=sig.break_level;if(g_tzTraceMssLevel<=0)g_tzTraceMssLevel=shiftLevel;if(g_tzTraceMssBreakTs<=0)g_tzTraceMssBreakTs=r[shiftIdx].time;reason="M1_MICRO_STRUCTURE_SHIFT_CONFIRMED";return true;}
   }
   int eventIdx=MathMax(2,sig.anchor_idx);
   if(!TZ62_FindPostEventMicroShift(r,buy,eventIdx,shiftIdx,shiftLevel)){reason="WAITING_FOR_M1_MICRO_STRUCTURE_SHIFT";return false;}
   sig.break_idx=shiftIdx;sig.break_level=shiftLevel;g_tzTraceMssLevel=shiftLevel;g_tzTraceMssBreakTs=r[shiftIdx].time;
   reason="M1_MICRO_STRUCTURE_SHIFT_CONFIRMED";return true;
}

bool TZ62_BuildDisplacementContinuation(MqlRates &r[],double a,bool buy,Signal &sig,string &stage)
{
   sig.valid=false;stage="CONTINUATION_M1_SHIFT";if(g_lastTradeBar<=0||a<=0)return false;
   int mx=MathMin(MathMax(24,BreakoutLookbackBars),ArraySize(r)-16),depth=MathMax(6,MathMin(SimpleMicroMSSLookbackBars,60));
   bool sawShift=false,sawPd=false,sawRetest=false;
   for(int br=3;br<=mx;br++)
   {
      if(r[br].time<=g_lastTradeBar)continue;
      int ms=-1;double bos=0.0;if(!TZ60_FindNearestMicroSwing(r,br,buy,depth,ms,bos))continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);
      if(!broke||!StrongDisp(r,br,a,MathMax(0.45,BreakoutMinBreakATR),buy))continue;sawShift=true;
      int anchorIdx=MathMin(ArraySize(r)-2,br+MathMax(8,depth/2));
      int api=-1;double apl=0.0,aph=0.0;string apt="";
      if(!TZ60_FindAnyCausalPD(r,buy,anchorIdx,br,api,apl,aph,apt))continue;sawPd=true;
      int pi=-1,pb=-1;double pl=0.0,ph=0.0;string pt="";
      if(!TZ60_FindRetestedCausalPD(r,buy,anchorIdx,br,pi,pl,ph,pt,pb))continue;sawRetest=true;
      int shift=-1;double shiftLevel=0.0;if(!TZ62_FindPostEventMicroShift(r,buy,pb,shift,shiftLevel))continue;
      if(!TZ60_DirectionalClose(r[1],buy))continue;
      sig.valid=true;sig.buy=buy;sig.reentry=true;sig.flip=false;sig.anchor_idx=pb;sig.break_idx=shift;sig.pd_idx=pi;
      sig.anchor_price=buy?r[pb].low:r[pb].high;sig.break_level=shiftLevel;sig.impulse_extreme=buy?r[br].high:r[br].low;
      sig.ote_low=pl;sig.ote_high=ph;sig.pd_low=pl;sig.pd_high=ph;sig.entry_low=MathMin(r[1].open,r[1].close);sig.entry_high=MathMax(r[1].open,r[1].close);sig.pd_type="CONTINUATION_PD_"+pt;
      TZ60_SetTrace(bos,r[br].close,r[br].time,shiftLevel,r[shift].time,pt,pl,ph,(pi>=0&&pi<ArraySize(r)?r[pi].time:0),r[pb].time,r[1].time);
      stage="READY";return true;
   }
   if(!sawShift)stage="CONTINUATION_M1_SHIFT";else if(!sawPd)stage="CONTINUATION_OB_FVG";else if(!sawRetest)stage="CONTINUATION_PD_PULLBACK";else stage="CONTINUATION_POST_RETEST_M1_SHIFT";
   return false;
}

bool TZ62_ConfirmBoundaryBreakout(MqlRates &r[],double a,bool buy,double rangeLo,double rangeHi,double boundary,int br,string source,Signal &sig,string &stage)
{
   sig.valid=false;if(br<3||a<=0)return false;
   double band=MathMax(_Point*5.0,a*BreakoutBoundaryBandATR),breakBuf=MathMax(_Point*5.0,a*0.05);
   bool broke=buy?(r[br].close>boundary+breakBuf):(r[br].close<boundary-breakBuf);
   if(!broke||!StrongDisp(r,br,a,BreakoutMinBreakATR,buy)){stage="BREAKOUT_DISPLACEMENT";return false;}
   bool accepted=false,failed=false;int accOldest=MathMax(1,br-MathMax(1,BreakoutAcceptanceBars));
   for(int j=br-1;j>=accOldest;j--){bool rejectedBack=buy?(r[j].close<boundary-band):(r[j].close>boundary+band);if(rejectedBack){failed=true;break;}bool held=buy?(r[j].close>=boundary):(r[j].close<=boundary);if(held)accepted=true;}
   if(failed||!accepted){stage="BREAKOUT_ACCEPTANCE";return false;}
   int pb=-1,pi=-1;double pl=boundary-band,ph=boundary+band;string pt="BOUNDARY";
   int cpi=-1,cpb=-1;double clo=0.0,chi=0.0;string ctype="";int anchorIdx=MathMin(ArraySize(r)-2,br+MathMax(8,BreakoutBalanceBars));
   if(TZ60_FindRetestedCausalPD(r,buy,anchorIdx,br,cpi,clo,chi,ctype,cpb)){bool overlaps=(chi>=boundary-band&&clo<=boundary+band);if(overlaps&&cpb>=2){pi=cpi;pb=cpb;pl=clo;ph=chi;pt=ctype;}}
   if(pb<2)
   {
      int newest=MathMax(2,br-MathMax(2,BreakoutRetestMaxBars));
      for(int j=2;j<=br-1;j++){if(j<newest)continue;if(!TZ60_BarTouchesRange(r[j],boundary-band,boundary+band))continue;bool held=buy?(r[j].close>=boundary-band):(r[j].close<=boundary+band);if(!held)continue;pb=j;pi=j;pl=boundary-band;ph=boundary+band;pt="BOUNDARY";break;}
   }
   if(pb<2){stage="BREAKOUT_RETEST";return false;}
   int shift=-1;double shiftLevel=0.0;if(!TZ62_FindPostEventMicroShift(r,buy,pb,shift,shiftLevel)){stage="BREAKOUT_M1_MICRO_SHIFT";return false;}
   if(!TZ60_DirectionalClose(r[1],buy)){stage="BREAKOUT_DIRECTIONAL_CLOSE";return false;}
   if(MathAbs(r[1].close-boundary)>a*BreakoutMaxChaseATR){stage="BREAKOUT_NO_CHASE";return false;}
   sig.valid=true;sig.buy=buy;sig.reentry=(g_primaryEntries>0);sig.flip=false;sig.anchor_idx=pb;sig.break_idx=shift;sig.pd_idx=pi;
   sig.anchor_price=buy?r[pb].low:r[pb].high;sig.break_level=shiftLevel;sig.impulse_extreme=buy?r[br].high:r[br].low;
   sig.ote_low=pl;sig.ote_high=ph;sig.pd_low=pl;sig.pd_high=ph;sig.entry_low=MathMin(r[1].open,r[1].close);sig.entry_high=MathMax(r[1].open,r[1].close);sig.pd_type="BREAKOUT_"+source+"_"+pt;
   TZ60_SetTrace(boundary,r[br].close,r[br].time,shiftLevel,r[shift].time,pt,pl,ph,(pi>=0&&pi<ArraySize(r)?r[pi].time:0),r[pb].time,r[1].time);stage="READY";return true;
}

bool TZ62_TryOpeningRangeBreakout(MqlRates &r[],double a,bool buy,datetime startUtc,string name,Signal &sig,string &stage)
{
   datetime nowUtc=TimeGMT();if(nowUtc<=0)return false;datetime endUtc=startUtc+OpeningRangeMinutes*60;
   if(nowUtc<endUtc||nowUtc>endUtc+ORBMaxMinutesAfterOpen*60)return false;
   double hi=0.0,lo=0.0;if(!TZ47_ORBounds(r,startUtc,OpeningRangeMinutes,hi,lo))return false;double boundary=buy?hi:lo;
   int mx=MathMin(MathMax(12,BreakoutLookbackBars),ArraySize(r)-12);
   for(int br=3;br<=mx;br++){datetime t=TZ47_ServerToUTC(r[br].time);if(t<endUtc||t>nowUtc)continue;double bb=MathMax(_Point*5.0,a*0.05);bool broke=buy?(r[br].close>boundary+bb):(r[br].close<boundary-bb);if(!broke)continue;if(TZ62_ConfirmBoundaryBreakout(r,a,buy,lo,hi,boundary,br,name+"_OR",sig,stage))return true;}
   return false;
}

bool TZ62_BuildCompressionBreakout(MqlRates &r[],double a,bool buy,Signal &sig,string &stage)
{
   if(a<=0)return false;int mx=MathMin(MathMax(24,BreakoutLookbackBars),ArraySize(r)-BreakoutBalanceBars-4);
   for(int br=3;br<=mx;br++)
   {
      int first=br+1,last=MathMin(ArraySize(r)-2,br+MathMax(6,BreakoutBalanceBars));if(last-first<5)continue;
      double hi=-DBL_MAX,lo=DBL_MAX,path=0.0;
      for(int i=first;i<=last;i++){hi=MathMax(hi,r[i].high);lo=MathMin(lo,r[i].low);if(i<last)path+=MathAbs(r[i].close-r[i+1].close);}
      double width=hi-lo;if(width<a*0.50||width>a*BreakoutCompressionMaxATR)continue;
      double net=MathAbs(r[first].close-r[last].close),eff=path>0?net/path:1.0;if(eff>0.45)continue;
      double boundary=buy?hi:lo,bb=MathMax(_Point*5.0,a*0.05);bool broke=buy?(r[br].close>boundary+bb):(r[br].close<boundary-bb);if(!broke)continue;
      if(TZ62_ConfirmBoundaryBreakout(r,a,buy,lo,hi,boundary,br,"M1_BALANCE",sig,stage))return true;
   }
   if(stage=="")stage="BREAKOUT_BOUNDARY";return false;
}

bool TZ62_BuildInstitutionalBreakout(MqlRates &r[],double a,bool buy,string localRegime,Signal &sig,string &stage)
{
   sig.valid=false;stage="BREAKOUT_BOUNDARY";if(!EnableInstitutionalBreakoutModel||!g_tzAllowBreakout)return false;
   bool cloudOk=(g_tzCloudRegime=="TESTER"||g_tzCloudRegime=="COMPRESSION"||g_tzCloudRegime=="RANGE"||g_tzCloudRegime=="TREND"||g_tzCloudRegime=="EXPANSION");
   bool localOk=(localRegime=="COMPRESSION"||localRegime=="RANGE"||localRegime=="TREND"||localRegime=="EXPANSION");
   if(!cloudOk||!localOk){stage="BREAKOUT_REGIME";return false;}
   datetime nowUtc=TimeGMT();
   if(nowUtc>0){bool ukSummer=TZ47_UKSummer(nowUtc),usSummer=TZ47_USSummer(nowUtc);datetime ny=TZ47_TodayUTCStart(nowUtc,usSummer?12:13,20),london=TZ47_TodayUTCStart(nowUtc,ukSummer?7:8,0);if(TZ62_TryOpeningRangeBreakout(r,a,buy,ny,"NY",sig,stage))return true;if(TZ62_TryOpeningRangeBreakout(r,a,buy,london,"LONDON",sig,stage))return true;}
   return TZ62_BuildCompressionBreakout(r,a,buy,sig,stage);
}

void TZ_ShallowValue(bool buy,double anchor,double impulse,double &lo,double &hi)
{
   double d=MathAbs(impulse-anchor);
   double mn=MathMin(ResearchEscapeRetraceMin,ResearchEscapeRetraceMax),mx=MathMax(ResearchEscapeRetraceMin,ResearchEscapeRetraceMax);
   if(buy){lo=impulse-d*mx;hi=impulse-d*mn;}
   else{lo=impulse+d*mn;hi=impulse+d*mx;}
   if(lo>hi){double x=lo;lo=hi;hi=x;}
}

bool TZ_BuildEscapePullback(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;if(a<=0)return false;
   int mx=MathMin(MathMax(12,ResearchEscapeLookbackBars),ArraySize(r)-8);
   for(int zi=4;zi<=mx;zi++)
   {
      if(!TouchZone(r[zi]))continue;
      int bp=-1;double bos=0;
      if(!OlderPivot(r,zi+2,SwingLookback,buy,bp,bos))continue;
      int br=-1;
      for(int j=zi-1;j>=2;j--)
      {
         bool broke=buy?(r[j].close>bos):(r[j].close<bos);
         if(broke&&StrongDisp(r,j,a,ResearchEscapeDisplacementATR,buy)){br=j;break;}
      }
      if(br<2)continue;
      double anchor=buy?r[zi].low:r[zi].high,imp=buy?r[br].high:r[br].low;
      for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
      if(MathAbs(imp-anchor)<a*0.75)continue;
      double vl,vh;TZ_ShallowValue(buy,anchor,imp,vl,vh);
      int pi;double pl,ph,el,eh;string pt;
      if(!FindFreshPD(r,buy,zi,br,vl,vh,pi,pl,ph,pt,el,eh))continue;
      sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=false;sig.anchor_idx=zi;sig.break_idx=br;sig.pd_idx=pi;
      sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=imp;sig.ote_low=vl;sig.ote_high=vh;
      sig.pd_low=pl;sig.pd_high=ph;sig.entry_low=el;sig.entry_high=eh;sig.pd_type="ESC-"+pt;return true;
   }
   return false;
}

bool TZ_EntryAtEscapeValue(bool buy,double price,Signal &s,double a)
{
   if(price>=s.entry_low&&price<=s.entry_high)return true;
   double d=MathMin(MathAbs(price-s.entry_low),MathAbs(price-s.entry_high));
   return d<=a*ResearchEscapeMaxChaseATR;
}

bool TZ31_BuildPostHandoffContinuation(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;
   if(g_tzExecutionHandoffTs<=0)return false;
   int mx=MathMin(MathMax(ReentryLookbackBars,ResearchEscapeLookbackBars),ArraySize(r)-8);
   for(int br=3;br<=mx;br++)
   {
      if(r[br].time<g_tzExecutionHandoffTs)continue;
      int bp;double bos;
      if(!OlderPivot(r,br+2,SwingLookback,buy,bp,bos))continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);
      if(!broke||!StrongDisp(r,br,a,MathMax(0.60,ResearchEscapeDisplacementATR),buy))continue;

      int ap;double anchor;
      if(!OlderPivot(r,br+2,SwingLookback,!buy,ap,anchor)||ap<=br)continue;
      double imp=buy?r[br].high:r[br].low;
      for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
      if(MathAbs(imp-anchor)<a*0.75)continue;

      double ol,oh;OTE(buy,anchor,imp,ol,oh);
      int pi;double pl,ph,el,eh;string pt;
      if(!FindFreshPD(r,buy,ap,br,ol,oh,pi,pl,ph,pt,el,eh))continue;

      sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=false;
      sig.anchor_idx=ap;sig.break_idx=br;sig.pd_idx=pi;
      sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=imp;
      sig.ote_low=ol;sig.ote_high=oh;sig.pd_low=pl;sig.pd_high=ph;
      sig.entry_low=el;sig.entry_high=eh;sig.pd_type="HOF-"+pt;
      return true;
   }
   return false;
}

string TZ31_DiagnosePostHandoff(MqlRates &r[],double a,bool buy)
{
   if(g_tzExecutionHandoffTs<=0)return "HANDOFF_TIME";
   bool sawBreak=false,sawDisp=false;
   int mx=MathMin(MathMax(ReentryLookbackBars,ResearchEscapeLookbackBars),ArraySize(r)-8);
   for(int br=3;br<=mx;br++)
   {
      if(r[br].time<g_tzExecutionHandoffTs)continue;
      int bp;double bos;
      if(!OlderPivot(r,br+2,SwingLookback,buy,bp,bos))continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);
      if(!broke)continue;
      sawBreak=true;
      if(StrongDisp(r,br,a,MathMax(0.60,ResearchEscapeDisplacementATR),buy)){sawDisp=true;break;}
   }
   if(!sawBreak)return "MSS_BOS";
   if(!sawDisp)return "DISPLACEMENT";
   return "VALUE_PD_ARRAY";
}

string TZ_DiagnosePrimaryStage(MqlRates &r[],double a,bool buy,bool recentZone)
{
   if(!recentZone)return "LOCATION";
   int maxSweep=MathMin(SweepWindowBars,ArraySize(r)-8);double buf=SweepBufferPoints*_Point;
   bool sawSweep=false,sawBreak=false,sawDisp=false;
   for(int sw=6;sw<=maxSweep;sw++)
   {
      int li=-1,ms=-1;double liquidity=0,mss=0;
      if(!OlderPivot(r,sw+2,SwingLookback,!buy,li,liquidity))continue;
      if(!OlderPivot(r,sw+2,SwingLookback,buy,ms,mss))continue;
      bool swept=buy?(r[sw].low<liquidity-buf&&r[sw].close>liquidity):(r[sw].high>liquidity+buf&&r[sw].close<liquidity);
      if(!swept||!TouchZone(r[sw]))continue;sawSweep=true;
      for(int j=sw-1;j>=3;j--)
      {
         bool broke=buy?(r[j].close>mss):(r[j].close<mss);
         if(!broke)continue;sawBreak=true;
         if(StrongDisp(r,j,a,MathMax(MinDisplacementATR,g_plan.min_disp_atr),buy)){sawDisp=true;break;}
      }
      if(sawDisp)break;
   }
   if(!sawSweep)return "SWEEP";
   if(!sawBreak)return "MSS_BOS";
   if(!sawDisp)return "DISPLACEMENT";
   return "VALUE_PD_ARRAY";
}



bool TZ39_ProfessionalValueReactionReady(
   MqlRates &r[],double a,bool buy,Signal &s,double market,
   int lookbackBars,double minBodyATR,double maxChaseATR,string prefix,
   string &reason,int &reactionIdx)
{
   reactionIdx=-1;
   if(a<=0||s.break_idx<2||s.pd_idx<2)
   {
      reason=prefix+"_SIGNAL_INVALID";
      return false;
   }

   // Only bars that closed AFTER both the structure break and the PD-array
   // construction may confirm the entry. This prevents the displacement candle
   // itself, or an older OB/FVG candle, from being misread as entry confirmation.
   int newestAfterFormation=s.break_idx-1;
   // FVG is only fully formed when the newer third candle (pd_idx-1) closes.
   // Confirmation must therefore come from a later CLOSED bar, never that
   // formation candle itself. An OB predates displacement, so the break close
   // is its activation event and break_idx-1 is already strictly later.
   if(StringFind(s.pd_type,"FVG")>=0)
      newestAfterFormation=MathMin(newestAfterFormation,s.pd_idx-2);
   newestAfterFormation=MathMin(newestAfterFormation,ArraySize(r)-3);
   if(newestAfterFormation<1)
   {
      reason=prefix+"_WAITING_FOR_CLOSED_M1_VALUE_REACTION";
      return false;
   }

   // Once closed M1 accepts through the wrong side of the PD array, that value
   // array is dead for a new order. Do not let a later tick revive it.
   for(int j=newestAfterFormation;j>=1;j--)
   {
      if(buy&&r[j].close<s.pd_low){reason=prefix+"_PD_ARRAY_ACCEPTED_INVALIDATION";return false;}
      if(!buy&&r[j].close>s.pd_high){reason=prefix+"_PD_ARRAY_ACCEPTED_INVALIDATION";return false;}
   }

   int mx=MathMin(MathMax(1,lookbackBars),newestAfterFormation);
   for(int i=1;i<=mx;i++)
   {
      bool touched=(r[i].high>=s.entry_low&&r[i].low<=s.entry_high);
      if(!touched)continue;
      double body=MathAbs(r[i].close-r[i].open);
      bool directional=buy?(r[i].close>r[i].open):(r[i].close<r[i].open);
      bool rejected=buy?(r[i].close>=s.entry_high):(r[i].close<=s.entry_low);
      bool microBreak=buy?(r[i].close>r[i+1].high):(r[i].close<r[i+1].low);
      if(directional&&rejected&&microBreak&&body>=a*minBodyATR)
      {
         reactionIdx=i;
         break;
      }
   }
   if(reactionIdx<0)
   {
      reason=prefix+"_WAITING_FOR_CLOSED_M1_VALUE_REACTION";
      return false;
   }

   // Confirmation never grants chase permission. Market must still be close to
   // the confirmed overlap and must not have pushed materially through its wrong side.
   double chase=0.0;
   if(buy&&market>s.entry_high)chase=market-s.entry_high;
   if(!buy&&market<s.entry_low)chase=s.entry_low-market;
   if(chase>a*maxChaseATR)
   {
      reason=prefix+"_VALUE_REACTION_CONFIRMED_BUT_CHASED";
      return false;
   }
   if(buy&&market<s.entry_low-a*maxChaseATR)
   {
      reason=prefix+"_VALUE_REACTION_LOST_BELOW_ARRAY";
      return false;
   }
   if(!buy&&market>s.entry_high+a*maxChaseATR)
   {
      reason=prefix+"_VALUE_REACTION_LOST_ABOVE_ARRAY";
      return false;
   }

   reason=prefix+"_CLOSED_M1_VALUE_REACTION_CONFIRMED";
   return true;
}

bool TZ39_InitialEntryReady(MqlRates &r[],double a,bool buy,Signal &s,double market,string tag,string &reason,int &reactionIdx)
{
   double maxChase=ProfessionalEntryReactionMaxChaseATR;
   if(tag=="E0")maxChase=MathMin(maxChase,ResearchEscapeMaxChaseATR);
   return TZ39_ProfessionalValueReactionReady(
      r,a,buy,s,market,ProfessionalEntryValueReactionLookbackBars,
      ProfessionalEntryReactionMinBodyATR,maxChase,tag,reason,reactionIdx);
}

bool TZ36_PostHandoffEntryReady(MqlRates &r[],double a,bool buy,Signal &s,double market,string &reason,int &reactionIdx)
{
   reactionIdx=-1;
   if(s.break_idx<3||s.break_idx>PostHandoffSignalMaxAgeBars)
   {
      reason="POST_HANDOFF_SIGNAL_STALE";
      return false;
   }
   int lookback=MathMin(PostHandoffValueReactionLookbackBars,ProfessionalEntryValueReactionLookbackBars);
   double minBody=MathMax(PostHandoffReactionMinBodyATR,ProfessionalEntryReactionMinBodyATR);
   double maxChase=MathMin(PostHandoffReactionMaxChaseATR,ProfessionalEntryReactionMaxChaseATR);
   return TZ39_ProfessionalValueReactionReady(
      r,a,buy,s,market,lookback,minBody,maxChase,"POST_HANDOFF",reason,reactionIdx);
}

bool TZ36_NearestDirectionalTarget(bool flip,bool buy,double entry,double &target)
{
   target=0.0;
   double t1,t2,t3,run;
   int n=Targets(flip,buy,t1,t2,t3,run);
   if(n<=0)return false;
   double xs[4]={t1,t2,t3,run};
   double minGap=MathMax(_Point*5.0,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
   for(int i=0;i<4;i++)
   {
      double x=xs[i];if(x<=0)continue;
      if(buy&&x>entry+minGap&&(target<=0||x<target))target=x;
      if(!buy&&x<entry-minGap&&(target<=0||x>target))target=x;
   }
   return target>0;
}

bool TZ36_TargetAlreadyTradedSinceHandoff(MqlRates &r[],bool buy,double target)
{
   if(g_tzExecutionHandoffTs<=0||target<=0)return false;
   for(int i=1;i<ArraySize(r);i++)
   {
      if(r[i].time<g_tzExecutionHandoffTs)break;
      if(buy&&r[i].high>=target)return true;
      if(!buy&&r[i].low<=target)return true;
   }
   return false;
}

bool TZ36_MinRRValid(double entry,double sl,double target,double &rr,double &required)
{
   rr=0.0;
   required=MathMax(1.0,g_plan.min_rr);
   double risk=MathAbs(entry-sl);
   double reward=MathAbs(target-entry);
   if(risk<=_Point||reward<=_Point)return false;
   rr=reward/risk;
   return rr+1e-9>=required;
}

bool TZ35_ReentryEntryReady(MqlRates &r[],double a,bool buy,Signal &s,double market,string &reason,int &reactionIdx)
{
   reactionIdx=-1;
   if(s.break_idx<3||s.break_idx>ReentrySignalMaxAgeBars)
   {
      reason="REENTRY_SIGNAL_STALE";
      return false;
   }
   int lookback=MathMin(ReentryValueReactionLookbackBars,ProfessionalEntryValueReactionLookbackBars);
   double minBody=MathMax(ReentryReactionMinBodyATR,ProfessionalEntryReactionMinBodyATR);
   double maxChase=MathMin(ReentryReactionMaxChaseATR,ProfessionalEntryReactionMaxChaseATR);
   return TZ39_ProfessionalValueReactionReady(
      r,a,buy,s,market,lookback,minBody,maxChase,"REENTRY",reason,reactionIdx);
}

bool TZ40_BreakerFlipReady(
   MqlRates &r[],double a,bool buy,Signal &s,double market,string tag,
   string &reason,int &reactionIdx)
{
   reactionIdx=-1;
   if(StringFind(s.pd_type,"FLIP-BREAKER-")<0)return false;
   if(a<=0||s.anchor_idx<2||s.break_idx<1||s.break_idx+1>=ArraySize(r))
   {
      reason="FLIP_"+tag+"_BREAKER_SIGNAL_INVALID";
      return false;
   }
   if(r[s.anchor_idx].time<g_tzFlipAcceptedAt||r[s.break_idx].time<g_tzFlipAcceptedAt)
   {
      reason="FLIP_"+tag+"_BREAKER_PRE_ACCEPTANCE_EVENT";
      return false;
   }

   bool retestTouched=(
      r[s.anchor_idx].high>=s.entry_low &&
      r[s.anchor_idx].low<=s.entry_high
   );
   double body=MathAbs(r[s.break_idx].close-r[s.break_idx].open);
   bool directional=buy
      ?(r[s.break_idx].close>r[s.break_idx].open)
      :(r[s.break_idx].close<r[s.break_idx].open);
   bool rejected=buy
      ?(r[s.break_idx].close>=s.entry_high)
      :(r[s.break_idx].close<=s.entry_low);
   bool microBreak=buy
      ?(r[s.break_idx].close>r[s.break_idx+1].high)
      :(r[s.break_idx].close<r[s.break_idx+1].low);

   if(!(retestTouched&&directional&&rejected&&microBreak&&body>=a*ProfessionalEntryReactionMinBodyATR))
   {
      reason="FLIP_"+tag+"_BREAKER_WAITING_FOR_CLOSED_M1_REACTION";
      return false;
   }

   // The retest + closed break/displacement is the confirmation. Permit entry
   // only while market remains close to that CLOSED confirmation; never chase.
   double confirm=r[s.break_idx].close;
   double chase=buy?MathMax(0.0,market-confirm):MathMax(0.0,confirm-market);
   if(chase>a*ProfessionalEntryReactionMaxChaseATR)
   {
      reason="FLIP_"+tag+"_BREAKER_CONFIRMED_BUT_CHASED";
      return false;
   }
   if(buy&&market<s.entry_low-a*ProfessionalEntryReactionMaxChaseATR)
   {
      reason="FLIP_"+tag+"_BREAKER_REACTION_LOST_BELOW_ARRAY";
      return false;
   }
   if(!buy&&market>s.entry_high+a*ProfessionalEntryReactionMaxChaseATR)
   {
      reason="FLIP_"+tag+"_BREAKER_REACTION_LOST_ABOVE_ARRAY";
      return false;
   }

   reactionIdx=s.break_idx;
   reason="FLIP_"+tag+"_BREAKER_RETEST_MSS_DISPLACEMENT_CONFIRMED";
   return true;
}

bool TZ39_FlipEntryReady(MqlRates &r[],double a,bool buy,Signal &s,double market,string tag,string &reason,int &reactionIdx)
{
   if(StringFind(s.pd_type,"FLIP-BREAKER-")>=0)
   {
      string breakerReason="";
      int breakerIdx=-1;
      if(TZ40_BreakerFlipReady(r,a,buy,s,market,tag,breakerReason,breakerIdx))
      {
         reason=breakerReason;reactionIdx=breakerIdx;return true;
      }
      // If the immediate breaker confirmation is valid structurally but already
      // chased, keep the hard no-chase decision. Otherwise the standard post-
      // formation value-reaction path may still qualify a later controlled retest.
      if(StringFind(breakerReason,"CONFIRMED_BUT_CHASED")>=0)
      {
         reason=breakerReason;reactionIdx=-1;return false;
      }
   }
   return TZ39_ProfessionalValueReactionReady(
      r,a,buy,s,market,ProfessionalEntryValueReactionLookbackBars,
      ProfessionalEntryReactionMinBodyATR,ProfessionalEntryReactionMaxChaseATR,
      "FLIP_"+tag,reason,reactionIdx);
}

void TZ36_SendEntryDecisionAudit(string tag,Signal &s,double entry,double sl,double lots,double a,int reactionIdx,double openTarget,double rr,double rrRequired,bool reactionRequired,MqlRates &r[])
{
   if(IsTester())return;
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   datetime breakTs=(s.break_idx>=0&&s.break_idx<ArraySize(r)?r[s.break_idx].time:0);
   datetime pdTs=(s.pd_idx>=0&&s.pd_idx<ArraySize(r)?r[s.pd_idx].time:0);
   datetime reactionTs=(reactionIdx>=1&&reactionIdx<ArraySize(r)?r[reactionIdx].time:0);
   string setup=TZ47_SetupName(tag);
   string campaign=g_plan.analysis_id+"|"+g_plan.zone_id+"|"+tag;
   string details=StringFormat(
      "{\"campaign_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\",\"direction\":\"%s\","
      "\"authority\":\"%s\",\"candidate_model\":\"%s\",\"pd_type\":\"%s\","
      "\"break_bar_ts\":%I64d,\"pd_bar_ts\":%I64d,\"value_reaction_bar_ts\":%I64d,"
      "\"anchor_price\":%.5f,\"break_level\":%.5f,\"impulse_extreme\":%.5f,"
      "\"ote_low\":%.5f,\"ote_high\":%.5f,\"pd_low\":%.5f,\"pd_high\":%.5f,"
      "\"entry_low\":%.5f,\"entry_high\":%.5f,\"entry_price\":%.5f,\"stop_price\":%.5f,"
      "\"m1_atr\":%.5f,\"lots\":%.4f,\"reentries_before\":%d,"
      "\"risk_model\":\"%s\",\"risk_epoch\":\"%s\",\"risk_context\":\"%s\",\"risk_base\":%.2f,\"grade_risk_pct\":%.4f,\"original_risk_pct\":%.4f,\"flip_risk_pct\":%.4f,\"risk_money\":%.2f,"
      "\"nearest_open_target\":%.5f,\"rr_at_entry\":%.4f,\"min_rr_required\":%.4f,"
      "\"closed_m1_value_reaction_required\":%d,\"closed_m1_value_reaction_confirmed\":%d}",
      TZ_JsonEscape(campaign),TZ_JsonEscape(setup),TZ_JsonEscape(tag),(s.buy?"BUY":"SELL"),
      TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzCandidateModel),TZ_JsonEscape(s.pd_type),
      (long)breakTs,(long)pdTs,(long)reactionTs,
      s.anchor_price,s.break_level,s.impulse_extreme,s.ote_low,s.ote_high,s.pd_low,s.pd_high,
      s.entry_low,s.entry_high,entry,sl,a,lots,g_reentries,
      TZ_JsonEscape(g_tzRiskModel),TZ_JsonEscape(g_tzRiskEpoch),TZ_JsonEscape(g_tzRiskContext),g_tzLastRiskBase,g_tzGradeRiskPct,g_tzOriginalRiskPct,g_tzFlipRiskPct,g_tzLastRiskMoney,
      openTarget,rr,rrRequired,(reactionRequired?1:0),(reactionIdx>=1?1:0));
   string body=StringFormat(
      "{\"ts\":%I64d,\"event\":\"ENTRY_DECISION\",\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"price\":%.5f,\"details\":%s}",
      (long)now,TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),entry,details);
   string response;
   TZ_Post("/mt5/feedback",body,response);
}

bool TZ45_ActiveOwnerMatchesCurrentPlan()
{
   // Owner priority must be decided from the persisted owner mirror, not from
   // mutable runtime execution authority. Accepted-flip arming/evaluation is
   // allowed to clear g_tzExecutionAuthority, so using that variable here makes
   // the owner test self-defeating.
   if(TZ30_OwnerKV("owner_mirror_active")!="1")return false;
   string ownerId=TZ30_OwnerKV("owner_mirror_zone_id");
   string ownerDir=TZ30_OwnerKV("owner_mirror_direction");
   string ownerStatus=TZ30_OwnerKV("owner_mirror_status");
   string ownerAuthority=TZ30_OwnerKV("owner_mirror_authority");
   datetime acquired=(datetime)StringToInteger(TZ30_OwnerKV("owner_mirror_acquired_at"));
   if(ownerId==""||ownerId!=g_plan.zone_id||ownerDir!=g_plan.original_direction||acquired<=0)return false;
   if(ownerStatus!="INTERACTING"&&ownerStatus!="REACTION_CONFIRMED"&&ownerStatus!="OBJECTIVE_IN_PROGRESS")return false;
   if(ownerAuthority!="HTF_CORE_HANDOFF"&&ownerAuthority!="HTF_ZONE_CONTACT_HANDOFF"&&ownerAuthority!="HTF_ZONE_SWEEP_HANDOFF"&&ownerAuthority!="LIQUIDITY_REVERSAL_HANDOFF")return false;
   return true;
}

void Evaluate()
{
   // Capture an accepted invalidation against the OLD plan only when that plan is
   // not a currently acquired non-terminal thesis owner. An active owner has
   // priority over dormant flip/reclaim alternatives until the owner is released.
   if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();

   if(!TZ31_RefreshCloudState(false)){TZ_SetGate("PLAN","PLAN_REFRESH_FAILED");return;}

   bool ownerPriority=TZ45_ActiveOwnerMatchesCurrentPlan();
   if(!ownerPriority)
   {
      // The refreshed Cloud plan may itself be a failed-zone candidate. Capture
      // it only after confirming no active owner owns the current selected plan.
      TZ28_ArmAcceptedFlip();
      if(g_tzFlipPlanStored)
      {
         TZ28_EvaluateAcceptedFlip();
         return;
      }
   }

   // If ownerPriority is true, a stored accepted flip stays persisted for audit
   // and expiry but cannot alter the owner's runtime authority. Normal Cloud
   // plan/safety/parity/M1 guards still decide whether any new entry is permitted.
   if(!TZ_ResearchGuards())return;

   MqlRates r[];ArraySetAsSeries(r,true);if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160){TZ_SetGate("DATA","INSUFFICIENT_M1_BARS");return;}
   datetime cb=r[1].time;if(cb==g_lastTradeBar){TZ_SetGate("BAR","ALREADY_TRADED_THIS_BAR");return;}
   double a=ATR(r,ATRPeriod,1);if(a<=0){TZ_SetGate("DATA","M1_ATR_UNAVAILABLE");return;}
   MqlTick tk;if(!SymbolInfoTick(_Symbol,tk)){TZ_SetGate("MARKET","NO_TICK");return;}
   bool origBuy=(g_plan.original_direction=="BUY"),havePos=AnyOurPosition();
   bool recentZone=TZ_RecentZoneInteraction(r,MathMax(30,ResearchRecentZoneBars));
   bool strategicRecentZone=TZ_RecentZoneInteraction(r,MathMax(30,AlternativeZoneInteractionBars));
   Signal sig;ZeroMemory(sig);string tag="";double share=0;string primaryStage="";bool primaryScanned=false;
   g_tzLocalRegime=TZ47_LocalRegime(r);
   g_tzCandidateModel="NONE";

   bool primaryAuthority=(
      g_tzExecutionAuthority=="HTF_CORE_HANDOFF"||
      g_tzExecutionAuthority=="HTF_ZONE_CONTACT_HANDOFF"||
      g_tzExecutionAuthority=="HTF_ZONE_SWEEP_HANDOFF"
   );
   bool objectiveOpen=!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask);

   if(primaryAuthority)
   {
      bool reentryPhase=(g_primaryEntries>0);
      if(!reentryPhase)
      {
         if(havePos){TZ_SetGate("POSITION","PRIMARY_BLOCKED_BY_EXISTING_POSITION");return;}
         primaryScanned=true;
         string sniperModel="";
         if(TZ60_ScanPrimaryEngine(r,origBuy,false,recentZone,sig,sniperModel,primaryStage))
         {tag="P0";share=PrimaryRiskShare;g_tzCandidateModel=sniperModel;}
      }
      else
      {
         if(!EnableReentries){TZ_SetGate("THESIS","REENTRIES_DISABLED");return;}
         if(MaxReentriesPerThesis>0&&g_reentries>=MaxReentriesPerThesis)
         {TZ_SetGate("THESIS","REENTRY_LIMIT_REACHED");return;}
         if(!objectiveOpen){TZ_SetGate("TARGET","THESIS_OBJECTIVE_COMPLETE");return;}
         if(havePos&&!AllProtected()){TZ_SetGate("POSITION","REENTRY_WAIT_POSITION_UNPROTECTED");return;}

         primaryScanned=true;
         string sniperModel="";
         double rshare=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);
         if(TZ60_ScanPrimaryEngine(r,origBuy,true,recentZone,sig,sniperModel,primaryStage))
         {
            tag="R"+IntegerToString(g_reentries+1);
            share=rshare;
            g_tzCandidateModel=sniperModel;
         }
      }
   }
   else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF"&&!havePos&&g_primaryEntries==0)
   {
      bool authorityBuy=(g_tzLRDirection=="BUY");
      if(g_tzLRDirection!=""&&authorityBuy==origBuy&&TZ31_BuildPostHandoffContinuation(r,a,origBuy,sig))
      {tag="L0";share=PrimaryRiskShare*MathMin(1.0,MathMax(0.10,g_tzLRRiskMultiplier));g_tzCandidateModel="LIQ_REVERSAL_CONTINUATION";}
   }
   else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF"&&EnableReentries&&
           g_reentries<MaxReentriesPerThesis&&(!havePos||AllProtected())&&objectiveOpen)
   {
      double rshare=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);
      if(BuildReentry(r,a,origBuy,sig))
      {tag="R"+IntegerToString(g_reentries+1);share=rshare;g_tzCandidateModel="REENTRY";}
   }

   if(!sig.valid)
   {
      string stage="";
      if(primaryAuthority&&primaryScanned)stage=primaryStage;
      else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF")
         stage=TZ31_DiagnosePostHandoff(r,a,origBuy);
      else stage="MICRO_PATTERN";
      string waitReason="WAITING_FOR_VALID_"+stage;
      if(primaryAuthority)waitReason+="_OR_M1_ENGULFING";
      TZ_SetGate(stage,waitReason);return;
   }

   double entry=sig.buy?tk.ask:tk.bid;
   int valueReactionIdx=-1;
   bool postHandoff=(tag=="L0"||tag=="S0");
   bool reactionRequired=true;
   bool sniperModel=(
      StringFind(sig.pd_type,"MASTER_SNIPER_PD_")==0||
      sig.pd_type=="ZONE_ENGULFING"
   );
   if(sniperModel)
   {
      valueReactionIdx=1;
   }
   else if(sig.reentry)
   {
      string reentryReason="";
      if(!TZ35_ReentryEntryReady(r,a,sig.buy,sig,entry,reentryReason,valueReactionIdx))
      {
         TZ_SetGate("REENTRY_CONFIRMATION",reentryReason);
         return;
      }
   }
   else if(postHandoff)
   {
      string handoffReason="";
      if(!TZ36_PostHandoffEntryReady(r,a,sig.buy,sig,entry,handoffReason,valueReactionIdx))
      {
         TZ_SetGate("HANDOFF_CONFIRMATION",handoffReason);
         return;
      }
   }
   else
   {
      string entryReason="";
      if(!TZ39_InitialEntryReady(r,a,sig.buy,sig,entry,tag,entryReason,valueReactionIdx))
      {
         TZ_SetGate("ENTRY_CONFIRMATION",entryReason);
         return;
      }
   }
   if(!TZ_TargetDirectionValid(false,sig.buy,entry)){TZ_SetGate("TARGET","NO_OPEN_TARGET_BEYOND_ENTRY");return;}
   string thesisId=(g_tzRuntimeThesisKey!=""?g_tzRuntimeThesisKey:(g_plan.analysis_id+"|"+g_plan.zone_id));
   datetime patternBreakTs=(sig.break_idx>=0&&sig.break_idx<ArraySize(r)?r[sig.break_idx].time:cb); string seq=thesisId+"|"+g_tzCandidateModel+"|"+IntegerToString((int)patternBreakTs)+"|"+sig.pd_type+"|"+IntegerToString((int)cb);
   if(seq==g_lastSequence){TZ_SetGate("DUPLICATE","SEQUENCE_ALREADY_SENT");return;}
   double microSl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;
   bool zoneProtectedSniper=(
      StringFind(sig.pd_type,"MASTER_SNIPER_PD_")==0||
      sig.pd_type=="ZONE_ENGULFING"
   );
   double sl=(sig.reentry&&!zoneProtectedSniper)
      ?NormalizeDouble(microSl,_Digits)
      :TZ46_InitialZoneProtectedStop(sig.buy,microSl,g_plan.zone_low,g_plan.zone_high,a);
   entry=NormalizeDouble(entry,_Digits);
   if(sl<=0){TZ_SetGate("RISK","ZONE_DISTAL_STOP_UNAVAILABLE");return;}
   if((sig.buy&&sl>=entry)||(!sig.buy&&sl<=entry)){TZ_SetGate("RISK","INVALID_STOP_SIDE");return;}

   // v3.60: actual-entry RR to the deepest still-open planned objective is the
   // distance gate. Nearer open objectives remain scale-outs. Fixed-dollar runway
   // does not veto an otherwise valid institutional first entry.
   double nearestTarget=0.0,rrTarget=0.0,rr=0.0,rrRequired=0.0;
   if(!TZ36_NearestDirectionalTarget(false,sig.buy,entry,nearestTarget)||
      !TZ49_DeepestDirectionalTarget(false,sig.buy,entry,rrTarget))
   {TZ_SetGate("TARGET","NO_OPEN_TARGET_BEYOND_ENTRY");return;}
   if(postHandoff&&TZ36_TargetAlreadyTradedSinceHandoff(r,sig.buy,nearestTarget))
   {TZ_SetGate("TARGET","POST_HANDOFF_OBJECTIVE_ALREADY_TRADED");return;}
   if(!TZ36_MinRRValid(entry,sl,rrTarget,rr,rrRequired))
   {TZ_SetGate("TARGET","MIN_RR_NOT_MET_TO_DEEPEST_OPEN_OBJECTIVE");return;}

   if(!TZ42_RevalidateParityBeforeOrder())return;
   double risk=TZ38_ThesisBudget(false,g_plan.grade)*share;g_tzLastRiskMoney=risk;double lots=TZ37_LotsForRisk(sig.buy,entry,sl,risk);g_tzLastIntendedLots=lots;if(lots<=0){TZ_SetGate("RISK","LOT_SIZE_ZERO_OR_BELOW_MIN");return;}
   TZ36_SendEntryDecisionAudit(tag,sig,entry,sl,lots,a,valueReactionIdx,rrTarget,rr,rrRequired,reactionRequired,r);
   if(TZ37_SendOrders(sig.buy,entry,sl,lots,false,tag,sig.pd_type))
   {
      if(sig.reentry)g_reentries++;else g_primaryEntries++;
      g_lastSequence=seq;g_lastTradeBar=cb;
      g_tzLastModel=(g_tzCandidateModel!=""&&g_tzCandidateModel!="NONE"?g_tzCandidateModel:sig.pd_type);
      TZ_SetGate("ORDER_SENT",g_tzLastSplitPartial?"DEMO_ENTRY_OPENED_PARTIAL_SPLIT":"DEMO_ENTRY_OPENED");
      Print("SMC Research v3.61 ",tag," opened. authority=",g_tzExecutionAuthority," model=",g_tzLastModel,
            " gate=",g_tzGateStage," lr=",g_tzLRLabel,"@",g_tzLRPrice," entry=",entry," sl=",sl,
            " rrTarget=",rrTarget," rr=",DoubleToString(rr,2)," riskMoney=",risk);
   }
   else TZ_SetGate("ORDER","MT5_ORDER_SEND_FAILED");
}

int OnInit()
{
   int rc=TZ27_SeqCore_OnInit();if(rc!=INIT_SUCCEEDED)return rc;
   if(ResearchMaxSpreadPoints<=0||ResearchRecentZoneBars<30)return INIT_PARAMETERS_INCORRECT;
   if(SimpleMicroMSSLookbackBars<6||SimpleMicroMSSLookbackBars>60)return INIT_PARAMETERS_INCORRECT;
   if(SniperPullbackMaxBars<2||SniperPullbackMaxBars>30)return INIT_PARAMETERS_INCORRECT;
   if(SniperConfirmMaxBars<1||SniperConfirmMaxBars>6)return INIT_PARAMETERS_INCORRECT;
   if(SniperEngulfContextBars<2||SniperEngulfContextBars>12)return INIT_PARAMETERS_INCORRECT;
   if(ResearchLiquidityReversalRiskMultiplier<=0||ResearchLiquidityReversalRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchZoneSweepRiskMultiplier<=0||ResearchZoneSweepRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeRiskMultiplier<=0||ResearchEscapeRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeLookbackBars<12||ResearchEscapeDisplacementATR<=0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeRetraceMin<=0||ResearchEscapeRetraceMax>=1.0||ResearchEscapeRetraceMin>=ResearchEscapeRetraceMax)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeMaxChaseATR<0||ResearchEscapeMaxChaseATR>0.30)return INIT_PARAMETERS_INCORRECT;
   if(ResearchFlipCandidateMaxMinutes<15||ResearchFlipCandidateMaxMinutes>720)return INIT_PARAMETERS_INCORRECT;
   if(AlternativeModelRiskMultiplier<=0||AlternativeModelRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(AlternativeZoneInteractionBars<30||AlternativeZoneInteractionBars>480)return INIT_PARAMETERS_INCORRECT;
   if(MomentumRetraceMin<=0||MomentumRetraceMax>=1.0||MomentumRetraceMin>=MomentumRetraceMax)return INIT_PARAMETERS_INCORRECT;
   if(MomentumMinDisplacementATR<0.40||MomentumMinDisplacementATR>2.0)return INIT_PARAMETERS_INCORRECT;
   if(VWAPBandATR<=0||VWAPBandATR>0.50||VWAPLookbackBars<30)return INIT_PARAMETERS_INCORRECT;
   if(VWAPMinDisplacementATR<0.40||VWAPMinDisplacementATR>2.0)return INIT_PARAMETERS_INCORRECT;
   if(OpeningRangeMinutes<15||OpeningRangeMinutes>90||ORBMaxMinutesAfterOpen<30||ORBMaxMinutesAfterOpen>480)return INIT_PARAMETERS_INCORRECT;
   if(ORBRetestBandATR<=0||ORBRetestBandATR>0.50||ORBMinBreakATR<0.40||ORBMinBreakATR>2.0)return INIT_PARAMETERS_INCORRECT;
   if(ReentrySignalMaxAgeBars<3||ReentrySignalMaxAgeBars>ReentryLookbackBars)return INIT_PARAMETERS_INCORRECT;
   if(ReentryValueReactionLookbackBars<1||ReentryValueReactionLookbackBars>12)return INIT_PARAMETERS_INCORRECT;
   if(ReentryReactionMinBodyATR<0.05||ReentryReactionMinBodyATR>1.00)return INIT_PARAMETERS_INCORRECT;
   if(ReentryReactionMaxChaseATR<0.0||ReentryReactionMaxChaseATR>0.50)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffSignalMaxAgeBars<3||PostHandoffSignalMaxAgeBars>ReentryLookbackBars)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffValueReactionLookbackBars<1||PostHandoffValueReactionLookbackBars>12)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffReactionMinBodyATR<0.05||PostHandoffReactionMinBodyATR>1.00)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffReactionMaxChaseATR<0.0||PostHandoffReactionMaxChaseATR>0.50)return INIT_PARAMETERS_INCORRECT;
   if(!ReentryRequireClosedM1ValueReaction||!PostHandoffRequireClosedM1ValueReaction)return INIT_PARAMETERS_INCORRECT;
   if(ProfessionalEntryValueReactionLookbackBars<1||ProfessionalEntryValueReactionLookbackBars>12)return INIT_PARAMETERS_INCORRECT;
   if(ProfessionalEntryReactionMinBodyATR<0.05||ProfessionalEntryReactionMinBodyATR>1.00)return INIT_PARAMETERS_INCORRECT;
   if(ProfessionalEntryReactionMaxChaseATR<0.0||ProfessionalEntryReactionMaxChaseATR>0.50)return INIT_PARAMETERS_INCORRECT;
   if(ResearchValidationInitialCapital<=0||ResearchRiskPctTrendAPlus<=0||ResearchRiskPctTrendA<=0||ResearchRiskPctCountertrendAPlus<=0||ResearchRiskPctCountertrendA<=0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchRiskPctTrendA>ResearchRiskPctTrendAPlus||ResearchRiskPctCountertrendAPlus>ResearchRiskPctTrendA||ResearchRiskPctCountertrendA>ResearchRiskPctCountertrendAPlus)return INIT_PARAMETERS_INCORRECT;
   g_tzValidationInitialCapital=ResearchValidationInitialCapital;g_tzRiskContext="TREND";g_tzOriginalRiskPct=0.0;g_tzFlipRiskPct=0.0;g_tzGradeRiskPct=0.0;
   TZ_SetGate("BOOT","READY");TZ28_LoadAcceptedFlip();TZ31_RefreshCloudState(true);TZ_PreCoreSync();
   if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();
   TZ_SavePersistentState();TZ28_SaveAcceptedFlip();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
   Print("TradeZone Sequence runtime ",TZ_SEQUENCE_VERSION," active. UNIFIED primary engine: zone sweep -> micro MSS -> causal OB/FVG -> bounded retest -> latest directional M1, or recent-zone engulfing. P0/R1/R2 use the same scanner. Full-zone buffered SL + actual-entry RR.");return INIT_SUCCEEDED;
}

void OnDeinit(const int reason){TZ_SavePersistentState();TZ28_SaveAcceptedFlip();TZ_WriteSequenceState();TZ27_SeqCore_OnDeinit(reason);}
void OnTimer()
{
   if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();
   TZ_PreCoreSync();TZ_LoadPersistentState();
   if(g_tzFlipPlanStored){g_flipPrimaryEntries=g_tzAcceptedFlipEntries;g_flipReentries=g_tzAcceptedFlipReentries;}
   TZ28_SaveAcceptedFlip();TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
}
void OnTick()
{
   if(!TZ45_ActiveOwnerMatchesCurrentPlan())TZ28_ArmAcceptedFlip();
   TZ_PreCoreSync();ManagePositions();Evaluate();
   if(g_tzFlipPlanStored){g_flipPrimaryEntries=g_tzAcceptedFlipEntries;g_flipReentries=g_tzAcceptedFlipReentries;}
   TZ28_SaveAcceptedFlip();TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
}

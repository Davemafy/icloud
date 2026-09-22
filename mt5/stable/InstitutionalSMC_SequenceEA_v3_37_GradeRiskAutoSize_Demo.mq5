#property strict
#property version   "3.37"
#property description "DEMO/PAPER XAU M1 execution: B+ reduced-risk authority + grade-scaled fixed-capital sizing + safe lot allocation + v3.36 confirmation/RR guards."

// Research wrapper around the validated v3.21 execution core.
// DEMO/PAPER ONLY. Real accounts remain hard-blocked.
// v3.29 keeps the v3.28 accepted-zone flip model and adds a second normal-location
// authority: HTF_ZONE_SWEEP_HANDOFF. Once the cloud proves price entered a qualified
// outer envelope and swept/reclaimed its attached structural liquidity, Sequence may
// search the SAME M1 sniper / deep-reentry / escape patterns without requiring a
// tactical-core touch. Authority is not an entry; value/no-chase/target/risk guards remain.
// Accepted invalidation is still never an instant reverse entry. DEMO/PAPER ONLY.

#define Evaluate TZ27_StrictBaseEvaluate
#define OnInit TZ27_SeqCore_OnInit
#define OnDeinit TZ27_SeqCore_OnDeinit
#define OnTimer TZ27_SeqCore_OnTimer
#define OnTick TZ27_SeqCore_OnTick
#define ManagePositions TZ21_BaseManagePositions
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#undef Evaluate
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick
#undef ManagePositions

#define TZ_SEQUENCE_VERSION "3.37"

input bool PaperResearchMode=true;
input double ResearchMaxSpreadPoints=50.0;
input bool ResearchUseDailyLossGuard=false;
input int ResearchRecentZoneBars=240;
input bool ResearchAllowContinuationRescue=true;
input double ResearchLiquidityReversalRiskMultiplier=0.50;
input double ResearchZoneSweepRiskMultiplier=0.65;
input bool ResearchAllowEscapePullback=true;
input double ResearchEscapeRiskMultiplier=0.50;
input int ResearchEscapeLookbackBars=90;
input double ResearchEscapeDisplacementATR=0.70;
input double ResearchEscapeRetraceMin=0.25;
input double ResearchEscapeRetraceMax=0.55;
input double ResearchEscapeMaxChaseATR=0.12;
input int ResearchFlipCandidateMaxMinutes=120;

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

// v3.37 grade-scaled research risk. Cloud exports the same values; these remain
// deterministic tester/fail-safe defaults.
input double ResearchValidationInitialCapital=10000.0;
input double ResearchRiskPctAPlus=1.00;
input double ResearchRiskPctA=0.75;
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
double g_tzLRPrice=0.0,g_tzLRRiskMultiplier=0.50;
datetime g_tzExecutionHandoffTs=0,g_tzLastCloudSync=0;
string g_tzRuntimeThesisKey="";

string g_tzRiskModel="GRADE_SCALED_INITIAL_CAPITAL_V1";
string g_tzRiskEpoch="RISK_NORMALIZED_10000_V1";
double g_tzValidationInitialCapital=10000.0;
double g_tzGradeRiskPct=0.0;
double g_tzLastRiskBase=0.0,g_tzLastRiskMoney=0.0,g_tzLastIntendedLots=0.0,g_tzLastActualLots=0.0;
bool g_tzLastSplitPartial=false;

// v3.37 grade-scaled fixed-capital sizing. The sizing base may shrink after
// realized losses but never compounds above the validation-capital anchor.
double TZ37_DefaultGradeRiskPct(string grade)
{
   if(grade=="A+")return ResearchRiskPctAPlus;
   if(grade=="A")return ResearchRiskPctA;
   if(grade=="B+")return ResearchRiskPctBPlus;
   return 0.0;
}

void TZ37_LoadRiskContract(string text,string grade)
{
   string model=KV(text,"risk_model");if(model!="")g_tzRiskModel=model;
   string epoch=KV(text,"risk_epoch");if(epoch!="")g_tzRiskEpoch=epoch;
   double cap=StringToDouble(KV(text,"validation_initial_capital"));
   if(cap>0)g_tzValidationInitialCapital=cap;
   else if(g_tzValidationInitialCapital<=0)g_tzValidationInitialCapital=ResearchValidationInitialCapital;
   double pct=StringToDouble(KV(text,"grade_risk_pct"));
   g_tzGradeRiskPct=(pct>0?pct:TZ37_DefaultGradeRiskPct(grade));
}

double TZ37_RiskBase()
{
   double cap=(g_tzValidationInitialCapital>0?g_tzValidationInitialCapital:ResearchValidationInitialCapital);
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   if(cap<=0||bal<=0)return 0.0;
   return MathMin(cap,bal);
}

double TZ37_ThesisBudget(bool flip,string grade)
{
   double pct=TZ37_DefaultGradeRiskPct(grade);
   if(grade==g_plan.grade&&g_tzGradeRiskPct>0)pct=g_tzGradeRiskPct;
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

bool TZ37_SendOrders(bool buy,double entry,double sl,double lots,bool flip,string tag,string pd)
{
   g_tzLastActualLots=0.0;g_tzLastSplitPartial=false;
   double total=TZ37_FloorVolume(lots);if(total<=0)return false;
   double t1,t2,t3,run;int nt=Targets(flip,buy,t1,t2,t3,run);if(nt<=0||t1<=0)return false;
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
         Print("SMC Research v3.37 management modify failed ticket=",ticket,
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

void TZ_SetGate(string stage,string reason)
{
   g_tzGateStage=stage;g_tzGateReason=reason;
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();g_tzGateTs=now;
}

void TZ28_ClearAcceptedFlip(string reason)
{
   g_tzFlipPlanStored=false;g_tzFlipAcceptedAt=0;g_tzFlipSourceAnalysis="";g_tzFlipSourceZone="";
   g_tzAcceptedFlipEntries=0;g_tzAcceptedFlipReentries=0;
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
   FileWriteString(h,"flip_entries="+IntegerToString(g_tzAcceptedFlipEntries)+"\r\n");
   FileWriteString(h,"flip_reentries="+IntegerToString(g_tzAcceptedFlipReentries)+"\r\n");
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
   p.valid=(p.analysis_id!=""&&p.zone_id!=""&&p.zone_low>0&&p.zone_high>p.zone_low);
   datetime accepted=(datetime)StringToInteger(TZ_ReadLocalKV("accepted_flip_state.txt","accepted_at"));
   if(!p.valid||accepted<=0){TZ28_ClearAcceptedFlip("PERSISTED_FLIP_INVALID");return;}
   g_tzFlipPlan=p;g_tzFlipPlanStored=true;g_tzFlipAcceptedAt=accepted;
   g_tzFlipSourceAnalysis=p.analysis_id;g_tzFlipSourceZone=p.zone_id;
   g_tzAcceptedFlipEntries=(int)StringToInteger(TZ_ReadLocalKV("accepted_flip_state.txt","flip_entries"));
   g_tzAcceptedFlipReentries=(int)StringToInteger(TZ_ReadLocalKV("accepted_flip_state.txt","flip_reentries"));
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
   g_tzAcceptedFlipEntries=0;g_tzAcceptedFlipReentries=0;
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

      // Authority is earned only after the failed-zone retest + M1 structure/displacement/value pattern exists.
      // The order still waits for price to return to the calculated value entry; no instant reverse and no chase.
      g_tzExecutionAuthority="ACCEPTED_ZONE_FLIP_HANDOFF";
      double entry=sig.buy?tk.ask:tk.bid;
      if(!EntryAtValue(sig.buy,entry,sig,a)){TZ_SetGate("FLIP_VALUE","FLIP_HANDOFF_EARNED_WAITING_FOR_VALUE_PULLBACK");break;}
      if(!TZ_TargetDirectionValid(true,sig.buy,entry)){TZ_SetGate("TARGET","NO_OPEN_FLIP_TARGET_BEYOND_ENTRY");break;}
      string seq=g_tzFlipSourceAnalysis+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;
      if(seq==g_lastSequence){TZ_SetGate("DUPLICATE","FLIP_SEQUENCE_ALREADY_SENT");break;}
      double sl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;
      sl=NormalizeDouble(sl,_Digits);entry=NormalizeDouble(entry,_Digits);
      if((sig.buy&&sl>=entry)||(!sig.buy&&sl<=entry)){TZ_SetGate("RISK","INVALID_FLIP_STOP_SIDE");break;}
      double risk=TZ37_ThesisBudget(true,g_tzFlipPlan.grade)*share;g_tzLastRiskMoney=risk;double lots=TZ37_LotsForRisk(sig.buy,entry,sl,risk);g_tzLastIntendedLots=lots;
      if(lots<=0){TZ_SetGate("RISK","FLIP_LOT_SIZE_ZERO");break;}
      if(TZ37_SendOrders(sig.buy,entry,sl,lots,true,tag,sig.pd_type))
      {
         if(tag=="F0")g_tzAcceptedFlipEntries++;else g_tzAcceptedFlipReentries++;
         g_flipPrimaryEntries=g_tzAcceptedFlipEntries;g_flipReentries=g_tzAcceptedFlipReentries;
         g_lastSequence=seq;g_lastTradeBar=cb;g_tzLastModel="ACCEPTED_ZONE_FLIP_"+sig.pd_type;
         TZ_SetGate("ORDER_SENT","DEMO_ACCEPTED_ZONE_FLIP_OPENED");
         TZ28_SaveAcceptedFlip();
         Print("SMC Research v3.37 ",tag," opened from accepted-zone flip. authority=",g_tzExecutionAuthority,
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
   string ownerId=TZ30_OwnerKV("owner_mirror_zone_id");
   string acquired=TZ30_OwnerKV("owner_mirror_acquired_at");
   string seed="";
   if(ownerActive=="1"&&ownerId!="") seed="OWNER|"+ownerId+"|"+acquired;
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
      "owner_mirror_status","owner_mirror_authority","owner_mirror_acquired_at",
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
   TZ37_LoadRiskContract(text,g_plan.grade);
}


bool TZ31_RefreshCloudState(bool force=false)
{
   if(IsTester())
   {
      if(!RefreshPlan())return false;
      g_tzExecutionAuthority="HTF_CORE_HANDOFF";
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

   // Persist/release the owner mirror even while execution is safety-blocked.
   // A wide spread must stop orders, not erase the institutional thesis recovery copy.
   TZ30_SaveOwnerMirrorFromPlan(text);

   if(KV(text,"live_block")=="1")
   {
      g_plan.valid=false;g_tzExecutionAuthority="NONE";
      TZ_SetGate("SAFETY","CLOUD_LIVE_BLOCK:"+KV(text,"live_block_reason"));return false;
   }

   Plan p;if(!ParsePlanText(text,p))
   {
      g_tzExecutionAuthority="NONE";TZ_SetGate("PLAN","PLAN_PARSE_FAILED");return false;
   }

   string ownerActive=KV(text,"owner_mirror_active");
   string ownerId=KV(text,"owner_mirror_zone_id");
   string ownerAcquired=KV(text,"owner_mirror_acquired_at");
   string newThesisKey=(ownerActive=="1"&&ownerId!="")?("OWNER|"+ownerId+"|"+ownerAcquired):("ZONE|"+p.zone_id);
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
   TZ37_LoadRiskContract(text,g_plan.grade);

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
   FileWriteString(h,"last_execution_model="+g_tzLastModel+"\r\n");
   FileWriteString(h,"gate_stage="+g_tzGateStage+"\r\n");
   FileWriteString(h,"gate_reason="+g_tzGateReason+"\r\n");
   FileWriteString(h,"candidate_model="+g_tzCandidateModel+"\r\n");
   FileWriteString(h,"risk_model="+g_tzRiskModel+"\r\n");
   FileWriteString(h,"risk_epoch="+g_tzRiskEpoch+"\r\n");
   FileWriteString(h,"validation_initial_capital="+DoubleToString(g_tzValidationInitialCapital,2)+"\r\n");
   FileWriteString(h,"grade_risk_pct="+DoubleToString(g_tzGradeRiskPct,2)+"\r\n");
   FileWriteString(h,"last_risk_base="+DoubleToString(g_tzLastRiskBase,2)+"\r\n");
   FileWriteString(h,"last_risk_money="+DoubleToString(g_tzLastRiskMoney,2)+"\r\n");
   FileWriteString(h,"last_intended_lots="+DoubleToString(g_tzLastIntendedLots,4)+"\r\n");
   FileWriteString(h,"last_actual_lots="+DoubleToString(g_tzLastActualLots,4)+"\r\n");
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
      "\"state_persisted\":true,\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"plan_valid\":%s,\"execution_authority\":\"%s\",\"last_execution_model\":\"%s\","
      "\"owner_mirror_contract\":\"%s\",\"owner_mirror_active\":%s,\"owner_mirror_saved_at\":%I64d,"
      "\"owner_mirror_analysis_id\":\"%s\",\"owner_mirror_zone_id\":\"%s\",\"owner_mirror_direction\":\"%s\","
      "\"owner_mirror_source_tf\":\"%s\",\"owner_mirror_source_ts\":%I64d,\"owner_mirror_grade\":\"%s\","
      "\"owner_mirror_status\":\"%s\",\"owner_mirror_authority\":\"%s\",\"owner_mirror_acquired_at\":%I64d,"
      "\"owner_mirror_core_low\":%s,\"owner_mirror_core_high\":%s,\"owner_mirror_zone_low\":%s,\"owner_mirror_zone_high\":%s,"
      "\"owner_mirror_target1\":%s,\"owner_mirror_target2\":%s,\"owner_mirror_target3\":%s,"
      "\"owner_mirror_target1_hit_at\":%I64d,\"owner_mirror_target2_hit_at\":%I64d,\"owner_mirror_target3_hit_at\":%I64d,"
      "\"owner_mirror_reaction_confirmed_at\":%I64d,\"owner_mirror_best_price\":%s,\"owner_mirror_zone_payload_b64\":\"%s\","
      "\"execution_handoff_ts\":%I64d,"
      "\"gate_stage\":\"%s\",\"gate_reason\":\"%s\",\"candidate_model\":\"%s\",\"gate_ts\":%I64d,"
      "\"primary_entries\":%d,\"reentries\":%d,\"flip_primary_entries\":%d,\"flip_reentries\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\",\"installed_sequence_version\":\"%s\","
      "\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\",\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzLastModel),
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
      TZ_JsonEscape(g_tzGateStage),TZ_JsonEscape(g_tzGateReason),TZ_JsonEscape(g_tzCandidateModel),(long)g_tzGateTs,
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

bool TZ_ResearchGuards()
{
   if(!IsTester()&&!IsDemo()){TZ_SetGate("SAFETY","NON_DEMO_ACCOUNT");return false;}
   if(!g_plan.valid){TZ_SetGate("PLAN","PLAN_INVALID");return false;}
   if(g_plan.ea_mode!="DUAL_BRANCH"){TZ_SetGate("AUTHORITY","PLAN_WATCH_ONLY");return false;}
   if(g_tzExecutionAuthority!="HTF_CORE_HANDOFF"&&
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



bool TZ36_PostHandoffEntryReady(MqlRates &r[],double a,bool buy,Signal &s,double market,string &reason,int &reactionIdx)
{
   reactionIdx=-1;
   if(s.break_idx<3||s.break_idx>PostHandoffSignalMaxAgeBars)
   {
      reason="POST_HANDOFF_SIGNAL_STALE";
      return false;
   }

   // A first post-handoff PD array that has already been accepted through is dead.
   int newest=MathMin(s.pd_idx-1,ArraySize(r)-2);
   for(int j=newest;j>=1;j--)
   {
      if(buy&&r[j].close<s.pd_low){reason="POST_HANDOFF_PD_ACCEPTED_INVALIDATION";return false;}
      if(!buy&&r[j].close>s.pd_high){reason="POST_HANDOFF_PD_ACCEPTED_INVALIDATION";return false;}
   }

   if(!PostHandoffRequireClosedM1ValueReaction)
   {
      if(EntryAtValue(buy,market,s,a)){reason="POST_HANDOFF_LEGACY_VALUE_TOUCH_ALLOWED";return true;}
      reason="WAITING_FOR_POST_HANDOFF_VALUE_TOUCH";
      return false;
   }

   // Value-touch alone is never an L0/S0 entry. Require a CLOSED M1 rejection
   // from the overlap and a micro break in the intended direction.
   int mx=MathMin(PostHandoffValueReactionLookbackBars,MathMin(s.pd_idx-1,ArraySize(r)-3));
   for(int i=1;i<=mx;i++)
   {
      bool touched=(r[i].high>=s.entry_low&&r[i].low<=s.entry_high);
      if(!touched)continue;
      double body=MathAbs(r[i].close-r[i].open);
      bool directional=buy?(r[i].close>r[i].open):(r[i].close<r[i].open);
      bool rejected=buy?(r[i].close>=s.entry_high):(r[i].close<=s.entry_low);
      bool microBreak=buy?(r[i].close>r[i+1].high):(r[i].close<r[i+1].low);
      if(directional&&rejected&&microBreak&&body>=a*PostHandoffReactionMinBodyATR)
      {
         reactionIdx=i;
         break;
      }
   }
   if(reactionIdx<0)
   {
      reason="WAITING_FOR_CLOSED_M1_POST_HANDOFF_VALUE_REACTION";
      return false;
   }

   double chase=0.0;
   if(buy&&market>s.entry_high)chase=market-s.entry_high;
   if(!buy&&market<s.entry_low)chase=s.entry_low-market;
   if(chase>a*PostHandoffReactionMaxChaseATR)
   {
      reason="POST_HANDOFF_REACTION_CONFIRMED_BUT_CHASED";
      return false;
   }
   if(buy&&market<s.entry_low-a*MaxEntryChaseATR)
   {
      reason="POST_HANDOFF_VALUE_REACTION_LOST_BELOW_ARRAY";
      return false;
   }
   if(!buy&&market>s.entry_high+a*MaxEntryChaseATR)
   {
      reason="POST_HANDOFF_VALUE_REACTION_LOST_ABOVE_ARRAY";
      return false;
   }

   reason="POST_HANDOFF_VALUE_REACTION_CONFIRMED";
   return true;
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

   // Once a bearish PD array is accepted above its distal edge (or bullish below),
   // it is no longer a professional first-class value array for a new re-entry.
   int newest=MathMin(s.pd_idx-1,ArraySize(r)-2);
   for(int j=newest;j>=1;j--)
   {
      if(buy&&r[j].close<s.pd_low){reason="PD_ARRAY_ACCEPTED_INVALIDATION";return false;}
      if(!buy&&r[j].close>s.pd_high){reason="PD_ARRAY_ACCEPTED_INVALIDATION";return false;}
   }

   if(!ReentryRequireClosedM1ValueReaction)
   {
      if(EntryAtValue(buy,market,s,a)){reason="LEGACY_VALUE_TOUCH_ALLOWED";return true;}
      reason="WAITING_FOR_VALUE_TOUCH";
      return false;
   }

   // The touch itself is not an entry. Wait for a CLOSED M1 candle to reject the
   // overlap in thesis direction and close through the prior candle's micro structure.
   int mx=MathMin(ReentryValueReactionLookbackBars,MathMin(s.pd_idx-1,ArraySize(r)-3));
   for(int i=1;i<=mx;i++)
   {
      bool touched=(r[i].high>=s.entry_low&&r[i].low<=s.entry_high);
      if(!touched)continue;
      double body=MathAbs(r[i].close-r[i].open);
      bool directional=buy?(r[i].close>r[i].open):(r[i].close<r[i].open);
      bool rejected=buy?(r[i].close>=s.entry_high):(r[i].close<=s.entry_low);
      bool microBreak=buy?(r[i].close>r[i+1].high):(r[i].close<r[i+1].low);
      if(directional&&rejected&&microBreak&&body>=a*ReentryReactionMinBodyATR)
      {
         reactionIdx=i;
         break;
      }
   }
   if(reactionIdx<0)
   {
      reason="WAITING_FOR_CLOSED_M1_VALUE_REACTION";
      return false;
   }

   // Confirmation is not permission to chase. If price has already run too far away,
   // or has pushed back through the wrong side of the value overlap, stand down.
   double chase=0.0;
   if(buy&&market>s.entry_high)chase=market-s.entry_high;
   if(!buy&&market<s.entry_low)chase=s.entry_low-market;
   if(chase>a*ReentryReactionMaxChaseATR)
   {
      reason="CONFIRMED_VALUE_REACTION_BUT_CHASED";
      return false;
   }
   if(buy&&market<s.entry_low-a*MaxEntryChaseATR)
   {
      reason="VALUE_REACTION_LOST_BELOW_ARRAY";
      return false;
   }
   if(!buy&&market>s.entry_high+a*MaxEntryChaseATR)
   {
      reason="VALUE_REACTION_LOST_ABOVE_ARRAY";
      return false;
   }

   reason="REENTRY_VALUE_REACTION_CONFIRMED";
   return true;
}

void TZ36_SendEntryDecisionAudit(string tag,Signal &s,double entry,double sl,double lots,double a,int reactionIdx,double openTarget,double rr,double rrRequired,bool reactionRequired,MqlRates &r[])
{
   if(IsTester())return;
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   datetime breakTs=(s.break_idx>=0&&s.break_idx<ArraySize(r)?r[s.break_idx].time:0);
   datetime pdTs=(s.pd_idx>=0&&s.pd_idx<ArraySize(r)?r[s.pd_idx].time:0);
   datetime reactionTs=(reactionIdx>=1&&reactionIdx<ArraySize(r)?r[reactionIdx].time:0);
   string setup=(tag=="L0"?"LIQUIDITY_REVERSAL":tag=="S0"?"ZONE_SWEEP_CONTINUATION":StringFind(tag,"R")==0?"REENTRY_"+StringSubstr(tag,1):tag);
   string campaign=g_plan.analysis_id+"|"+g_plan.zone_id+"|"+tag;
   string details=StringFormat(
      "{\"campaign_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\",\"direction\":\"%s\","
      "\"authority\":\"%s\",\"candidate_model\":\"%s\",\"pd_type\":\"%s\","
      "\"break_bar_ts\":%I64d,\"pd_bar_ts\":%I64d,\"value_reaction_bar_ts\":%I64d,"
      "\"anchor_price\":%.5f,\"break_level\":%.5f,\"impulse_extreme\":%.5f,"
      "\"ote_low\":%.5f,\"ote_high\":%.5f,\"pd_low\":%.5f,\"pd_high\":%.5f,"
      "\"entry_low\":%.5f,\"entry_high\":%.5f,\"entry_price\":%.5f,\"stop_price\":%.5f,"
      "\"m1_atr\":%.5f,\"lots\":%.4f,\"reentries_before\":%d,"
      "\"nearest_open_target\":%.5f,\"rr_at_entry\":%.4f,\"min_rr_required\":%.4f,"
      "\"closed_m1_value_reaction_required\":%d,\"closed_m1_value_reaction_confirmed\":%d}",
      TZ_JsonEscape(campaign),TZ_JsonEscape(setup),TZ_JsonEscape(tag),(s.buy?"BUY":"SELL"),
      TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzCandidateModel),TZ_JsonEscape(s.pd_type),
      (long)breakTs,(long)pdTs,(long)reactionTs,
      s.anchor_price,s.break_level,s.impulse_extreme,s.ote_low,s.ote_high,s.pd_low,s.pd_high,
      s.entry_low,s.entry_high,entry,sl,a,lots,g_reentries,
      openTarget,rr,rrRequired,(reactionRequired?1:0),(reactionIdx>=1?1:0));
   string body=StringFormat(
      "{\"ts\":%I64d,\"event\":\"ENTRY_DECISION\",\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"price\":%.5f,\"details\":%s}",
      (long)now,TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),entry,details);
   string response;
   TZ_Post("/mt5/feedback",body,response);
}

void Evaluate()
{
   // Critical ordering fix: capture M15 accepted invalidation against the OLD zone
   // before RefreshPlan / cloud authority changes can replace or de-authorize it.
   TZ28_ArmAcceptedFlip();

   if(g_tzFlipPlanStored)
   {
      // Refresh current cloud safety/context, but accepted-zone flip execution uses
      // the persisted failed-zone geometry and its own post-invalidation handoff.
      TZ31_RefreshCloudState(false);
      TZ28_EvaluateAcceptedFlip();
      return;
   }

   if(!TZ31_RefreshCloudState(false)){TZ_SetGate("PLAN","PLAN_REFRESH_FAILED");return;}

   // A fresh cloud plan may itself report FAILED_FLIP_CANDIDATE.
   TZ28_ArmAcceptedFlip();
   if(g_tzFlipPlanStored){TZ28_EvaluateAcceptedFlip();return;}

   if(!TZ_ResearchGuards())return;

   MqlRates r[];ArraySetAsSeries(r,true);if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160){TZ_SetGate("DATA","INSUFFICIENT_M1_BARS");return;}
   datetime cb=r[1].time;if(cb==g_lastTradeBar){TZ_SetGate("BAR","ALREADY_TRADED_THIS_BAR");return;}
   double a=ATR(r,ATRPeriod,1);if(a<=0){TZ_SetGate("DATA","M1_ATR_UNAVAILABLE");return;}
   MqlTick tk;if(!SymbolInfoTick(_Symbol,tk)){TZ_SetGate("MARKET","NO_TICK");return;}
   bool origBuy=(g_plan.original_direction=="BUY"),havePos=AnyOurPosition();
   bool recentZone=TZ_RecentZoneInteraction(r,MathMax(30,ResearchRecentZoneBars));Signal sig;ZeroMemory(sig);string tag="";double share=0;
   g_tzCandidateModel="NONE";

   // Terminal cap truth: after R2 (default MaxReentriesPerThesis=2), the same
   // thesis may continue as context but cannot silently advertise another value wait.
   if(!havePos&&EnableReentries&&MaxReentriesPerThesis>0&&g_reentries>=MaxReentriesPerThesis)
   {
      TZ_SetGate("THESIS","REENTRY_LIMIT_REACHED");
      return;
   }

   if(!havePos&&g_primaryEntries==0)
   {
      if(g_tzExecutionAuthority=="HTF_CORE_HANDOFF")
      {
         if(BuildPrimary(r,a,origBuy,sig)){tag="P0";share=PrimaryRiskShare;g_tzCandidateModel="SNIPER";}
         else if(PaperResearchMode&&ResearchAllowContinuationRescue&&recentZone&&BuildReentry(r,a,origBuy,sig))
         {sig.reentry=false;tag="C0";share=PrimaryRiskShare;g_tzCandidateModel="DEEP_REENTRY";}
         else if(PaperResearchMode&&ResearchAllowEscapePullback&&recentZone&&TZ_BuildEscapePullback(r,a,origBuy,sig))
         {sig.reentry=false;tag="E0";share=PrimaryRiskShare*ResearchEscapeRiskMultiplier;g_tzCandidateModel="ESCAPE_PULLBACK";}
      }
      else if(g_tzExecutionAuthority=="HTF_ZONE_SWEEP_HANDOFF")
      {
         if(TZ31_BuildPostHandoffContinuation(r,a,origBuy,sig))
         {tag="S0";share=PrimaryRiskShare*MathMin(1.0,MathMax(0.10,ResearchZoneSweepRiskMultiplier));g_tzCandidateModel="ZONE_SWEEP_CONTINUATION";}
      }
      else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF")
      {
         bool authorityBuy=(g_tzLRDirection=="BUY");
         if(g_tzLRDirection!=""&&authorityBuy==origBuy&&TZ31_BuildPostHandoffContinuation(r,a,origBuy,sig))
         {tag="L0";share=PrimaryRiskShare*MathMin(1.0,MathMax(0.10,g_tzLRRiskMultiplier));g_tzCandidateModel="LIQ_REVERSAL_CONTINUATION";}
      }
   }
   else if(!havePos&&EnableReentries&&g_reentries<MaxReentriesPerThesis&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
   {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);g_tzCandidateModel="REENTRY";}}
   else if(havePos&&EnableReentries&&g_reentries<MaxReentriesPerThesis&&AllProtected()&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
   {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);g_tzCandidateModel="REENTRY";}}

   if(!sig.valid)
   {
      string stage="";
      if(g_tzExecutionAuthority=="HTF_CORE_HANDOFF")stage=TZ_DiagnosePrimaryStage(r,a,origBuy,recentZone);
      else if(g_tzExecutionAuthority=="HTF_ZONE_SWEEP_HANDOFF"||g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF")
         stage=TZ31_DiagnosePostHandoff(r,a,origBuy);
      else stage="MICRO_PATTERN";
      TZ_SetGate(stage,"WAITING_FOR_VALID_"+stage);return;
   }

   double entry=sig.buy?tk.ask:tk.bid;
   int valueReactionIdx=-1;
   bool postHandoff=(tag=="L0"||tag=="S0");
   bool reactionRequired=false;
   if(sig.reentry)
   {
      reactionRequired=ReentryRequireClosedM1ValueReaction;
      string reentryReason="";
      if(!TZ35_ReentryEntryReady(r,a,sig.buy,sig,entry,reentryReason,valueReactionIdx))
      {
         TZ_SetGate("REENTRY_CONFIRMATION",reentryReason);
         return;
      }
   }
   else if(postHandoff)
   {
      reactionRequired=PostHandoffRequireClosedM1ValueReaction;
      string handoffReason="";
      if(!TZ36_PostHandoffEntryReady(r,a,sig.buy,sig,entry,handoffReason,valueReactionIdx))
      {
         TZ_SetGate("HANDOFF_CONFIRMATION",handoffReason);
         return;
      }
   }
   else
   {
      bool atValue=(tag=="E0"?TZ_EntryAtEscapeValue(sig.buy,entry,sig,a):EntryAtValue(sig.buy,entry,sig,a));
      if(!atValue){TZ_SetGate("VALUE","SIGNAL_FOUND_WAITING_FOR_PULLBACK");return;}
   }
   if(!TZ_TargetDirectionValid(false,sig.buy,entry)){TZ_SetGate("TARGET","NO_OPEN_TARGET_BEYOND_ENTRY");return;}
   string thesisId=(g_tzRuntimeThesisKey!=""?g_tzRuntimeThesisKey:(g_plan.analysis_id+"|"+g_plan.zone_id));
   string seq=thesisId+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;
   if(seq==g_lastSequence){TZ_SetGate("DUPLICATE","SEQUENCE_ALREADY_SENT");return;}
   double sl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;sl=NormalizeDouble(sl,_Digits);entry=NormalizeDouble(entry,_Digits);
   if((sig.buy&&sl>=entry)||(!sig.buy&&sl<=entry)){TZ_SetGate("RISK","INVALID_STOP_SIDE");return;}

   // Every original-side entry must have a real open objective and meet the cloud plan's
   // minimum RR. For post-handoff entries, a target already traded after the handoff is expired.
   double openTarget=0.0,rr=0.0,rrRequired=0.0;
   if(!TZ36_NearestDirectionalTarget(false,sig.buy,entry,openTarget))
   {TZ_SetGate("TARGET","NO_OPEN_TARGET_BEYOND_ENTRY");return;}
   if(postHandoff&&TZ36_TargetAlreadyTradedSinceHandoff(r,sig.buy,openTarget))
   {TZ_SetGate("TARGET","POST_HANDOFF_OBJECTIVE_ALREADY_TRADED");return;}
   if(!TZ36_MinRRValid(entry,sl,openTarget,rr,rrRequired))
   {TZ_SetGate("TARGET","MIN_RR_NOT_MET");return;}

   double risk=TZ37_ThesisBudget(false,g_plan.grade)*share;g_tzLastRiskMoney=risk;double lots=TZ37_LotsForRisk(sig.buy,entry,sl,risk);g_tzLastIntendedLots=lots;if(lots<=0){TZ_SetGate("RISK","LOT_SIZE_ZERO_OR_BELOW_MIN");return;}
   TZ36_SendEntryDecisionAudit(tag,sig,entry,sl,lots,a,valueReactionIdx,openTarget,rr,rrRequired,reactionRequired,r);
   if(TZ37_SendOrders(sig.buy,entry,sl,lots,false,tag,sig.pd_type))
   {
      if(sig.reentry)g_reentries++;else g_primaryEntries++;
      g_lastSequence=seq;g_lastTradeBar=cb;
      g_tzLastModel=(tag=="L0"?"LIQ_REVERSAL_":tag=="E0"?"ESCAPE_":"")+sig.pd_type;
      TZ_SetGate("ORDER_SENT",g_tzLastSplitPartial?"DEMO_ENTRY_OPENED_PARTIAL_SPLIT":"DEMO_ENTRY_OPENED");
      Print("SMC Research v3.37 ",tag," opened. authority=",g_tzExecutionAuthority," model=",g_tzLastModel,
            " gate=",g_tzGateStage," lr=",g_tzLRLabel,"@",g_tzLRPrice," entry=",entry," sl=",sl,
            " target=",openTarget," rr=",DoubleToString(rr,2)," riskMoney=",risk);
   }
   else TZ_SetGate("ORDER","MT5_ORDER_SEND_FAILED");
}

int OnInit()
{
   int rc=TZ27_SeqCore_OnInit();if(rc!=INIT_SUCCEEDED)return rc;
   if(ResearchMaxSpreadPoints<=0||ResearchRecentZoneBars<30)return INIT_PARAMETERS_INCORRECT;
   if(ResearchLiquidityReversalRiskMultiplier<=0||ResearchLiquidityReversalRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchZoneSweepRiskMultiplier<=0||ResearchZoneSweepRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeRiskMultiplier<=0||ResearchEscapeRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeLookbackBars<12||ResearchEscapeDisplacementATR<=0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeRetraceMin<=0||ResearchEscapeRetraceMax>=1.0||ResearchEscapeRetraceMin>=ResearchEscapeRetraceMax)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeMaxChaseATR<0||ResearchEscapeMaxChaseATR>0.30)return INIT_PARAMETERS_INCORRECT;
   if(ResearchFlipCandidateMaxMinutes<15||ResearchFlipCandidateMaxMinutes>720)return INIT_PARAMETERS_INCORRECT;
   if(ReentrySignalMaxAgeBars<3||ReentrySignalMaxAgeBars>ReentryLookbackBars)return INIT_PARAMETERS_INCORRECT;
   if(ReentryValueReactionLookbackBars<1||ReentryValueReactionLookbackBars>12)return INIT_PARAMETERS_INCORRECT;
   if(ReentryReactionMinBodyATR<0.05||ReentryReactionMinBodyATR>1.00)return INIT_PARAMETERS_INCORRECT;
   if(ReentryReactionMaxChaseATR<0.0||ReentryReactionMaxChaseATR>0.50)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffSignalMaxAgeBars<3||PostHandoffSignalMaxAgeBars>ReentryLookbackBars)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffValueReactionLookbackBars<1||PostHandoffValueReactionLookbackBars>12)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffReactionMinBodyATR<0.05||PostHandoffReactionMinBodyATR>1.00)return INIT_PARAMETERS_INCORRECT;
   if(PostHandoffReactionMaxChaseATR<0.0||PostHandoffReactionMaxChaseATR>0.50)return INIT_PARAMETERS_INCORRECT;
   if(ResearchValidationInitialCapital<=0||ResearchRiskPctAPlus<=0||ResearchRiskPctA<=0||ResearchRiskPctBPlus<=0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchRiskPctBPlus>=ResearchRiskPctA||ResearchRiskPctA>ResearchRiskPctAPlus)return INIT_PARAMETERS_INCORRECT;
   g_tzValidationInitialCapital=ResearchValidationInitialCapital;g_tzGradeRiskPct=TZ37_DefaultGradeRiskPct(g_plan.grade);
   TZ_SetGate("BOOT","READY");TZ28_LoadAcceptedFlip();TZ31_RefreshCloudState(true);TZ_PreCoreSync();
   TZ28_ArmAcceptedFlip();TZ_SavePersistentState();TZ28_SaveAcceptedFlip();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
   Print("TradeZone Sequence runtime ",TZ_SEQUENCE_VERSION," active. Safety blocks pause orders but still persist/release the exact owner mirror; no chase.");return INIT_SUCCEEDED;
}

void OnDeinit(const int reason){TZ_SavePersistentState();TZ28_SaveAcceptedFlip();TZ_WriteSequenceState();TZ27_SeqCore_OnDeinit(reason);}
void OnTimer()
{
   TZ28_ArmAcceptedFlip();
   TZ_PreCoreSync();TZ_LoadPersistentState();
   if(g_tzFlipPlanStored){g_flipPrimaryEntries=g_tzAcceptedFlipEntries;g_flipReentries=g_tzAcceptedFlipReentries;}
   TZ28_SaveAcceptedFlip();TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
}
void OnTick()
{
   TZ28_ArmAcceptedFlip();
   TZ_PreCoreSync();ManagePositions();Evaluate();
   if(g_tzFlipPlanStored){g_flipPrimaryEntries=g_tzAcceptedFlipEntries;g_flipReentries=g_tzAcceptedFlipReentries;}
   TZ28_SaveAcceptedFlip();TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
}

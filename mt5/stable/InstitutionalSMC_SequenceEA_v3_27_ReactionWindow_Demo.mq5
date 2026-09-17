#property strict
#property version   "3.27"
#property description "DEMO/PAPER XAU M1 reaction-window execution: macro location latch + sniper/escape micro entries."

// Research wrapper around the validated v3.21 execution core.
// DEMO/PAPER ONLY. Real accounts remain hard-blocked.
// v3.27 keeps macro location alive after a qualified HTF core interaction so
// M1 structure can complete outside the box. It adds a reduced-risk first
// pullback escape model and explicit no-trade gate telemetry.

#define Evaluate TZ27_StrictBaseEvaluate
#define OnInit TZ27_SeqCore_OnInit
#define OnDeinit TZ27_SeqCore_OnDeinit
#define OnTimer TZ27_SeqCore_OnTimer
#define OnTick TZ27_SeqCore_OnTick
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#undef Evaluate
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick

#define TZ_SEQUENCE_VERSION "3.27"

input bool PaperResearchMode=true;
input double ResearchMaxSpreadPoints=50.0;
input bool ResearchUseDailyLossGuard=false;
input int ResearchRecentZoneBars=240;
input bool ResearchAllowContinuationRescue=true;
input double ResearchLiquidityReversalRiskMultiplier=0.50;
input bool ResearchAllowEscapePullback=true;
input double ResearchEscapeRiskMultiplier=0.50;
input int ResearchEscapeLookbackBars=90;
input double ResearchEscapeDisplacementATR=0.70;
input double ResearchEscapeRetraceMin=0.25;
input double ResearchEscapeRetraceMax=0.55;
input double ResearchEscapeMaxChaseATR=0.12;

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

void TZ_SetGate(string stage,string reason)
{
   g_tzGateStage=stage;g_tzGateReason=reason;
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();g_tzGateTs=now;
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
   if(g_plan.analysis_id=="")return "";
   string seed=g_plan.analysis_id+"|"+g_plan.zone_id;
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

void TZ27_LoadExecutionAuthority(bool force=false)
{
   if(IsTester()){g_tzExecutionAuthority="HTF_CORE_HANDOFF";return;}
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(!force && now-g_tzLastAuthorityPoll<MathMax(2,PollSeconds))return;
   g_tzLastAuthorityPoll=now;
   string text;if(!HttpGet("/mt5/plan",text)){g_tzExecutionAuthority="NONE";TZ_SetGate("AUTHORITY","PLAN_HTTP_UNAVAILABLE");return;}
   if(KV(text,"analysis_id")!=g_plan.analysis_id){g_tzExecutionAuthority="NONE";TZ_SetGate("AUTHORITY","ANALYSIS_ID_MISMATCH");return;}
   g_tzExecutionAuthority=KV(text,"execution_authority");if(g_tzExecutionAuthority=="")g_tzExecutionAuthority="NONE";
   g_tzLRDirection=KV(text,"liquidity_reversal_direction");
   g_tzLRLabel=KV(text,"liquidity_reversal_label");
   g_tzLRPrice=StringToDouble(KV(text,"liquidity_reversal_price"));
   double rm=StringToDouble(KV(text,"liquidity_reversal_risk_multiplier"));
   g_tzLRRiskMultiplier=(rm>0&&rm<=1.0?rm:ResearchLiquidityReversalRiskMultiplier);
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
      "\"gate_stage\":\"%s\",\"gate_reason\":\"%s\",\"candidate_model\":\"%s\",\"gate_ts\":%I64d,"
      "\"primary_entries\":%d,\"reentries\":%d,\"flip_primary_entries\":%d,\"flip_reentries\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\",\"installed_sequence_version\":\"%s\","
      "\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\",\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzLastModel),
      TZ_JsonEscape(g_tzGateStage),TZ_JsonEscape(g_tzGateReason),TZ_JsonEscape(g_tzCandidateModel),(long)g_tzGateTs,
      g_primaryEntries,g_reentries,g_flipPrimaryEntries,g_flipReentries,TZ_JsonEscape(updater),TZ_JsonEscape(stable),TZ_JsonEscape(installedBridge),TZ_JsonEscape(installedSequence),
      TZ_JsonEscape(desiredBridge),TZ_JsonEscape(desiredSequence),TZ_JsonEscape(pending),TZ_JsonEscape(updateResult));
   string r;TZ_Post("/mt5/heartbeat",body,r);
}

void TZ_PreCoreSync()
{
   if(IsTester())return;
   if(OperatingMode==LIVE_CLOUD)RefreshPlan();
   TZ_LoadPersistentState();TZ27_LoadExecutionAuthority(false);
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
   if(g_tzExecutionAuthority!="HTF_CORE_HANDOFF"&&g_tzExecutionAuthority!="LIQUIDITY_REVERSAL_HANDOFF")
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

void Evaluate()
{
   if(!RefreshPlan()){TZ_SetGate("PLAN","PLAN_REFRESH_FAILED");return;}
   TZ27_LoadExecutionAuthority(false);if(!TZ_ResearchGuards())return;
   if(EnableZoneFlip&&!g_flipCandidate&&M15Acceptance()){g_flipCandidate=true;Print("SMC Research v3.27: M15 accepted invalidation -> FLIP_CANDIDATE. No instant reverse.");}

   MqlRates r[];ArraySetAsSeries(r,true);if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160){TZ_SetGate("DATA","INSUFFICIENT_M1_BARS");return;}
   datetime cb=r[1].time;if(cb==g_lastTradeBar){TZ_SetGate("BAR","ALREADY_TRADED_THIS_BAR");return;}
   double a=ATR(r,ATRPeriod,1);if(a<=0){TZ_SetGate("DATA","M1_ATR_UNAVAILABLE");return;}
   MqlTick tk;if(!SymbolInfoTick(_Symbol,tk)){TZ_SetGate("MARKET","NO_TICK");return;}
   bool origBuy=(g_plan.original_direction=="BUY"),flipBuy=(g_plan.flip_direction=="BUY"),havePos=AnyOurPosition();
   bool recentZone=TZ_RecentZoneInteraction(r,MathMax(30,ResearchRecentZoneBars));Signal sig;ZeroMemory(sig);string tag="";bool useFlip=false;double share=0;
   g_tzCandidateModel="NONE";

   if(!g_flipCandidate)
   {
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
         else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF")
         {
            bool authorityBuy=(g_tzLRDirection=="BUY");
            if(g_tzLRDirection!=""&&authorityBuy==origBuy&&BuildReentry(r,a,origBuy,sig))
            {sig.reentry=false;tag="L0";share=PrimaryRiskShare*MathMin(1.0,MathMax(0.10,g_tzLRRiskMultiplier));g_tzCandidateModel="LIQ_REVERSAL";}
         }
      }
      else if(!havePos&&EnableReentries&&g_reentries<MaxReentriesPerThesis&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);g_tzCandidateModel="REENTRY";}}
      else if(havePos&&EnableReentries&&g_reentries<MaxReentriesPerThesis&&AllProtected()&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);g_tzCandidateModel="REENTRY";}}
   }
   else if(EnableZoneFlip&&!havePos)
   {
      useFlip=true;
      if(g_flipPrimaryEntries==0){if(BuildFlip(r,a,flipBuy,sig)){tag="F0";share=PrimaryRiskShare;g_tzCandidateModel="FLIP";}}
      else if(EnableReentries&&g_flipReentries<MaxReentriesPerThesis&&!ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,flipBuy,sig)){sig.flip=true;tag="FR"+IntegerToString(g_flipReentries+1);share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);g_tzCandidateModel="FLIP_REENTRY";}}
   }
   else if(EnableZoneFlip&&havePos&&g_flipPrimaryEntries>0&&EnableReentries&&g_flipReentries<MaxReentriesPerThesis&&AllProtected()&&!ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
   {useFlip=true;if(BuildReentry(r,a,flipBuy,sig)){sig.flip=true;tag="FR"+IntegerToString(g_flipReentries+1);share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);g_tzCandidateModel="FLIP_REENTRY";}}

   if(!sig.valid)
   {
      string stage=(g_tzExecutionAuthority=="HTF_CORE_HANDOFF"?TZ_DiagnosePrimaryStage(r,a,origBuy,recentZone):"MICRO_PATTERN");
      TZ_SetGate(stage,"WAITING_FOR_VALID_"+stage);return;
   }

   double entry=sig.buy?tk.ask:tk.bid;
   bool atValue=(tag=="E0"?TZ_EntryAtEscapeValue(sig.buy,entry,sig,a):EntryAtValue(sig.buy,entry,sig,a));
   if(!atValue){TZ_SetGate("VALUE","SIGNAL_FOUND_WAITING_FOR_PULLBACK");return;}
   if(!TZ_TargetDirectionValid(useFlip,sig.buy,entry)){TZ_SetGate("TARGET","NO_OPEN_TARGET_BEYOND_ENTRY");return;}
   string seq=g_plan.analysis_id+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;
   if(seq==g_lastSequence){TZ_SetGate("DUPLICATE","SEQUENCE_ALREADY_SENT");return;}
   double sl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;sl=NormalizeDouble(sl,_Digits);entry=NormalizeDouble(entry,_Digits);
   if((sig.buy&&sl>=entry)||(!sig.buy&&sl<=entry)){TZ_SetGate("RISK","INVALID_STOP_SIDE");return;}
   double risk=ThesisBudget(useFlip)*share;double lots=LotsForRisk(entry,sl,risk);if(lots<=0){TZ_SetGate("RISK","LOT_SIZE_ZERO");return;}
   if(SendOrders(sig.buy,entry,sl,lots,useFlip,tag,sig.pd_type))
   {
      if(useFlip){if(sig.reentry)g_flipReentries++;else g_flipPrimaryEntries++;}
      else{if(sig.reentry)g_reentries++;else g_primaryEntries++;}
      g_lastSequence=seq;g_lastTradeBar=cb;
      g_tzLastModel=(tag=="L0"?"LIQ_REVERSAL_":tag=="E0"?"ESCAPE_":"")+sig.pd_type;
      TZ_SetGate("ORDER_SENT","DEMO_ENTRY_OPENED");
      Print("SMC Research v3.27 ",tag," opened. authority=",g_tzExecutionAuthority," model=",g_tzLastModel,
            " gate=",g_tzGateStage," lr=",g_tzLRLabel,"@",g_tzLRPrice," entry=",entry," sl=",sl," riskMoney=",risk);
   }
   else TZ_SetGate("ORDER","MT5_ORDER_SEND_FAILED");
}

int OnInit()
{
   int rc=TZ27_SeqCore_OnInit();if(rc!=INIT_SUCCEEDED)return rc;
   if(ResearchMaxSpreadPoints<=0||ResearchRecentZoneBars<30)return INIT_PARAMETERS_INCORRECT;
   if(ResearchLiquidityReversalRiskMultiplier<=0||ResearchLiquidityReversalRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeRiskMultiplier<=0||ResearchEscapeRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeLookbackBars<12||ResearchEscapeDisplacementATR<=0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeRetraceMin<=0||ResearchEscapeRetraceMax>=1.0||ResearchEscapeRetraceMin>=ResearchEscapeRetraceMax)return INIT_PARAMETERS_INCORRECT;
   if(ResearchEscapeMaxChaseATR<0||ResearchEscapeMaxChaseATR>0.30)return INIT_PARAMETERS_INCORRECT;
   TZ_SetGate("BOOT","READY");TZ_PreCoreSync();TZ27_LoadExecutionAuthority(true);TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
   Print("TradeZone Sequence runtime ",TZ_SEQUENCE_VERSION," active. DEMO/PAPER reaction-window execution; sniper + reduced-risk escape pullback; no chase.");return INIT_SUCCEEDED;
}

void OnDeinit(const int reason){TZ_SavePersistentState();TZ_WriteSequenceState();TZ27_SeqCore_OnDeinit(reason);}
void OnTimer(){TZ_PreCoreSync();TZ27_SeqCore_OnTimer();TZ_LoadPersistentState();TZ27_LoadExecutionAuthority(false);TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();}
void OnTick(){TZ_PreCoreSync();ManagePositions();Evaluate();TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();}

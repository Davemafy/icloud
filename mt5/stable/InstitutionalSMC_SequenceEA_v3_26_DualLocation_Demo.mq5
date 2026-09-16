#property strict
#property version   "3.26"
#property description "DEMO/PAPER XAU M1 dual-location execution: HTF core handoff + confirmed liquidity-reversal handoff."

// Research wrapper around the validated v3.21 execution core.
// DEMO/PAPER ONLY. Real accounts remain hard-blocked.
// v3.26 makes execution authority explicit: HTF_CORE_HANDOFF or
// LIQUIDITY_REVERSAL_HANDOFF. A liquidity object is never promoted into an HTF zone.

#define Evaluate TZ26_StrictBaseEvaluate
#define OnInit TZ26_SeqCore_OnInit
#define OnDeinit TZ26_SeqCore_OnDeinit
#define OnTimer TZ26_SeqCore_OnTimer
#define OnTick TZ26_SeqCore_OnTick
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#undef Evaluate
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick

#define TZ_SEQUENCE_VERSION "3.26"

input bool PaperResearchMode=true;
input double ResearchMaxSpreadPoints=50.0;
input bool ResearchUseDailyLossGuard=false;
input int ResearchRecentZoneBars=240;
input bool ResearchAllowContinuationRescue=true;
input double ResearchLiquidityReversalRiskMultiplier=0.50;

datetime g_tzLastStateWrite=0,g_tzLastHeartbeat=0,g_tzLastAuthorityPoll=0;
string g_tzLoadedStateKey="";
string g_tzLastModel="";
string g_tzExecutionAuthority="NONE";
string g_tzLRDirection="";
string g_tzLRLabel="";
double g_tzLRPrice=0.0,g_tzLRRiskMultiplier=0.50;

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

void TZ26_LoadExecutionAuthority(bool force=false)
{
   if(IsTester()){g_tzExecutionAuthority="HTF_CORE_HANDOFF";return;}
   datetime now=TimeTradeServer();if(now<=0)now=TimeCurrent();
   if(!force && now-g_tzLastAuthorityPoll<MathMax(2,PollSeconds))return;
   g_tzLastAuthorityPoll=now;
   string text;if(!HttpGet("/mt5/plan",text)){g_tzExecutionAuthority="NONE";return;}
   if(KV(text,"analysis_id")!=g_plan.analysis_id){g_tzExecutionAuthority="NONE";return;}
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
      "\"primary_entries\":%d,\"reentries\":%d,\"flip_primary_entries\":%d,\"flip_reentries\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\",\"installed_sequence_version\":\"%s\","
      "\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\",\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzExecutionAuthority),TZ_JsonEscape(g_tzLastModel),
      g_primaryEntries,g_reentries,g_flipPrimaryEntries,g_flipReentries,TZ_JsonEscape(updater),TZ_JsonEscape(stable),TZ_JsonEscape(installedBridge),TZ_JsonEscape(installedSequence),
      TZ_JsonEscape(desiredBridge),TZ_JsonEscape(desiredSequence),TZ_JsonEscape(pending),TZ_JsonEscape(updateResult));
   string r;TZ_Post("/mt5/heartbeat",body,r);
}

void TZ_PreCoreSync()
{
   if(IsTester())return;
   if(OperatingMode==LIVE_CLOUD)RefreshPlan();
   TZ_LoadPersistentState();TZ26_LoadExecutionAuthority(false);
}

bool TZ_RecentZoneInteraction(MqlRates &r[],int bars)
{
   int n=MathMin(bars,ArraySize(r)-2);for(int i=1;i<=n;i++)if(r[i].high>=g_plan.zone_low&&r[i].low<=g_plan.zone_high)return true;return false;
}

bool TZ_ResearchGuards()
{
   if(!IsTester()&&!IsDemo())return false;
   if(!g_plan.valid||g_plan.ea_mode!="DUAL_BRANCH")return false;
   if(g_tzExecutionAuthority!="HTF_CORE_HANDOFF"&&g_tzExecutionAuthority!="LIQUIDITY_REVERSAL_HANDOFF")return false;
   MqlTick t;if(!SymbolInfoTick(_Symbol,t))return false;double spread=(t.ask-t.bid)/_Point;
   double maxSpread=PaperResearchMode?ResearchMaxSpreadPoints:MaxSpreadPoints;if(maxSpread>0&&spread>maxSpread)return false;
   if(!PaperResearchMode||ResearchUseDailyLossGuard){double maxLoss=AccountInfoDouble(ACCOUNT_BALANCE)*ThesisRiskPct/100.0*MaxDailyLossR;if(TodayPnL()<=-maxLoss)return false;}
   return true;
}

bool TZ_TargetDirectionValid(bool flip,bool buy,double entry)
{
   double t1,t2,t3,run;int n=Targets(flip,buy,t1,t2,t3,run);if(n<=0)return false;
   double minGap=MathMax(_Point*5.0,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));double targets[4]={t1,t2,t3,run};bool any=false;
   for(int i=0;i<4;i++){double x=targets[i];if(x<=0)continue;if(buy&&x>entry+minGap)any=true;if(!buy&&x<entry-minGap)any=true;}return any;
}

void Evaluate()
{
   if(!RefreshPlan())return;TZ26_LoadExecutionAuthority(false);if(!TZ_ResearchGuards())return;
   if(EnableZoneFlip&&!g_flipCandidate&&M15Acceptance()){g_flipCandidate=true;Print("SMC Research v3.26: M15 accepted invalidation -> FLIP_CANDIDATE. No instant reverse.");}

   MqlRates r[];ArraySetAsSeries(r,true);if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160)return;datetime cb=r[1].time;if(cb==g_lastTradeBar)return;
   double a=ATR(r,ATRPeriod,1);if(a<=0)return;MqlTick tk;if(!SymbolInfoTick(_Symbol,tk))return;
   bool origBuy=(g_plan.original_direction=="BUY"),flipBuy=(g_plan.flip_direction=="BUY"),havePos=AnyOurPosition();
   bool recentZone=TZ_RecentZoneInteraction(r,MathMax(30,ResearchRecentZoneBars));Signal sig;ZeroMemory(sig);string tag="";bool useFlip=false;double share=0;

   if(!g_flipCandidate)
   {
      if(!havePos&&g_primaryEntries==0)
      {
         if(g_tzExecutionAuthority=="HTF_CORE_HANDOFF")
         {
            if(BuildPrimary(r,a,origBuy,sig)){tag="P0";share=PrimaryRiskShare;}
            else if(PaperResearchMode&&ResearchAllowContinuationRescue&&recentZone&&BuildReentry(r,a,origBuy,sig)){sig.reentry=false;tag="C0";share=PrimaryRiskShare;}
         }
         else if(g_tzExecutionAuthority=="LIQUIDITY_REVERSAL_HANDOFF")
         {
            bool authorityBuy=(g_tzLRDirection=="BUY");
            if(g_tzLRDirection!=""&&authorityBuy==origBuy&&BuildReentry(r,a,origBuy,sig))
            {
               sig.reentry=false;tag="L0";share=PrimaryRiskShare*MathMin(1.0,MathMax(0.10,g_tzLRRiskMultiplier));
            }
         }
      }
      else if(!havePos&&EnableReentries&&g_reentries<MaxReentriesPerThesis&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);}}
      else if(havePos&&EnableReentries&&g_reentries<MaxReentriesPerThesis&&AllProtected()&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);}}
   }
   else if(EnableZoneFlip&&!havePos)
   {
      useFlip=true;
      if(g_flipPrimaryEntries==0){if(BuildFlip(r,a,flipBuy,sig)){tag="F0";share=PrimaryRiskShare;}}
      else if(EnableReentries&&g_flipReentries<MaxReentriesPerThesis&&!ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,flipBuy,sig)){sig.flip=true;tag="FR"+IntegerToString(g_flipReentries+1);share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);}}
   }
   else if(EnableZoneFlip&&havePos&&g_flipPrimaryEntries>0&&EnableReentries&&g_flipReentries<MaxReentriesPerThesis&&AllProtected()&&!ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
   {useFlip=true;if(BuildReentry(r,a,flipBuy,sig)){sig.flip=true;tag="FR"+IntegerToString(g_flipReentries+1);share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);}}

   if(!sig.valid)return;double entry=sig.buy?tk.ask:tk.bid;if(!EntryAtValue(sig.buy,entry,sig,a))return;if(!TZ_TargetDirectionValid(useFlip,sig.buy,entry))return;
   string seq=g_plan.analysis_id+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;if(seq==g_lastSequence)return;
   double sl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;sl=NormalizeDouble(sl,_Digits);entry=NormalizeDouble(entry,_Digits);
   if((sig.buy&&sl>=entry)||(!sig.buy&&sl<=entry))return;double risk=ThesisBudget(useFlip)*share;double lots=LotsForRisk(entry,sl,risk);if(lots<=0)return;
   if(SendOrders(sig.buy,entry,sl,lots,useFlip,tag,sig.pd_type))
   {
      if(useFlip){if(sig.reentry)g_flipReentries++;else g_flipPrimaryEntries++;}
      else{if(sig.reentry)g_reentries++;else g_primaryEntries++;}
      g_lastSequence=seq;g_lastTradeBar=cb;g_tzLastModel=(tag=="L0"?"LIQ_REVERSAL_":"")+sig.pd_type;
      Print("SMC Research v3.26 ",tag," opened. authority=",g_tzExecutionAuthority," model=",g_tzLastModel,
            " lr=",g_tzLRLabel,"@",g_tzLRPrice," entry=",entry," sl=",sl," riskMoney=",risk);
   }
}

int OnInit()
{
   int rc=TZ26_SeqCore_OnInit();if(rc!=INIT_SUCCEEDED)return rc;
   if(ResearchMaxSpreadPoints<=0||ResearchRecentZoneBars<30)return INIT_PARAMETERS_INCORRECT;
   if(ResearchLiquidityReversalRiskMultiplier<=0||ResearchLiquidityReversalRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   TZ_PreCoreSync();TZ26_LoadExecutionAuthority(true);TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();
   Print("TradeZone Sequence runtime ",TZ_SEQUENCE_VERSION," active. DEMO/PAPER dual-location execution; full M1 value sequence required.");return INIT_SUCCEEDED;
}

void OnDeinit(const int reason){TZ_SavePersistentState();TZ_WriteSequenceState();TZ26_SeqCore_OnDeinit(reason);}
void OnTimer(){TZ_PreCoreSync();TZ26_SeqCore_OnTimer();TZ_LoadPersistentState();TZ26_LoadExecutionAuthority(false);TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();}
void OnTick(){TZ_PreCoreSync();ManagePositions();Evaluate();TZ_SavePersistentState();TZ_WriteSequenceState();TZ_SendSequenceHeartbeat();}

#property strict
#property version   "3.25"
#property description "DEMO/PAPER XAU M1 research-flow sequence: simple institutional entry testing with minimal gates."

// Research wrapper around the validated v3.21 execution core.
// DEMO/PAPER ONLY. Real accounts remain hard-blocked.
// The purpose is to collect entry/management data before re-introducing extra filters.

#define Evaluate TZ25_StrictBaseEvaluate
#define OnInit TZ25_SeqCore_OnInit
#define OnDeinit TZ25_SeqCore_OnDeinit
#define OnTimer TZ25_SeqCore_OnTimer
#define OnTick TZ25_SeqCore_OnTick
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#undef Evaluate
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick

#define TZ_SEQUENCE_VERSION "3.25"

input bool PaperResearchMode=true;
input double ResearchMaxSpreadPoints=50.0;
input bool ResearchUseDailyLossGuard=false;
input int ResearchRecentZoneBars=240;
input bool ResearchAllowContinuationRescue=true;

datetime g_tzLastStateWrite=0,g_tzLastHeartbeat=0;
string g_tzLoadedStateKey="";
string g_tzLastModel="";

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
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
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
      ulong t=PositionGetTicket(i);
      if(!t)continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol && (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber)n++;
   }
   return n;
}

void TZ_LoadPersistentState()
{
   string p=TZ_StatePrefix();
   if(p==""||p==g_tzLoadedStateKey)return;
   g_tzLoadedStateKey=p;
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
   string p=TZ_StatePrefix();
   if(p=="")return;
   GlobalVariableSet(p+".P",(double)g_primaryEntries);
   GlobalVariableSet(p+".R",(double)g_reentries);
   GlobalVariableSet(p+".FP",(double)g_flipPrimaryEntries);
   GlobalVariableSet(p+".FR",(double)g_flipReentries);
   GlobalVariableSet(p+".BAR",(double)g_lastTradeBar);
   GlobalVariableSet(p+".FLIP",g_flipCandidate?1.0:0.0);
   GlobalVariableSet(p+".FAT",(double)g_flipAcceptedAt);
}

bool TZ_Post(string path,string body,string &response)
{
   if(CloudApiKey=="")return false;
   string url=CloudBaseUrl+path;
   string headers="Content-Type: application/json\r\nX-API-Key: "+CloudApiKey+"\r\n";
   char data[],result[];
   string rh;
   StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);
   if(ArraySize(data)>0)ArrayResize(data,ArraySize(data)-1);
   ResetLastError();
   int code=WebRequest("POST",url,headers,HttpTimeoutMs,data,result,rh);
   response=CharArrayToString(result,0,-1,CP_UTF8);
   return code==200;
}

void TZ_WriteSequenceState()
{
   if(IsTester())return;
   datetime now=TimeTradeServer();
   if(now<=0)now=TimeCurrent();
   if(now-g_tzLastStateWrite<5)return;
   g_tzLastStateWrite=now;
   int openCount=TZ_OpenPositionCount();
   bool safe=(openCount==0);
   FolderCreate("TradeZone");
   int h=FileOpen("TradeZone\\sequence_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return;
   FileWriteString(h,"ts="+IntegerToString((int)now)+"\r\n");
   FileWriteString(h,"version="+TZ_SEQUENCE_VERSION+"\r\n");
   FileWriteString(h,"restart_safe="+(safe?"1":"0")+"\r\n");
   FileWriteString(h,"active_sequence="+(openCount>0?"1":"0")+"\r\n");
   FileWriteString(h,"open_positions="+IntegerToString(openCount)+"\r\n");
   FileWriteString(h,"analysis_id="+g_plan.analysis_id+"\r\n");
   FileWriteString(h,"zone_id="+g_plan.zone_id+"\r\n");
   FileWriteString(h,"plan_valid="+(g_plan.valid?"1":"0")+"\r\n");
   FileWriteString(h,"research_mode="+(PaperResearchMode?"1":"0")+"\r\n");
   FileWriteString(h,"primary_entries="+IntegerToString(g_primaryEntries)+"\r\n");
   FileWriteString(h,"reentries="+IntegerToString(g_reentries)+"\r\n");
   FileWriteString(h,"flip_primary_entries="+IntegerToString(g_flipPrimaryEntries)+"\r\n");
   FileWriteString(h,"flip_reentries="+IntegerToString(g_flipReentries)+"\r\n");
   FileClose(h);
}

void TZ_SendSequenceHeartbeat()
{
   if(IsTester()||OperatingMode!=LIVE_CLOUD)return;
   datetime now=TimeTradeServer();
   if(now<=0)now=TimeCurrent();
   if(now-g_tzLastHeartbeat<15)return;
   g_tzLastHeartbeat=now;
   int openCount=TZ_OpenPositionCount();
   bool safe=(openCount==0);
   string updater=TZ_ReadLocalKV("updater_status.txt","updater_version");
   string stable=TZ_ReadLocalKV("updater_status.txt","stable_release");
   string installedBridge=TZ_ReadLocalKV("updater_status.txt","installed_bridge_version");
   string installedSequence=TZ_ReadLocalKV("updater_status.txt","installed_sequence_version");
   string desiredBridge=TZ_ReadLocalKV("updater_status.txt","desired_bridge_version");
   string desiredSequence=TZ_ReadLocalKV("updater_status.txt","desired_sequence_version");
   string pending=TZ_ReadLocalKV("updater_status.txt","pending_reload");
   string updateResult=TZ_ReadLocalKV("updater_status.txt","result");
   string body=StringFormat(
      "{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_SequenceEA\",\"version\":\"%s\",\"symbol\":\"%s\",\"account_login\":%I64d,"
      "\"details\":{\"paper_only\":true,\"research_mode\":%s,\"restart_safe\":%s,\"active_sequence\":%s,\"open_positions\":%d,"
      "\"state_persisted\":true,\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"plan_valid\":%s,\"last_execution_model\":\"%s\","
      "\"primary_entries\":%d,\"reentries\":%d,\"flip_primary_entries\":%d,\"flip_reentries\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\","
      "\"installed_sequence_version\":\"%s\",\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\","
      "\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),
      PaperResearchMode?"true":"false",safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",TZ_JsonEscape(g_tzLastModel),
      g_primaryEntries,g_reentries,g_flipPrimaryEntries,g_flipReentries,
      TZ_JsonEscape(updater),TZ_JsonEscape(stable),TZ_JsonEscape(installedBridge),TZ_JsonEscape(installedSequence),
      TZ_JsonEscape(desiredBridge),TZ_JsonEscape(desiredSequence),TZ_JsonEscape(pending),TZ_JsonEscape(updateResult)
   );
   string r;
   TZ_Post("/mt5/heartbeat",body,r);
}

void TZ_PreCoreSync()
{
   if(IsTester())return;
   if(OperatingMode==LIVE_CLOUD)RefreshPlan();
   TZ_LoadPersistentState();
}

bool TZ_RecentZoneInteraction(MqlRates &r[],int bars)
{
   int n=MathMin(bars,ArraySize(r)-2);
   for(int i=1;i<=n;i++)
      if(r[i].high>=g_plan.zone_low && r[i].low<=g_plan.zone_high)return true;
   return false;
}

bool TZ_ResearchGuards()
{
   // Hard boundary: this research EA can never execute on a real-money account.
   if(!IsTester() && !IsDemo())return false;
   if(!g_plan.valid || g_plan.ea_mode=="NO_TRADE")return false;

   MqlTick t;
   if(!SymbolInfoTick(_Symbol,t))return false;
   double spread=(t.ask-t.bid)/_Point;
   double maxSpread=PaperResearchMode?ResearchMaxSpreadPoints:MaxSpreadPoints;
   if(maxSpread>0 && spread>maxSpread)return false;

   if(!PaperResearchMode || ResearchUseDailyLossGuard)
   {
      double maxLoss=AccountInfoDouble(ACCOUNT_BALANCE)*ThesisRiskPct/100.0*MaxDailyLossR;
      if(TodayPnL()<=-maxLoss)return false;
   }
   return true;
}

bool TZ_TargetDirectionValid(bool flip,bool buy,double entry)
{
   double t1,t2,t3,run;
   int n=Targets(flip,buy,t1,t2,t3,run);
   if(n<=0)return false;
   double minGap=MathMax(_Point*5.0,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
   double targets[4]={t1,t2,t3,run};
   bool any=false;
   for(int i=0;i<4;i++)
   {
      double x=targets[i];
      if(x<=0)continue;
      if(buy && x>entry+minGap)any=true;
      if(!buy && x<entry-minGap)any=true;
   }
   return any;
}

void Evaluate()
{
   if(!RefreshPlan()||!TZ_ResearchGuards())return;

   if(EnableZoneFlip && !g_flipCandidate && M15Acceptance())
   {
      g_flipCandidate=true;
      Print("SMC Research v3.25: M15 accepted invalidation -> FLIP_CANDIDATE. No instant reverse.");
   }

   MqlRates r[];
   ArraySetAsSeries(r,true);
   if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160)return;

   datetime cb=r[1].time;
   if(cb==g_lastTradeBar)return;

   double a=ATR(r,ATRPeriod,1);
   if(a<=0)return;

   MqlTick tk;
   if(!SymbolInfoTick(_Symbol,tk))return;

   bool origBuy=(g_plan.original_direction=="BUY");
   bool flipBuy=(g_plan.flip_direction=="BUY");
   bool havePos=AnyOurPosition();
   bool recentZone=TZ_RecentZoneInteraction(r,MathMax(30,ResearchRecentZoneBars));
   Signal sig;
   ZeroMemory(sig);
   string tag="";
   bool useFlip=false;
   double share=0;

   if(!g_flipCandidate)
   {
      if(!havePos && g_primaryEntries==0)
      {
         // First choice: the full sniper model from the institutional prompt.
         if(BuildPrimary(r,a,origBuy,sig))
         {
            tag="P0";
            share=PrimaryRiskShare;
         }
         // Research-flow rescue: if the zone already interacted and price has since
         // built a valid continuation BOS/displacement/value sequence, allow that
         // sequence to become the first paper entry instead of missing the move.
         else if(PaperResearchMode && ResearchAllowContinuationRescue && recentZone && BuildReentry(r,a,origBuy,sig))
         {
            sig.reentry=false;
            tag="C0";
            share=PrimaryRiskShare;
         }
      }
      else if(!havePos && EnableReentries && g_reentries<MaxReentriesPerThesis &&
              !ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {
         // A prior paper entry may already be closed. Continue testing the thesis
         // without requiring a currently open/protected position.
         if(BuildReentry(r,a,origBuy,sig))
         {
            tag="R"+IntegerToString(g_reentries+1);
            share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);
         }
      }
      else if(havePos && EnableReentries && g_reentries<MaxReentriesPerThesis &&
              AllProtected() && !ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {
         // Keep the professional no-averaging-down rule when a position is open.
         if(BuildReentry(r,a,origBuy,sig))
         {
            tag="R"+IntegerToString(g_reentries+1);
            share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);
         }
      }
   }
   else if(EnableZoneFlip && !havePos)
   {
      useFlip=true;
      if(g_flipPrimaryEntries==0)
      {
         if(BuildFlip(r,a,flipBuy,sig))
         {
            tag="F0";
            share=PrimaryRiskShare;
         }
      }
      else if(EnableReentries && g_flipReentries<MaxReentriesPerThesis &&
              !ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
      {
         if(BuildReentry(r,a,flipBuy,sig))
         {
            sig.flip=true;
            tag="FR"+IntegerToString(g_flipReentries+1);
            share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);
         }
      }
   }
   else if(EnableZoneFlip && havePos && g_flipPrimaryEntries>0 &&
           EnableReentries && g_flipReentries<MaxReentriesPerThesis &&
           AllProtected() && !ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
   {
      useFlip=true;
      if(BuildReentry(r,a,flipBuy,sig))
      {
         sig.flip=true;
         tag="FR"+IntegerToString(g_flipReentries+1);
         share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);
      }
   }

   if(!sig.valid)return;

   double entry=sig.buy?tk.ask:tk.bid;
   if(!EntryAtValue(sig.buy,entry,sig,a))return;
   if(!TZ_TargetDirectionValid(useFlip,sig.buy,entry))return;

   string seq=g_plan.analysis_id+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;
   if(seq==g_lastSequence)return;

   double sl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;
   sl=NormalizeDouble(sl,_Digits);
   entry=NormalizeDouble(entry,_Digits);

   if((sig.buy && sl>=entry) || (!sig.buy && sl<=entry))return;

   double risk=ThesisBudget(useFlip)*share;
   double lots=LotsForRisk(entry,sl,risk);
   if(lots<=0)return;

   if(SendOrders(sig.buy,entry,sl,lots,useFlip,tag,sig.pd_type))
   {
      if(useFlip)
      {
         if(sig.reentry)g_flipReentries++;
         else g_flipPrimaryEntries++;
      }
      else
      {
         if(sig.reentry)g_reentries++;
         else g_primaryEntries++;
      }
      g_lastSequence=seq;
      g_lastTradeBar=cb;
      g_tzLastModel=sig.pd_type;
      Print("SMC Research v3.25 ",tag," opened. model=",sig.pd_type,
            " research=",PaperResearchMode," recentZone=",recentZone,
            " entry=",entry," sl=",sl," riskMoney=",risk);
   }
}

int OnInit()
{
   int rc=TZ25_SeqCore_OnInit();
   if(rc!=INIT_SUCCEEDED)return rc;
   if(ResearchMaxSpreadPoints<=0)return INIT_PARAMETERS_INCORRECT;
   if(ResearchRecentZoneBars<30)return INIT_PARAMETERS_INCORRECT;

   TZ_PreCoreSync();
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SendSequenceHeartbeat();

   Print("TradeZone Sequence runtime ",TZ_SEQUENCE_VERSION,
         " active. DEMO/PAPER research flow: strict M1 pattern + value entry, fewer extra gates.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ25_SeqCore_OnDeinit(reason);
}

void OnTimer()
{
   TZ_PreCoreSync();
   TZ25_SeqCore_OnTimer();
   TZ_LoadPersistentState();
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SendSequenceHeartbeat();
}

void OnTick()
{
   TZ_PreCoreSync();
   ManagePositions();
   Evaluate();
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SendSequenceHeartbeat();
}

#property strict
#property version "1.44"
#property description "DEMO/PAPER bridge with Sequence 3.36 handoff/RR truth overlay, provenance-safe journal recovery, V659 zones, and ownership."

#define TZ_JOURNAL_BRIDGE_VERSION "1.44"
#define OnInit TZ_BridgeCore_OnInit
#define OnDeinit TZ_BridgeCore_OnDeinit
#define OnTimer TZ_BridgeCore_OnTimer
#define OnTradeTransaction TZ_BridgeCore_OnTradeTransaction
#include <TradeZoneCore\InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5>
#include <TradeZoneCore\TradeZone_ZoneRenderer_v1_0.mqh>
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTradeTransaction

#define TZ_BRIDGE_VERSION "1.44"
#define TZ_SEQUENCE_EXPECTED "3.36"
#define TZ_ZONE_RENDER_CONTRACT "V659"

input bool LogSuccessfulSnapshots=true;
input int RetryAfterStaleSeconds=90;
input bool ShowTwoZoneMapOnXauM1=true;

datetime g_tzBridgeStateAt=0;
datetime g_tzLastSnapshotSuccess=0;
int g_tzSnapshotFailures=0;
int g_tzMapCount=0;
string g_tzSellState="NONE",g_tzBuyState="NONE";
string g_tzSellZone="",g_tzBuyZone="";

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
   FileClose(h);StringTrimLeft(value);StringTrimRight(value);return value;
}

int TZ_SequenceOpenPositions()
{
   int n=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(!ticket)continue;
      if(PositionGetString(POSITION_SYMBOL)!=XauSymbol)continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=SequenceMagicNumber)continue;
      n++;
   }
   return n;
}

string TZ_JsonStringAfter(string text,int start,string key)
{
   string needle="\""+key+"\"";
   int p=StringFind(text,needle,start);if(p<0)return "";
   int colon=StringFind(text,":",p+StringLen(needle));if(colon<0)return "";
   int q1=StringFind(text,"\"",colon+1);if(q1<0)return "";
   int q2=StringFind(text,"\"",q1+1);if(q2<0)return "";
   return StringSubstr(text,q1+1,q2-q1-1);
}

string TZ_ReadinessPrefix(string method)
{
   if(method=="")return "ACTIVE";
   int p=StringFind(method,"|");
   return p>0?StringSubstr(method,0,p):method;
}

void TZ_ReadTwoZoneMap()
{
   string text;
   if(!Get("/analysis",text))return;
   int zonesAt=StringFind(text,"\"zones\"");
   if(zonesAt<0)return;

   int count=0,pos=zonesAt;
   string sellState="NONE",buyState="NONE",sellZone="",buyZone="";
   for(int i=0;i<2;i++)
   {
      int zpos=StringFind(text,"\"zone_id\"",pos);
      if(zpos<0)break;
      string zid=TZ_JsonStringAfter(text,zpos,"zone_id");
      string dir=TZ_JsonStringAfter(text,zpos,"original_direction");
      string method=TZ_JsonStringAfter(text,zpos,"core_method");
      string state=TZ_ReadinessPrefix(method);
      if(dir=="SELL"){sellState=state;sellZone=zid;}
      if(dir=="BUY"){buyState=state;buyZone=zid;}
      count++;
      pos=zpos+10;
   }
   g_tzMapCount=count;
   g_tzSellState=sellState;g_tzBuyState=buyState;
   g_tzSellZone=sellZone;g_tzBuyZone=buyZone;
}

string TZ_SequenceExecutionDisplay()
{
   int openCount=TZ_SequenceOpenPositions();
   string stage=TZ_ReadLocalKV("sequence_state.txt","gate_stage");
   string reason=TZ_ReadLocalKV("sequence_state.txt","gate_reason");
   string authority=TZ_ReadLocalKV("sequence_state.txt","execution_authority");

   if(openCount>0)
      return "MANAGING "+IntegerToString(openCount)+" POSITION"+(openCount==1?"":"S");
   if(stage=="ORDER_SENT")
      return "ORDER SENT";

   bool valueWait=(
      stage=="VALUE" ||
      stage=="VALUE_PD_ARRAY" ||
      stage=="FLIP_VALUE_PD_ARRAY" ||
      StringFind(reason,"WAITING_FOR_VALID_VALUE")>=0 ||
      StringFind(reason,"WAITING_FOR_PULLBACK")>=0
   );
   if(valueWait)return "WAITING FOR VALUE / RETRACE";
   if(stage=="REENTRY_CONFIRMATION")return "WAITING FOR CLOSED M1 VALUE REACTION";
   if(stage=="HANDOFF_CONFIRMATION")return "WAITING FOR CLOSED M1 VALUE REACTION";
   if(stage=="TARGET" && StringFind(reason,"MIN_RR_NOT_MET")>=0)return "ENTRY BLOCKED: MIN RR";
   if(stage=="TARGET" && StringFind(reason,"POST_HANDOFF_OBJECTIVE_ALREADY_TRADED")>=0)return "ENTRY BLOCKED: OBJECTIVE ALREADY TRADED";
   if(stage=="THESIS" && StringFind(reason,"REENTRY_LIMIT_REACHED")>=0)return "THESIS ENTRY LIMIT REACHED";
   if(stage=="SWEEP" || stage=="FLIP_SWEEP")return "WAITING FOR SWEEP";
   if(stage=="MSS_BOS" || stage=="FLIP_MSS_BOS")return "WAITING FOR MSS/BOS";
   if(stage=="DISPLACEMENT" || stage=="FLIP_DISPLACEMENT")return "WAITING FOR DISPLACEMENT";

   if(
      stage=="SAFETY" || stage=="SPREAD" || stage=="RISK" ||
      stage=="TARGET" || stage=="DUPLICATE" || stage=="AUTHORITY" ||
      stage=="DATA" || stage=="MARKET" || stage=="BAR" || stage=="PLAN"
   )
      return "EXECUTION HOLD";

   if(authority=="" || authority=="NONE")
      return g_tzrThesisLocked?"WAITING FOR SEQUENCE AUTHORITY":"NO EXECUTION AUTHORITY";

   if(stage=="" || stage=="UNKNOWN")return "M1 SEQUENCE ACTIVE";
   string display=stage;
   StringReplace(display,"_"," ");
   return display;
}

void TZ_ClearLegacyExecutionOverlay(long chart)
{
   int total=ObjectsTotal(chart,0,-1);
   for(int i=total-1;i>=0;i--)
   {
      string name=ObjectName(chart,i,0,-1);
      string text=ObjectGetString(chart,name,OBJPROP_TEXT);
      bool staleNoTrade=(StringFind(text,"SMC Cloud | NO_TRADE")>=0);
      bool staleZeroZones=(StringFind(text,"SMC Cloud")>=0 && StringFind(text,"zones 0")>=0);
      if(staleNoTrade || staleZeroZones)ObjectDelete(chart,name);
   }
}

void TZ_RenderTwoZoneMap()
{
   if(!ShowTwoZoneMapOnXauM1)return;
   int openCount=TZ_SequenceOpenPositions();
   string status="SMC Cloud | EXECUTION: "+TZ_SequenceExecutionDisplay()+
                 " | POSITIONS "+IntegerToString(openCount);
   status+="\nSMC Cloud | MAP "+IntegerToString(g_tzMapCount)+
           " | SELL "+g_tzSellState+" | BUY "+g_tzBuyState;

   if(g_tzrThesisLocked)
   {
      status+="\nACTIVE THESIS: "+(g_tzrThesisDirection==""?"NONE":g_tzrThesisDirection);
      if(g_tzrThesisStatus!="")status+=" | "+g_tzrThesisStatus;
      if(g_tzrThesisOwnerZoneId!="")status+=" | "+g_tzrThesisOwnerZoneId;
      else status+=" | OWNER OFF MAP";

      if(g_tzrNextObjective>0)
         status+="\nNEXT OBJECTIVE: "+DoubleToString(g_tzrNextObjective,2);
      if(g_tzrNoChase || g_tzrFreshM1Required)
         status+=" | NO CHASE / FRESH M1 REQUIRED";
      if(g_tzrOppositeExecutionBlocked)
         status+="\nNON-OWNER ZONES: WATCH ONLY | EXECUTION BLOCKED";
   }
   else if(g_tzrSelectedZoneId!="")
   {
      status+="\nSELECTED: "+g_tzrSelectedZoneId+" | NO ACQUIRED THESIS LOCK";
   }

   long chart=ChartFirst();
   while(chart>=0)
   {
      if(ChartSymbol(chart)==XauSymbol && ChartPeriod(chart)==PERIOD_M1)
      {
         TZ_ClearLegacyExecutionOverlay(chart);
         ChartSetString(chart,CHART_COMMENT,status);
         ChartRedraw(chart);
      }
      chart=ChartNext(chart);
   }
}

void TZ_WriteBridgeState()
{
   datetime now=TimeTradeServer();
   if(now-g_tzBridgeStateAt<5)return;
   g_tzBridgeStateAt=now;
   FolderCreate("TradeZone");
   int h=FileOpen("TradeZone\\bridge_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return;
   FileWriteString(h,"ts="+IntegerToString((int)now)+"\r\n");
   FileWriteString(h,"version="+TZ_BRIDGE_VERSION+"\r\n");
   FileWriteString(h,"last_snapshot_success="+IntegerToString((int)g_tzLastSnapshotSuccess)+"\r\n");
   FileWriteString(h,"consecutive_failures="+IntegerToString(g_tzSnapshotFailures)+"\r\n");
   FileWriteString(h,"sequence_open_positions="+IntegerToString(TZ_SequenceOpenPositions())+"\r\n");
   FileWriteString(h,"map_count="+IntegerToString(g_tzMapCount)+"\r\n");
   FileWriteString(h,"map_sell_state="+g_tzSellState+"\r\n");
   FileWriteString(h,"map_buy_state="+g_tzBuyState+"\r\n");
   FileWriteString(h,"active_thesis_locked="+(g_tzrThesisLocked?"1":"0")+"\r\n");
   FileWriteString(h,"active_thesis_direction="+g_tzrThesisDirection+"\r\n");
   FileWriteString(h,"active_thesis_owner_zone_id="+g_tzrThesisOwnerZoneId+"\r\n");
   FileClose(h);
}

void TZ_SendHeartbeatV144()
{
   string updater=TZ_ReadLocalKV("updater_status.txt","updater_version");
   string stable=TZ_ReadLocalKV("updater_status.txt","stable_release");
   string installedBridge=TZ_ReadLocalKV("updater_status.txt","installed_bridge_version");
   string installedSequence=TZ_ReadLocalKV("updater_status.txt","installed_sequence_version");
   string desiredBridge=TZ_ReadLocalKV("updater_status.txt","desired_bridge_version");
   string desiredSequence=TZ_ReadLocalKV("updater_status.txt","desired_sequence_version");
   string pending=TZ_ReadLocalKV("updater_status.txt","pending_reload");
   string updateResult=TZ_ReadLocalKV("updater_status.txt","result");
   string lastAction=TZ_ReadLocalKV("updater_status.txt","last_action");

   int openCount=TZ_SequenceOpenPositions();
   string b=StringFormat(
      "{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_DataBridge\",\"version\":\"%s\",\"symbol\":\"%s\",\"account_login\":%I64d,"
      "\"details\":{\"dxy\":\"%s\",\"journal_sync\":true,\"journal_history_backfill\":true,\"sequence_magic\":%I64d,\"sequence_expected_version\":\"%s\","
      "\"sequence_open_positions\":%d,\"paper_only\":true,\"snapshot_logging\":true,\"map_sync\":true,\"map_count\":%d,"
      "\"map_sell_state\":\"%s\",\"map_buy_state\":\"%s\",\"zone_render_contract\":\"%s\",\"execution_ownership_visual\":true,"
      "\"active_thesis_locked\":%s,\"active_thesis_direction\":\"%s\",\"active_thesis_owner_zone_id\":\"%s\","
      "\"last_snapshot_success\":%I64d,\"consecutive_failures\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\","
      "\"installed_sequence_version\":\"%s\",\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\","
      "\"pending_reload\":\"%s\",\"update_result\":\"%s\",\"last_action\":\"%s\"}}",
      (long)TimeTradeServer(),TZ_BRIDGE_VERSION,JsonEscape(XauSymbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),
      JsonEscape(DxySymbol),(long)SequenceMagicNumber,TZ_SEQUENCE_EXPECTED,openCount,g_tzMapCount,
      JsonEscape(g_tzSellState),JsonEscape(g_tzBuyState),TZ_ZONE_RENDER_CONTRACT,
      g_tzrThesisLocked?"true":"false",JsonEscape(g_tzrThesisDirection),JsonEscape(g_tzrThesisOwnerZoneId),
      (long)g_tzLastSnapshotSuccess,g_tzSnapshotFailures,
      JsonEscape(updater),JsonEscape(stable),JsonEscape(installedBridge),JsonEscape(installedSequence),
      JsonEscape(desiredBridge),JsonEscape(desiredSequence),JsonEscape(pending),JsonEscape(updateResult),JsonEscape(lastAction)
   );
   string r;Post("/mt5/heartbeat",b,r);
}

void TZ_LogSnapshot(bool ok,string tag)
{
   MqlTick t;double spread=0.0;
   if(SymbolInfoTick(XauSymbol,t))
   {
      double point=SymbolInfoDouble(XauSymbol,SYMBOL_POINT);
      if(point<=0)point=0.01;
      spread=(t.ask-t.bid)/point;
   }
   if(ok)
   {
      if(LogSuccessfulSnapshots)
         Print("AITS Bridge | SNAPSHOT OK | v",TZ_BRIDGE_VERSION," | zone-render=",TZ_ZONE_RENDER_CONTRACT," | ownership-visual=1 | tag=",tag," | spread=",DoubleToString(spread,1),"pt | failures=0 | map=",g_tzMapCount);
   }
   else
      Print("AITS Bridge | SNAPSHOT FAILED | v",TZ_BRIDGE_VERSION," | tag=",tag," | failures=",g_tzSnapshotFailures);
}

bool TZ_SendSnapshotCycle(string tag)
{
   bool ok=SendSnapshot(tag);
   datetime now=TimeTradeServer();
   if(ok)
   {
      g_tzLastSnapshotSuccess=now;
      g_tzSnapshotFailures=0;
      TZ_LogSnapshot(true,tag);
      return true;
   }

   g_tzSnapshotFailures++;
   TZ_LogSnapshot(false,tag);
   int stale=MathMax(30,RetryAfterStaleSeconds);
   if(g_tzLastSnapshotSuccess==0 || now-g_tzLastSnapshotSuccess>=stale)
   {
      bool retryOk=SendSnapshot("RETRY");
      if(retryOk)
      {
         g_tzLastSnapshotSuccess=TimeTradeServer();
         g_tzSnapshotFailures=0;
         TZ_LogSnapshot(true,"RETRY");
         return true;
      }
      g_tzSnapshotFailures++;
      TZ_LogSnapshot(false,"RETRY");
   }
   return false;
}

int OnInit()
{
   int rc=TZ_BridgeCore_OnInit();
   if(rc!=INIT_SUCCEEDED)return rc;
   TZ_SendSnapshotCycle("V144_VERIFY");
   RefreshPlanContext();
   TZ_ReadTwoZoneMap();
   TZR_RefreshAndRender();
   TZ_RenderTwoZoneMap();
   TZ_WriteBridgeState();
   TZ_SendHeartbeatV144();
   Print("AITS DataBridge runtime v",TZ_BRIDGE_VERSION," active: provenance-safe journal recovery + compile-safe tester guard + execution-truth overlay + V659 zones + ownership visualization.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   TZR_ClearAll();
   TZ_WriteBridgeState();
   TZ_BridgeCore_OnDeinit(reason);
}

void OnTimer()
{
   TZ_SendSnapshotCycle("LIVE");
   RefreshPlanContext();
   BackfillJournalHistory(false);
   TZ_ReadTwoZoneMap();
   TZR_RefreshAndRender();
   TZ_RenderTwoZoneMap();
   MarkPositions();
   TZ_WriteBridgeState();
   TZ_SendHeartbeatV144();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   TZ_BridgeCore_OnTradeTransaction(trans,request,result);
}

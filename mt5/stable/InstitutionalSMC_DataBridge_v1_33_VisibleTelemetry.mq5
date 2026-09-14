#property strict
#property version "1.33"
#property description "DEMO/PAPER telemetry bridge with visible 30-second snapshot status and guarded retry."

#define OnInit TZ_BridgeCore_OnInit
#define OnDeinit TZ_BridgeCore_OnDeinit
#define OnTimer TZ_BridgeCore_OnTimer
#define OnTradeTransaction TZ_BridgeCore_OnTradeTransaction
#include <TradeZoneCore\InstitutionalSMC_DataBridge_v1_31_XAU_DXY_Journal.mq5>
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTradeTransaction

#define TZ_BRIDGE_VERSION "1.33"
#define TZ_SEQUENCE_EXPECTED "3.23"

input bool LogSuccessfulSnapshots=true;
input int RetryAfterStaleSeconds=90;

datetime g_tzBridgeStateAt=0;
datetime g_tzLastSnapshotSuccess=0;
int g_tzSnapshotFailures=0;

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
   FileClose(h);
}

void TZ_SendHeartbeatV133()
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
      "\"details\":{\"dxy\":\"%s\",\"journal_sync\":true,\"sequence_magic\":%I64d,\"sequence_expected_version\":\"%s\","
      "\"sequence_open_positions\":%d,\"paper_only\":true,\"snapshot_logging\":true,\"last_snapshot_success\":%I64d,"
      "\"consecutive_failures\":%d,\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\","
      "\"installed_sequence_version\":\"%s\",\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\","
      "\"pending_reload\":\"%s\",\"update_result\":\"%s\",\"last_action\":\"%s\"}}",
      (long)TimeTradeServer(),TZ_BRIDGE_VERSION,JsonEscape(XauSymbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),
      JsonEscape(DxySymbol),(long)SequenceMagicNumber,TZ_SEQUENCE_EXPECTED,openCount,(long)g_tzLastSnapshotSuccess,g_tzSnapshotFailures,
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
         Print("AITS Bridge | SNAPSHOT OK | v",TZ_BRIDGE_VERSION," | tag=",tag," | spread=",DoubleToString(spread,1),"pt | failures=0");
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
   TZ_SendSnapshotCycle("V133_VERIFY");
   TZ_WriteBridgeState();
   TZ_SendHeartbeatV133();
   Print("AITS DataBridge runtime v",TZ_BRIDGE_VERSION," active: visible 30-second telemetry logging enabled.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   TZ_WriteBridgeState();
   TZ_BridgeCore_OnDeinit(reason);
}

void OnTimer()
{
   TZ_SendSnapshotCycle("LIVE");
   RefreshPlanContext();
   MarkPositions();
   TZ_WriteBridgeState();
   TZ_SendHeartbeatV133();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   TZ_BridgeCore_OnTradeTransaction(trans,request,result);
}

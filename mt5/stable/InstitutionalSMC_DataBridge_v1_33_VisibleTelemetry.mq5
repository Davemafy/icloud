#property strict
#property version "1.33"
#property description "DEMO/PAPER telemetry reliability wrapper: visible snapshot status and guarded retry."

#define OnInit TZ132_OnInit
#define OnDeinit TZ132_OnDeinit
#define OnTimer TZ132_OnTimer
#define OnTradeTransaction TZ132_OnTradeTransaction
#include "InstitutionalSMC_DataBridge_v1_32_RuntimeStatus.mq5"
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTradeTransaction

#define TZ133_VERSION "1.33"

input bool LogSuccessfulSnapshots=true;
input int RetryAfterStaleSeconds=90;

datetime g_tz133LastSuccess=0;
int g_tz133Failures=0;

void TZ133_WriteState()
{
   datetime now=TimeTradeServer();
   FolderCreate("TradeZone");
   int h=FileOpen("TradeZone\\bridge_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return;
   FileWriteString(h,"ts="+IntegerToString((int)now)+"\r\n");
   FileWriteString(h,"version="+TZ133_VERSION+"\r\n");
   FileWriteString(h,"last_snapshot_success="+IntegerToString((int)g_tz133LastSuccess)+"\r\n");
   FileWriteString(h,"consecutive_failures="+IntegerToString(g_tz133Failures)+"\r\n");
   FileWriteString(h,"sequence_open_positions="+IntegerToString(TZ_SequenceOpenPositions())+"\r\n");
   FileClose(h);
}

void TZ133_SendHeartbeat()
{
   string installedSequence=TZ_ReadLocalKV("updater_status.txt","installed_sequence_version");
   string pending=TZ_ReadLocalKV("updater_status.txt","pending_reload");
   string b=StringFormat(
      "{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_DataBridge\",\"version\":\"%s\",\"symbol\":\"%s\",\"account_login\":%I64d,"
      "\"details\":{\"journal_sync\":true,\"paper_only\":true,\"snapshot_logging\":true,\"last_snapshot_success\":%I64d,"
      "\"consecutive_failures\":%d,\"installed_sequence_version\":\"%s\",\"pending_reload\":\"%s\"}}",
      (long)TimeTradeServer(),TZ133_VERSION,JsonEscape(XauSymbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),
      (long)g_tz133LastSuccess,g_tz133Failures,JsonEscape(installedSequence),JsonEscape(pending)
   );
   string r;Post("/mt5/heartbeat",b,r);
}

void TZ133_LogSnapshot(bool ok,string tag)
{
   MqlTick t;
   double spread=0.0;
   if(SymbolInfoTick(XauSymbol,t))
   {
      double point=SymbolInfoDouble(XauSymbol,SYMBOL_POINT);
      if(point<=0)point=0.01;
      spread=(t.ask-t.bid)/point;
   }
   if(ok)
   {
      if(LogSuccessfulSnapshots)
         Print("AITS Bridge | SNAPSHOT OK | v",TZ133_VERSION," | tag=",tag," | spread=",DoubleToString(spread,1),"pt | failures=0");
   }
   else
      Print("AITS Bridge | SNAPSHOT FAILED | v",TZ133_VERSION," | tag=",tag," | failures=",g_tz133Failures);
}

bool TZ133_SendSnapshotCycle(string tag)
{
   bool ok=SendSnapshot(tag);
   datetime now=TimeTradeServer();
   if(ok)
   {
      g_tz133LastSuccess=now;
      g_tz133Failures=0;
      TZ133_LogSnapshot(true,tag);
      return true;
   }

   g_tz133Failures++;
   TZ133_LogSnapshot(false,tag);
   int stale=MathMax(30,RetryAfterStaleSeconds);
   if(g_tz133LastSuccess==0 || now-g_tz133LastSuccess>=stale)
   {
      bool retryOk=SendSnapshot("RETRY");
      if(retryOk)
      {
         g_tz133LastSuccess=TimeTradeServer();
         g_tz133Failures=0;
         TZ133_LogSnapshot(true,"RETRY");
         return true;
      }
      g_tz133Failures++;
      TZ133_LogSnapshot(false,"RETRY");
   }
   return false;
}

int OnInit()
{
   int rc=TZ132_OnInit();
   if(rc!=INIT_SUCCEEDED)return rc;
   TZ133_SendSnapshotCycle("V133_VERIFY");
   TZ133_WriteState();
   TZ133_SendHeartbeat();
   Print("AITS DataBridge runtime v",TZ133_VERSION," active: visible 30-second telemetry logging enabled.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   TZ133_WriteState();
   TZ132_OnDeinit(reason);
}

void OnTimer()
{
   TZ133_SendSnapshotCycle("LIVE");
   RefreshPlanContext();
   MarkPositions();
   TZ133_WriteState();
   TZ133_SendHeartbeat();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   TZ132_OnTradeTransaction(trans,request,result);
}

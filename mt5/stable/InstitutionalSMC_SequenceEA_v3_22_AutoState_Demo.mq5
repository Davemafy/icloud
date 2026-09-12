#property strict
// TradeZone Sequence runtime wrapper v3.22.
// It preserves the validated v3.21 execution core while adding:
// - running-version heartbeat
// - local restart-safety state
// - thesis counter persistence across safe terminal restarts
// - updater telemetry passthrough

#define OnInit TZ_SeqCore_OnInit
#define OnDeinit TZ_SeqCore_OnDeinit
#define OnTimer TZ_SeqCore_OnTimer
#define OnTick TZ_SeqCore_OnTick
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_21_Flip_Reentry_Backtest_Demo.mq5>
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick

#define TZ_SEQUENCE_VERSION "3.22"

datetime g_tzLastStateWrite=0,g_tzLastHeartbeat=0;
string g_tzLoadedStateKey="";

string TZ_JsonEscape(string s)
{
   StringReplace(s,"\\","\\\\");StringReplace(s,"\"","\\\"");StringReplace(s,"\r"," ");StringReplace(s,"\n"," ");return s;
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
   FileClose(h);StringTrimLeft(value);StringTrimRight(value);return value;
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
   string p=TZ_StatePrefix();if(p=="")return;
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
   char data[],result[];string rh;
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
      "\"details\":{\"paper_only\":true,\"restart_safe\":%s,\"active_sequence\":%s,\"open_positions\":%d,"
      "\"state_persisted\":true,\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"plan_valid\":%s,"
      "\"primary_entries\":%d,\"reentries\":%d,\"flip_primary_entries\":%d,\"flip_reentries\":%d,"
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\","
      "\"installed_sequence_version\":\"%s\",\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\","
      "\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),
      safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",
      g_primaryEntries,g_reentries,g_flipPrimaryEntries,g_flipReentries,
      TZ_JsonEscape(updater),TZ_JsonEscape(stable),TZ_JsonEscape(installedBridge),TZ_JsonEscape(installedSequence),
      TZ_JsonEscape(desiredBridge),TZ_JsonEscape(desiredSequence),TZ_JsonEscape(pending),TZ_JsonEscape(updateResult)
   );
   string r;TZ_Post("/mt5/heartbeat",body,r);
}

void TZ_PreCoreSync()
{
   if(IsTester())return;
   if(OperatingMode==LIVE_CLOUD)RefreshPlan();
   TZ_LoadPersistentState();
}

int OnInit()
{
   int rc=TZ_SeqCore_OnInit();
   if(rc!=INIT_SUCCEEDED)return rc;
   TZ_PreCoreSync();
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SendSequenceHeartbeat();
   Print("TradeZone Sequence runtime version ",TZ_SEQUENCE_VERSION," active with persistent restart-safe state.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SeqCore_OnDeinit(reason);
}

void OnTimer()
{
   TZ_PreCoreSync();
   TZ_SeqCore_OnTimer();
   TZ_LoadPersistentState();
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SendSequenceHeartbeat();
}

void OnTick()
{
   TZ_PreCoreSync();
   TZ_SeqCore_OnTick();
   TZ_SavePersistentState();
   TZ_WriteSequenceState();
   TZ_SendSequenceHeartbeat();
}

#property strict
#property version   "3.24"
#property description "DEMO/PAPER XAU M1: v3.23 execution core with cloud MAP/READY status sync."

#define OnInit TZ323_OnInit
#define OnDeinit TZ323_OnDeinit
#define OnTimer TZ323_OnTimer
#define OnTick TZ323_OnTick
#include <TradeZoneCore\InstitutionalSMC_SequenceEA_v3_23_MultiModel_Demo.mq5>
#undef OnInit
#undef OnDeinit
#undef OnTimer
#undef OnTick

#undef TZ_SEQUENCE_VERSION
#define TZ_SEQUENCE_VERSION "3.24"

datetime g_tz24LastStatusPoll=0;
int g_tz24MapZones=0;
int g_tz24ReadyZones=0;
string g_tz24PlanMode="NO_TRADE";
bool g_tz24LiveBlock=false;

int TZ24_Count(string text,string needle)
{
   if(needle=="")return 0;
   int n=0,pos=0;
   while(true)
   {
      int p=StringFind(text,needle,pos);
      if(p<0)break;
      n++;
      pos=p+StringLen(needle);
   }
   return n;
}

void TZ24_RefreshCloudStatus(bool force=false)
{
   if(IsTester()||OperatingMode!=LIVE_CLOUD)return;
   datetime now=TimeTradeServer();
   if(now<=0)now=TimeCurrent();
   int cadence=(int)MathMax(5,PollSeconds);
   if(!force && now-g_tz24LastStatusPoll<cadence)return;
   g_tz24LastStatusPoll=now;

   string plan;
   if(HttpGet("/mt5/plan",plan))
   {
      string mode=KV(plan,"ea_mode");
      if(mode!="")g_tz24PlanMode=mode;
      g_tz24LiveBlock=(KV(plan,"live_block")=="1");
   }

   string analysis;
   if(HttpGet("/analysis",analysis))
   {
      StringReplace(analysis," ","");
      StringReplace(analysis,"\r","");
      StringReplace(analysis,"\n","");
      g_tz24MapZones=TZ24_Count(analysis,"\"zone_id\":");
      g_tz24ReadyZones=
         TZ24_Count(analysis,"\"core_method\":\"ACTIONABLE")+
         TZ24_Count(analysis,"\"core_method\":\"M1_READY");
   }
}

void TZ24_UpdateChartStatus()
{
   if(IsTester())return;
   string mode=g_tz24LiveBlock?"BLOCKED":g_tz24PlanMode;
   if(mode=="")mode="NO_TRADE";
   Comment(
      "SMC Cloud | ",mode,
      " | MAP ",IntegerToString(g_tz24MapZones),
      " | READY ",IntegerToString(g_tz24ReadyZones)
   );
}

void TZ24_WriteSequenceState()
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
   FileWriteString(h,"plan_mode="+g_tz24PlanMode+"\r\n");
   FileWriteString(h,"map_zone_count="+IntegerToString(g_tz24MapZones)+"\r\n");
   FileWriteString(h,"ready_zone_count="+IntegerToString(g_tz24ReadyZones)+"\r\n");
   FileWriteString(h,"cloud_regime="+g_tzCloudRegime+"\r\n");
   FileWriteString(h,"local_regime="+g_tzLastLocalRegime+"\r\n");
   FileWriteString(h,"last_execution_model="+g_tzLastModel+"\r\n");
   FileClose(h);
}

void TZ24_SendSequenceHeartbeat()
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
      "\"details\":{\"paper_only\":true,\"restart_safe\":%s,\"active_sequence\":%s,\"open_positions\":%d,"
      "\"state_persisted\":true,\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"plan_valid\":%s,"
      "\"plan_mode\":\"%s\",\"map_zone_count\":%d,\"ready_zone_count\":%d,"
      "\"cloud_regime\":\"%s\",\"local_regime\":\"%s\",\"last_execution_model\":\"%s\","
      "\"updater_version\":\"%s\",\"stable_release\":\"%s\",\"installed_bridge_version\":\"%s\","
      "\"installed_sequence_version\":\"%s\",\"desired_bridge_version\":\"%s\",\"desired_sequence_version\":\"%s\","
      "\"pending_reload\":\"%s\",\"update_result\":\"%s\"}}",
      (long)now,TZ_SEQUENCE_VERSION,TZ_JsonEscape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),
      safe?"true":"false",openCount>0?"true":"false",openCount,
      TZ_JsonEscape(g_plan.analysis_id),TZ_JsonEscape(g_plan.zone_id),g_plan.valid?"true":"false",
      TZ_JsonEscape(g_tz24PlanMode),g_tz24MapZones,g_tz24ReadyZones,
      TZ_JsonEscape(g_tzCloudRegime),TZ_JsonEscape(g_tzLastLocalRegime),TZ_JsonEscape(g_tzLastModel),
      TZ_JsonEscape(updater),TZ_JsonEscape(stable),TZ_JsonEscape(installedBridge),TZ_JsonEscape(installedSequence),
      TZ_JsonEscape(desiredBridge),TZ_JsonEscape(desiredSequence),TZ_JsonEscape(pending),TZ_JsonEscape(updateResult)
   );
   string rr;
   TZ_Post("/mt5/heartbeat",body,rr);
}

int OnInit()
{
   int rc=TZ_SeqCore_OnInit();
   if(rc!=INIT_SUCCEEDED)return rc;
   if(AltModelRiskMultiplier<=0||AltModelRiskMultiplier>1.0)return INIT_PARAMETERS_INCORRECT;
   if(MomentumRetraceMin<=0||MomentumRetraceMax>=1||MomentumRetraceMin>=MomentumRetraceMax)return INIT_PARAMETERS_INCORRECT;
   TZ_PreCoreSync();
   TZ_LoadExecutionProfile();
   TZ_LoadPersistentState();
   TZ_SavePersistentState();
   TZ24_RefreshCloudStatus(true);
   TZ24_WriteSequenceState();
   TZ24_SendSequenceHeartbeat();
   TZ24_UpdateChartStatus();
   Print("TradeZone Sequence runtime ",TZ_SEQUENCE_VERSION," active: cloud MAP/READY status synchronized; v3.23 execution core unchanged.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   TZ_SavePersistentState();
   TZ24_WriteSequenceState();
   Comment("");
   TZ_SeqCore_OnDeinit(reason);
}

void OnTimer()
{
   TZ_PreCoreSync();
   TZ_SeqCore_OnTimer();
   TZ_LoadExecutionProfile();
   TZ_LoadPersistentState();
   TZ_SavePersistentState();
   TZ24_RefreshCloudStatus();
   TZ24_WriteSequenceState();
   TZ24_SendSequenceHeartbeat();
   TZ24_UpdateChartStatus();
}

void OnTick()
{
   TZ_PreCoreSync();
   ManagePositions();
   Evaluate();
   TZ_SavePersistentState();
   TZ24_RefreshCloudStatus();
   TZ24_WriteSequenceState();
   TZ24_SendSequenceHeartbeat();
   TZ24_UpdateChartStatus();
}

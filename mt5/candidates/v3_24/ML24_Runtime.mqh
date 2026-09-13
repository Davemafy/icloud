void ML24_WriteState(string localRegime)
{
   FolderCreate("TradeZone");int h=FileOpen("TradeZone\\ml_observer_state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);if(h==INVALID_HANDLE)return;
   FileWriteString(h,"ts="+IntegerToString((int)TimeCurrent())+"\r\n");
   FileWriteString(h,"version="+ML24_VERSION+"\r\n");
   FileWriteString(h,"mode=SHADOW_OBSERVATION_ONLY\r\n");
   FileWriteString(h,"execution_authority=0\r\n");
   FileWriteString(h,"analysis_id="+g_plan.analysis_id+"\r\n");
   FileWriteString(h,"zone_id="+g_plan.zone_id+"\r\n");
   FileWriteString(h,"cloud_regime="+ml24_cloud_regime+"\r\n");
   FileWriteString(h,"local_regime="+localRegime+"\r\n");
   FileWriteString(h,"packets_sent="+IntegerToString(ml24_packets_sent)+"\r\n");
   FileWriteString(h,"post_errors="+IntegerToString(ml24_post_errors)+"\r\n");
   FileWriteString(h,"last_bar="+IntegerToString((int)ml24_last_bar)+"\r\n");
   FileClose(h);
}

void ML24_Heartbeat()
{
   datetime now=TimeCurrent();if(now-ml24_last_heartbeat<30)return;ml24_last_heartbeat=now;
   string runtimeVer=ML24_ReadState("version");
   string body=StringFormat("{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_MLObserver\",\"version\":\"%s\",\"symbol\":\"%s\",\"account_login\":%I64d,\"details\":{\"paper_only\":true,\"observation_only\":true,\"execution_authority\":false,\"feature_contract\":\"V6_4_MLF1\",\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"runtime_sequence_version\":\"%s\",\"packets_sent\":%d,\"post_errors\":%d}}",(long)now,ML24_VERSION,ML24_Escape(_Symbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),ML24_Escape(g_plan.analysis_id),ML24_Escape(g_plan.zone_id),ML24_Escape(runtimeVer),ml24_packets_sent,ml24_post_errors);
   string response;ML24_Post("/mt5/heartbeat",body,response);
}

int OnInit()
{
   if(_Period!=PERIOD_M1){Print("ML Observer v3.24: attach to XAUUSD M1 only.");return INIT_PARAMETERS_INCORRECT;}
   if(!IsDemo()){Print("ML Observer v3.24 is DEMO/PAPER ONLY.");return INIT_FAILED;}
   if(OperatingMode!=LIVE_CLOUD){Print("ML Observer v3.24 is live-cloud shadow telemetry only.");return INIT_PARAMETERS_INCORRECT;}
   if(CloudApiKey==""){Print("ML Observer v3.24: CloudApiKey is empty.");return INIT_PARAMETERS_INCORRECT;}
   if(MomentumRetraceMin<=0||MomentumRetraceMax>=1||MomentumRetraceMin>=MomentumRetraceMax)return INIT_PARAMETERS_INCORRECT;
   EventSetTimer(MathMax(5,ObserverPollSeconds));
   ML24_RefreshContext(true);
   ML24_Heartbeat();
   Print("TradeZone ML Observer v3.24 active. SHADOW ONLY: no order placement, no SL/TP modification, no trade management.");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){EventKillTimer();ML24_WriteState("STOPPED");}
void OnTimer(){ML24_RefreshContext(false);ML24_ObserveClosedBar();ML24_Heartbeat();}
void OnTick(){/* Timer-driven observation keeps telemetry off the v3.23 execution OnTick path. */}

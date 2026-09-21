#property strict
#property version "1.31"
#property description "DEMO/PAPER read-only market + journal telemetry bridge for Institutional SMC Cloud."

#ifndef TZ_JOURNAL_BRIDGE_VERSION
#define TZ_JOURNAL_BRIDGE_VERSION "1.31"
#endif

input string CloudBaseUrl="https://YOUR-SERVICE.up.railway.app";
input string CloudApiKey="";
input string XauSymbol="XAUUSD";
input string DxySymbol="DXYUSD";
input int SendEverySeconds=30;
input int HttpTimeoutMs=8000;
input int BarsD1=280;
input int BarsH4=600;
input int BarsH1=600;
input int BarsM15=520;
input bool SendCalendarNews=true;
input int NewsWindowHours=24;

// Journal telemetry only. This does not place, change, or close orders.
input bool EnableJournalSync=true;
input ulong SequenceMagicNumber=5632001;
input string SequenceEaVersion="3.21"; // legacy fallback only; live journal reads TradeZone\\sequence_state.txt
input int JournalMarkEverySeconds=60;
input bool EnableJournalHistoryBackfill=true;
input int JournalBackfillDays=14;
input int JournalBackfillEverySeconds=900;
input int JournalBackfillMaxDeals=2000;

string RuntimeStateValue(string fileName,string key)
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
string JournalSequenceVersion()
{
   string v=RuntimeStateValue("sequence_state.txt","version");
   return v!=""?v:SequenceEaVersion;
}

string g_analysisId="",g_zoneId="",g_grade="",g_cloudVersion="";
datetime g_lastMark=0;
datetime g_lastJournalBackfill=0;
int g_lastBackfillEvents=0;
ulong g_posId[];
string g_posTag[],g_posAnalysis[],g_posZone[];

string JsonEscape(string s)
{
   StringReplace(s,"\\","\\\\");StringReplace(s,"\"","\\\"");StringReplace(s,"\r"," ");StringReplace(s,"\n"," ");return s;
}
string KV(string text,string key)
{
   string needle=key+"=";int p=StringFind(text,needle);if(p<0)return "";
   p+=StringLen(needle);int e=StringFind(text,"\n",p);if(e<0)e=StringLen(text);
   string v=StringSubstr(text,p,e-p);StringTrimLeft(v);StringTrimRight(v);return v;
}
double ATRValue(string sym,ENUM_TIMEFRAMES tf,int period=14)
{
   int h=iATR(sym,tf,period);if(h==INVALID_HANDLE)return 0;double b[];ArraySetAsSeries(b,true);double v=0;if(CopyBuffer(h,0,1,1,b)==1)v=b[0];IndicatorRelease(h);return v;
}
string BarsJson(string sym,ENUM_TIMEFRAMES tf,int count)
{
   MqlRates r[];int n=CopyRates(sym,tf,1,count,r);if(n<=0)return "[]";string s="[";
   for(int i=0;i<n;i++){if(i>0)s+=",";s+=StringFormat("{\"ts\":%I64d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"tick_volume\":%I64d}",(long)r[i].time,r[i].open,r[i].high,r[i].low,r[i].close,(long)r[i].tick_volume);}
   return s+"]";
}
string NewsJson()
{
   if(!SendCalendarNews)return "[]";datetime now=TimeTradeServer(),from=now-NewsWindowHours*3600,to=now+NewsWindowHours*3600;MqlCalendarValue vals[];
   int n=CalendarValueHistory(vals,from,to,"","USD");if(n<=0)return "[]";string s="[";int used=0;
   for(int i=0;i<n;i++){MqlCalendarEvent ev;if(!CalendarEventById(vals[i].event_id,ev))continue;if(ev.importance!=CALENDAR_IMPORTANCE_HIGH)continue;if(used++>0)s+=",";s+=StringFormat("{\"ts\":%I64d,\"currency\":\"USD\",\"title\":\"%s\",\"impact\":\"HIGH\"}",(long)vals[i].time,JsonEscape(ev.name));}
   return s+"]";
}
bool Post(string path,string body,string &response)
{
   string url=CloudBaseUrl+path,headers="Content-Type: application/json\r\nX-API-Key: "+CloudApiKey+"\r\n";char data[],result[];string rh;
   StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);if(ArraySize(data)>0)ArrayResize(data,ArraySize(data)-1);
   ResetLastError();int code=WebRequest("POST",url,headers,HttpTimeoutMs,data,result,rh);response=CharArrayToString(result,0,-1,CP_UTF8);
   if(code!=200){Print("SMC Bridge POST ",path," HTTP=",code," err=",GetLastError());return false;}return true;
}
bool Get(string path,string &response)
{
   string url=CloudBaseUrl+path,headers="X-API-Key: "+CloudApiKey+"\r\nAccept: text/plain\r\n";char data[],result[];string rh;
   ResetLastError();int code=WebRequest("GET",url,headers,HttpTimeoutMs,data,result,rh);response=CharArrayToString(result,0,-1,CP_UTF8);
   return code==200;
}
bool SendSnapshot(string reason)
{
   MqlTick t;if(!SymbolInfoTick(XauSymbol,t))return false;double point=SymbolInfoDouble(XauSymbol,SYMBOL_POINT);if(point<=0)point=0.01;double spread=(t.ask-t.bid)/point;
   string body=StringFormat("{\"protocol\":6,\"kind\":\"FULL_HISTORY\",\"reason\":\"%s\",\"sent_at\":%I64d,\"xau_symbol\":\"%s\",\"dxy_symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"spread_points\":%.2f,\"point\":%.5f,\"atr_h1\":%.5f,\"atr_m15\":%.5f,",JsonEscape(reason),(long)TimeTradeServer(),JsonEscape(XauSymbol),JsonEscape(DxySymbol),t.bid,t.ask,spread,point,ATRValue(XauSymbol,PERIOD_H1),ATRValue(XauSymbol,PERIOD_M15));
   body+="\"xau_d1\":"+BarsJson(XauSymbol,PERIOD_D1,BarsD1)+",";
   body+="\"xau_h4\":"+BarsJson(XauSymbol,PERIOD_H4,BarsH4)+",";
   body+="\"xau_h1\":"+BarsJson(XauSymbol,PERIOD_H1,BarsH1)+",";
   body+="\"xau_m15\":"+BarsJson(XauSymbol,PERIOD_M15,BarsM15)+",";
   body+="\"dxy_d1\":"+BarsJson(DxySymbol,PERIOD_D1,BarsD1)+",";
   body+="\"dxy_h4\":"+BarsJson(DxySymbol,PERIOD_H4,BarsH4)+",";
   body+="\"dxy_h1\":"+BarsJson(DxySymbol,PERIOD_H1,BarsH1)+",";
   body+="\"news\":"+NewsJson()+"}";
   string r;return Post("/market/snapshot",body,r);
}
void SendHeartbeat()
{
   string b=StringFormat("{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_DataBridge\",\"version\":\"1.31\",\"symbol\":\"%s\",\"account_login\":%I64d,\"details\":{\"dxy\":\"%s\",\"journal_sync\":true,\"sequence_magic\":%I64d,\"sequence_expected_version\":\"%s\",\"paper_only\":true}}",(long)TimeTradeServer(),JsonEscape(XauSymbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(DxySymbol),(long)SequenceMagicNumber,JsonEscape(JournalSequenceVersion()));
   string r;Post("/mt5/heartbeat",b,r);
}
void RefreshPlanContext()
{
   if(!EnableJournalSync)return;string text;if(!Get("/mt5/plan",text))return;
   string a=KV(text,"analysis_id"),z=KV(text,"zone_id"),cv=KV(text,"cloud_version");
   if(a!="")g_analysisId=a;
   if(z!="")g_zoneId=z;
   if(cv!="")g_cloudVersion=cv;
   g_grade=KV(text,"grade");
}
string SetupTag(string comment)
{
   string tags[10]={"FR2","FR1","F0","R2","R1","P0","S0","L0","C0","E0"};
   for(int i=0;i<10;i++)if(StringFind(comment," "+tags[i])>=0||StringFind(comment,tags[i])==0)return tags[i];
   return "UNKNOWN";
}
string SetupName(string tag)
{
   if(tag=="P0")return "PRIMARY";
   if(tag=="R1")return "REENTRY_1";
   if(tag=="R2")return "REENTRY_2";
   if(tag=="F0")return "ZONE_FLIP";
   if(tag=="FR1")return "FLIP_REENTRY_1";
   if(tag=="FR2")return "FLIP_REENTRY_2";
   if(tag=="S0")return "ZONE_SWEEP_CONTINUATION";
   if(tag=="L0")return "LIQUIDITY_REVERSAL";
   if(tag=="C0")return "CONTINUATION_RESCUE";
   if(tag=="E0")return "ESCAPE_PULLBACK";
   return "UNKNOWN";
}
int TrackIndex(ulong pid){for(int i=0;i<ArraySize(g_posId);i++)if(g_posId[i]==pid)return i;return -1;}
int EnsureTrack(ulong pid,string tag,string aid,string zid)
{
   int i=TrackIndex(pid);if(i>=0)return i;int n=ArraySize(g_posId);ArrayResize(g_posId,n+1);ArrayResize(g_posTag,n+1);ArrayResize(g_posAnalysis,n+1);ArrayResize(g_posZone,n+1);g_posId[n]=pid;g_posTag[n]=tag;g_posAnalysis[n]=aid;g_posZone[n]=zid;return n;
}
string TradeId(string aid,string zid,string tag){if(aid=="")aid="NO_ANALYSIS";if(zid=="")zid="NO_ZONE";return aid+"|"+zid+"|"+tag;}
string CanonicalTradeId(ulong pid){return "MT5POS|"+StringFormat("%I64d",(long)AccountInfoInteger(ACCOUNT_LOGIN))+"|"+StringFormat("%I64d",(long)pid);}
string EventUidDeal(string event,ulong deal){return event+"|DEAL|"+StringFormat("%I64d",(long)deal);}
string EventUidPosition(string event,ulong pid){return event+"|POSITION|"+StringFormat("%I64d",(long)pid);}
string PositionMetaFile(ulong pid)
{
   return "position_meta_"+StringFormat("%I64d",(long)pid)+".txt";
}
void SavePositionMeta(ulong pid,string tag,string aid,string zid,string grade,string bridgeVer,string sequenceVer,string cloudVer)
{
   if(IsTester()||pid==0)return;
   FolderCreate("TradeZone");
   int h=FileOpen("TradeZone\\"+PositionMetaFile(pid),FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE)return;
   FileWriteString(h,"position_id="+StringFormat("%I64d",(long)pid)+"\r\n");
   FileWriteString(h,"analysis_id="+aid+"\r\n");
   FileWriteString(h,"zone_id="+zid+"\r\n");
   FileWriteString(h,"tag="+tag+"\r\n");
   FileWriteString(h,"grade="+grade+"\r\n");
   FileWriteString(h,"execution_bridge_version="+bridgeVer+"\r\n");
   FileWriteString(h,"execution_sequence_version="+sequenceVer+"\r\n");
   FileWriteString(h,"execution_cloud_version="+cloudVer+"\r\n");
   FileClose(h);
}
bool LoadPositionMeta(ulong pid,string &tag,string &aid,string &zid,string &grade,string &bridgeVer,string &sequenceVer,string &cloudVer)
{
   string fileName=PositionMetaFile(pid);
   string savedPid=RuntimeStateValue(fileName,"position_id");
   if(savedPid=="")return false;
   aid=RuntimeStateValue(fileName,"analysis_id");
   zid=RuntimeStateValue(fileName,"zone_id");
   tag=RuntimeStateValue(fileName,"tag");
   grade=RuntimeStateValue(fileName,"grade");
   bridgeVer=RuntimeStateValue(fileName,"execution_bridge_version");
   sequenceVer=RuntimeStateValue(fileName,"execution_sequence_version");
   cloudVer=RuntimeStateValue(fileName,"execution_cloud_version");
   return true;
}
bool SendJournalAt(datetime eventTs,string event,double price,string aid,string zid,string details)
{
   if(!EnableJournalSync)return false;string body=StringFormat("{\"ts\":%I64d,\"event\":\"%s\",\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"price\":%.5f,\"details\":%s}",(long)eventTs,JsonEscape(event),JsonEscape(aid),JsonEscape(zid),price,details);string r;return Post("/mt5/feedback",body,r);
}
bool SendJournal(string event,double price,string aid,string zid,string details)
{
   return SendJournalAt(TimeTradeServer(),event,price,aid,zid,details);
}
bool AnyOpenTracked(string aid,string zid,string tag)
{
   for(int i=PositionsTotal()-1;i>=0;i--){ulong ticket=PositionGetTicket(i);if(!ticket)continue;if(PositionGetString(POSITION_SYMBOL)!=XauSymbol||(ulong)PositionGetInteger(POSITION_MAGIC)!=SequenceMagicNumber)continue;ulong pid=(ulong)PositionGetInteger(POSITION_IDENTIFIER);int k=TrackIndex(pid);if(k>=0&&g_posAnalysis[k]==aid&&g_posZone[k]==zid&&g_posTag[k]==tag)return true;}return false;
}
void MarkPositions()
{
   if(!EnableJournalSync)return;
   datetime now=TimeTradeServer();
   if(now-g_lastMark<JournalMarkEverySeconds)return;
   g_lastMark=now;
   MqlTick tk;if(!SymbolInfoTick(XauSymbol,tk))return;

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);if(!ticket)continue;
      if(PositionGetString(POSITION_SYMBOL)!=XauSymbol)continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=SequenceMagicNumber)continue;

      ulong pid=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
      string comment=PositionGetString(POSITION_COMMENT),tag=SetupTag(comment);
      int k=TrackIndex(pid);if(k<0)k=EnsureTrack(pid,tag,g_analysisId,g_zoneId);
      string aid=g_posAnalysis[k],zid=g_posZone[k],grade="",execBridge="",execSeq="",execCloud="";
      string metaTag=tag,metaAid=aid,metaZid=zid;
      bool hasMeta=LoadPositionMeta(pid,metaTag,metaAid,metaZid,grade,execBridge,execSeq,execCloud);
      if(hasMeta)
      {
         tag=metaTag;aid=metaAid;zid=metaZid;
      }
      else
      {
         grade=g_grade;
         execBridge=TZ_JOURNAL_BRIDGE_VERSION;
         execSeq=JournalSequenceVersion();
         execCloud=g_cloudVersion;
      }

      double open=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP);
      double vol=PositionGetDouble(POSITION_VOLUME),profit=PositionGetDouble(POSITION_PROFIT);
      ENUM_POSITION_TYPE pt=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      string dir=pt==POSITION_TYPE_BUY?"BUY":"SELL";
      double mark=pt==POSITION_TYPE_BUY?tk.bid:tk.ask;
      string metadataSource=hasMeta?"LOCAL_POSITION_METADATA":"LIVE_RUNTIME_CONTEXT";
      string d=StringFormat(
         "{\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\","
         "\"direction\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,\"volume\":%.4f,"
         "\"entry_price\":%.5f,\"current_sl\":%.5f,\"tp\":%.5f,\"floating_profit\":%.2f,"
         "\"event_provenance\":\"LIVE_MT5\",\"metadata_source\":\"%s\","
         "\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\","
         "\"execution_cloud_version\":\"%s\",\"comment\":\"%s\"}",
         JsonEscape(CanonicalTradeId(pid)),JsonEscape(TradeId(aid,zid,tag)),JsonEscape(SetupName(tag)),JsonEscape(tag),
         dir,JsonEscape(grade),(long)pid,vol,open,sl,tp,profit,metadataSource,
         JsonEscape(execBridge),JsonEscape(execSeq),JsonEscape(execCloud),JsonEscape(comment)
      );
      SendJournal("POSITION_MARK",mark,aid,zid,d);
   }
}

bool SequencePositionIdentifierOpen(ulong pid)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);if(!ticket)continue;
      if(PositionGetString(POSITION_SYMBOL)!=XauSymbol)continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=SequenceMagicNumber)continue;
      if((ulong)PositionGetInteger(POSITION_IDENTIFIER)==pid)return true;
   }
   return false;
}

void BackfillJournalHistory(bool force=false)
{
   if(!EnableJournalSync||!EnableJournalHistoryBackfill)return;
   datetime now=TimeTradeServer();
   if(!force && g_lastJournalBackfill>0 && now-g_lastJournalBackfill<MathMax(60,JournalBackfillEverySeconds))return;
   g_lastJournalBackfill=now;g_lastBackfillEvents=0;
   datetime from=now-(datetime)(MathMax(1,JournalBackfillDays)*86400);
   if(!HistorySelect(from,now))return;

   int total=HistoryDealsTotal(),inspected=0,maxDeals=MathMax(100,JournalBackfillMaxDeals);
   for(int i=total-1;i>=0 && inspected<maxDeals;i--)
   {
      ulong deal=HistoryDealGetTicket(i);if(!deal)continue;
      if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=SequenceMagicNumber)continue;
      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=XauSymbol)continue;
      inspected++;

      ulong pid=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);if(!pid)continue;
      ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
      ENUM_DEAL_REASON reason=(ENUM_DEAL_REASON)HistoryDealGetInteger(deal,DEAL_REASON);
      ENUM_DEAL_TYPE dtype=(ENUM_DEAL_TYPE)HistoryDealGetInteger(deal,DEAL_TYPE);
      datetime eventTs=(datetime)HistoryDealGetInteger(deal,DEAL_TIME);
      string comment=HistoryDealGetString(deal,DEAL_COMMENT),tag=SetupTag(comment);
      string aid="MT5_HISTORY",zid="",grade="",execBridge="",execSeq="",execCloud="";
      string metaTag=tag,metaAid=aid,metaZid=zid;
      bool hasMeta=LoadPositionMeta(pid,metaTag,metaAid,metaZid,grade,execBridge,execSeq,execCloud);
      if(hasMeta)
      {
         tag=metaTag;aid=metaAid;zid=metaZid;
      }
      else
      {
         int k=TrackIndex(pid);
         if(k>=0){aid=g_posAnalysis[k];zid=g_posZone[k];tag=g_posTag[k];}
      }

      string metadataSource=hasMeta?"LOCAL_POSITION_METADATA":(tag!="UNKNOWN"?"MT5_COMMENT":"UNAVAILABLE_FROM_MT5_HISTORY");
      double price=HistoryDealGetDouble(deal,DEAL_PRICE),vol=HistoryDealGetDouble(deal,DEAL_VOLUME);
      double profit=HistoryDealGetDouble(deal,DEAL_PROFIT),commission=HistoryDealGetDouble(deal,DEAL_COMMISSION),swap=HistoryDealGetDouble(deal,DEAL_SWAP);
      string canonical=CanonicalTradeId(pid),campaign=TradeId(aid,zid,tag),setup=SetupName(tag);
      string recoverySeq=JournalSequenceVersion();

      if(entry==DEAL_ENTRY_IN)
      {
         string dir=dtype==DEAL_TYPE_BUY?"BUY":"SELL";
         string d=StringFormat(
            "{\"event_uid\":\"%s\",\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\","
            "\"tag\":\"%s\",\"direction\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,"
            "\"deal_id\":%I64d,\"volume\":%.4f,\"recovered_from_mt5_history\":true,"
            "\"event_provenance\":\"MT5_HISTORY_RECOVERY\",\"metadata_source\":\"%s\","
            "\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\",\"execution_cloud_version\":\"%s\","
            "\"recovery_bridge_version\":\"%s\",\"recovery_sequence_version\":\"%s\",\"recovery_cloud_version\":\"%s\","
            "\"comment\":\"%s\"}",
            JsonEscape(EventUidDeal("ENTRY_OPENED",deal)),JsonEscape(canonical),JsonEscape(campaign),JsonEscape(setup),
            JsonEscape(tag),dir,JsonEscape(grade),(long)pid,(long)deal,vol,metadataSource,
            JsonEscape(execBridge),JsonEscape(execSeq),JsonEscape(execCloud),
            TZ_JOURNAL_BRIDGE_VERSION,JsonEscape(recoverySeq),JsonEscape(g_cloudVersion),JsonEscape(comment)
         );
         if(SendJournalAt(eventTs,"ENTRY_OPENED",price,aid,zid,d))g_lastBackfillEvents++;
         continue;
      }

      string ev="POSITION_EXIT";
      if(reason==DEAL_REASON_TP)ev="TP_HIT";
      else if(reason==DEAL_REASON_SL)ev="SL_HIT";
      double net=profit+commission+swap;
      string d=StringFormat(
         "{\"event_uid\":\"%s\",\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\","
         "\"tag\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,\"deal_id\":%I64d,\"volume\":%.4f,"
         "\"net_profit\":%.2f,\"recovered_from_mt5_history\":true,\"event_provenance\":\"MT5_HISTORY_RECOVERY\","
         "\"metadata_source\":\"%s\",\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\","
         "\"execution_cloud_version\":\"%s\",\"recovery_bridge_version\":\"%s\","
         "\"recovery_sequence_version\":\"%s\",\"recovery_cloud_version\":\"%s\",\"comment\":\"%s\"}",
         JsonEscape(EventUidDeal(ev,deal)),JsonEscape(canonical),JsonEscape(campaign),JsonEscape(setup),JsonEscape(tag),
         JsonEscape(grade),(long)pid,(long)deal,vol,net,metadataSource,
         JsonEscape(execBridge),JsonEscape(execSeq),JsonEscape(execCloud),TZ_JOURNAL_BRIDGE_VERSION,
         JsonEscape(recoverySeq),JsonEscape(g_cloudVersion),JsonEscape(comment)
      );
      if(SendJournalAt(eventTs,ev,price,aid,zid,d))g_lastBackfillEvents++;

      if(!SequencePositionIdentifierOpen(pid))
      {
         string closed=StringFormat(
            "{\"event_uid\":\"%s\",\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\","
            "\"tag\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,\"recovered_from_mt5_history\":true,"
            "\"event_provenance\":\"MT5_HISTORY_RECOVERY\",\"metadata_source\":\"%s\","
            "\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\",\"execution_cloud_version\":\"%s\","
            "\"recovery_bridge_version\":\"%s\",\"recovery_sequence_version\":\"%s\",\"recovery_cloud_version\":\"%s\"}",
            JsonEscape(EventUidPosition("TRADE_CLOSED",pid)),JsonEscape(canonical),JsonEscape(campaign),JsonEscape(setup),
            JsonEscape(tag),JsonEscape(grade),(long)pid,metadataSource,
            JsonEscape(execBridge),JsonEscape(execSeq),JsonEscape(execCloud),TZ_JOURNAL_BRIDGE_VERSION,
            JsonEscape(recoverySeq),JsonEscape(g_cloudVersion)
         );
         if(SendJournalAt(eventTs,"TRADE_CLOSED",price,aid,zid,closed))g_lastBackfillEvents++;
      }
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(!EnableJournalSync||trans.type!=TRADE_TRANSACTION_DEAL_ADD||trans.deal==0)return;
   ulong deal=trans.deal;if(!HistoryDealSelect(deal))return;
   if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=SequenceMagicNumber)return;
   if(HistoryDealGetString(deal,DEAL_SYMBOL)!=XauSymbol)return;

   ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
   ENUM_DEAL_REASON reason=(ENUM_DEAL_REASON)HistoryDealGetInteger(deal,DEAL_REASON);
   ulong pid=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
   string comment=HistoryDealGetString(deal,DEAL_COMMENT),tag=SetupTag(comment),aid=g_analysisId,zid=g_zoneId;
   double price=HistoryDealGetDouble(deal,DEAL_PRICE),vol=HistoryDealGetDouble(deal,DEAL_VOLUME);
   double profit=HistoryDealGetDouble(deal,DEAL_PROFIT),commission=HistoryDealGetDouble(deal,DEAL_COMMISSION),swap=HistoryDealGetDouble(deal,DEAL_SWAP);

   int k=TrackIndex(pid);
   if(entry==DEAL_ENTRY_IN)
   {
      k=EnsureTrack(pid,tag,aid,zid);
      string execSeq=JournalSequenceVersion();
      SavePositionMeta(pid,tag,aid,zid,g_grade,TZ_JOURNAL_BRIDGE_VERSION,execSeq,g_cloudVersion);
      ENUM_DEAL_TYPE dtype=(ENUM_DEAL_TYPE)HistoryDealGetInteger(deal,DEAL_TYPE);
      string dir=dtype==DEAL_TYPE_BUY?"BUY":"SELL";
      string d=StringFormat(
         "{\"event_uid\":\"%s\",\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\","
         "\"direction\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,\"deal_id\":%I64d,\"volume\":%.4f,"
         "\"event_provenance\":\"LIVE_MT5\",\"metadata_source\":\"LIVE_ENTRY_CONTEXT\","
         "\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\",\"execution_cloud_version\":\"%s\","
         "\"comment\":\"%s\"}",
         JsonEscape(EventUidDeal("ENTRY_OPENED",deal)),JsonEscape(CanonicalTradeId(pid)),JsonEscape(TradeId(aid,zid,tag)),
         JsonEscape(SetupName(tag)),JsonEscape(tag),dir,JsonEscape(g_grade),(long)pid,(long)deal,vol,
         TZ_JOURNAL_BRIDGE_VERSION,JsonEscape(execSeq),JsonEscape(g_cloudVersion),JsonEscape(comment)
      );
      SendJournal("ENTRY_OPENED",price,aid,zid,d);
      return;
   }

   if(k>=0){aid=g_posAnalysis[k];zid=g_posZone[k];tag=g_posTag[k];}
   string grade="",execBridge="",execSeq="",execCloud="";
   string metaTag=tag,metaAid=aid,metaZid=zid;
   bool hasMeta=LoadPositionMeta(pid,metaTag,metaAid,metaZid,grade,execBridge,execSeq,execCloud);
   if(hasMeta){tag=metaTag;aid=metaAid;zid=metaZid;}
   string metadataSource=hasMeta?"LOCAL_POSITION_METADATA":"LIVE_EXIT_NO_ENTRY_METADATA";

   string ev="POSITION_EXIT";
   if(reason==DEAL_REASON_TP)ev="TP_HIT";
   else if(reason==DEAL_REASON_SL)ev="SL_HIT";
   double net=profit+commission+swap;
   string d=StringFormat(
      "{\"event_uid\":\"%s\",\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\","
      "\"grade\":\"%s\",\"position_id\":%I64d,\"deal_id\":%I64d,\"volume\":%.4f,\"net_profit\":%.2f,"
      "\"event_provenance\":\"LIVE_MT5\",\"metadata_source\":\"%s\","
      "\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\",\"execution_cloud_version\":\"%s\","
      "\"comment\":\"%s\"}",
      JsonEscape(EventUidDeal(ev,deal)),JsonEscape(CanonicalTradeId(pid)),JsonEscape(TradeId(aid,zid,tag)),
      JsonEscape(SetupName(tag)),JsonEscape(tag),JsonEscape(grade),(long)pid,(long)deal,vol,net,metadataSource,
      JsonEscape(execBridge),JsonEscape(execSeq),JsonEscape(execCloud),JsonEscape(comment)
   );
   SendJournal(ev,price,aid,zid,d);

   if(!SequencePositionIdentifierOpen(pid))
   {
      string closed=StringFormat(
         "{\"event_uid\":\"%s\",\"trade_id\":\"%s\",\"campaign_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\","
         "\"grade\":\"%s\",\"position_id\":%I64d,\"event_provenance\":\"LIVE_MT5\",\"metadata_source\":\"%s\","
         "\"execution_bridge_version\":\"%s\",\"execution_sequence_version\":\"%s\",\"execution_cloud_version\":\"%s\"}",
         JsonEscape(EventUidPosition("TRADE_CLOSED",pid)),JsonEscape(CanonicalTradeId(pid)),JsonEscape(TradeId(aid,zid,tag)),
         JsonEscape(SetupName(tag)),JsonEscape(tag),JsonEscape(grade),(long)pid,metadataSource,
         JsonEscape(execBridge),JsonEscape(execSeq),JsonEscape(execCloud)
      );
      SendJournal("TRADE_CLOSED",price,aid,zid,closed);
   }
}

int OnInit()
{
   if(_Symbol!=XauSymbol){Print("Attach Data Bridge once to configured XAU chart only.");return INIT_FAILED;}if(CloudApiKey==""){Print("CloudApiKey is empty.");return INIT_PARAMETERS_INCORRECT;}SymbolSelect(DxySymbol,true);EventSetTimer(MathMax(10,SendEverySeconds));SendSnapshot("BOOTSTRAP");SendHeartbeat();RefreshPlanContext();MarkPositions();BackfillJournalHistory(true);return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){EventKillTimer();}
void OnTimer(){SendSnapshot("LIVE");SendHeartbeat();RefreshPlanContext();MarkPositions();BackfillJournalHistory(false);}

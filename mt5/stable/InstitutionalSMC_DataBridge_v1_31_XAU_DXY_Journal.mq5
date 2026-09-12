#property strict
#property version "1.31"
#property description "DEMO/PAPER read-only market + journal telemetry bridge for Institutional SMC Cloud."

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
input string SequenceEaVersion="3.21";
input int JournalMarkEverySeconds=60;

string g_analysisId="",g_zoneId="",g_grade="";
datetime g_lastMark=0;
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
   string b=StringFormat("{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_DataBridge\",\"version\":\"1.31\",\"symbol\":\"%s\",\"account_login\":%I64d,\"details\":{\"dxy\":\"%s\",\"journal_sync\":true,\"sequence_magic\":%I64d,\"sequence_expected_version\":\"%s\",\"paper_only\":true}}",(long)TimeTradeServer(),JsonEscape(XauSymbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(DxySymbol),(long)SequenceMagicNumber,JsonEscape(SequenceEaVersion));
   string r;Post("/mt5/heartbeat",b,r);
}
void RefreshPlanContext()
{
   if(!EnableJournalSync)return;string text;if(!Get("/mt5/plan",text))return;
   string a=KV(text,"analysis_id"),z=KV(text,"zone_id");if(a!="")g_analysisId=a;if(z!="")g_zoneId=z;g_grade=KV(text,"grade");
}
string SetupTag(string comment)
{
   string tags[6]={"FR2","FR1","F0","R2","R1","P0"};for(int i=0;i<6;i++)if(StringFind(comment," "+tags[i])>=0||StringFind(comment,tags[i])==0)return tags[i];return "UNKNOWN";
}
string SetupName(string tag)
{
   if(tag=="P0")return "PRIMARY";if(tag=="R1")return "REENTRY_1";if(tag=="R2")return "REENTRY_2";if(tag=="F0")return "ZONE_FLIP";if(tag=="FR1")return "FLIP_REENTRY_1";if(tag=="FR2")return "FLIP_REENTRY_2";return "UNKNOWN";
}
int TrackIndex(ulong pid){for(int i=0;i<ArraySize(g_posId);i++)if(g_posId[i]==pid)return i;return -1;}
int EnsureTrack(ulong pid,string tag,string aid,string zid)
{
   int i=TrackIndex(pid);if(i>=0)return i;int n=ArraySize(g_posId);ArrayResize(g_posId,n+1);ArrayResize(g_posTag,n+1);ArrayResize(g_posAnalysis,n+1);ArrayResize(g_posZone,n+1);g_posId[n]=pid;g_posTag[n]=tag;g_posAnalysis[n]=aid;g_posZone[n]=zid;return n;
}
string TradeId(string aid,string zid,string tag){if(aid=="")aid="NO_ANALYSIS";if(zid=="")zid="NO_ZONE";return aid+"|"+zid+"|"+tag;}
bool SendJournal(string event,double price,string aid,string zid,string details)
{
   if(!EnableJournalSync)return false;string body=StringFormat("{\"ts\":%I64d,\"event\":\"%s\",\"analysis_id\":\"%s\",\"zone_id\":\"%s\",\"price\":%.5f,\"details\":%s}",(long)TimeTradeServer(),JsonEscape(event),JsonEscape(aid),JsonEscape(zid),price,details);string r;return Post("/mt5/feedback",body,r);
}
bool AnyOpenTracked(string aid,string zid,string tag)
{
   for(int i=PositionsTotal()-1;i>=0;i--){ulong ticket=PositionGetTicket(i);if(!ticket)continue;if(PositionGetString(POSITION_SYMBOL)!=XauSymbol||(ulong)PositionGetInteger(POSITION_MAGIC)!=SequenceMagicNumber)continue;ulong pid=(ulong)PositionGetInteger(POSITION_IDENTIFIER);int k=TrackIndex(pid);if(k>=0&&g_posAnalysis[k]==aid&&g_posZone[k]==zid&&g_posTag[k]==tag)return true;}return false;
}
void MarkPositions()
{
   if(!EnableJournalSync)return;datetime now=TimeTradeServer();if(now-g_lastMark<JournalMarkEverySeconds)return;g_lastMark=now;MqlTick tk;if(!SymbolInfoTick(XauSymbol,tk))return;
   for(int i=PositionsTotal()-1;i>=0;i--){ulong ticket=PositionGetTicket(i);if(!ticket)continue;if(PositionGetString(POSITION_SYMBOL)!=XauSymbol||(ulong)PositionGetInteger(POSITION_MAGIC)!=SequenceMagicNumber)continue;ulong pid=(ulong)PositionGetInteger(POSITION_IDENTIFIER);string comment=PositionGetString(POSITION_COMMENT),tag=SetupTag(comment);int k=TrackIndex(pid);if(k<0)k=EnsureTrack(pid,tag,g_analysisId,g_zoneId);string aid=g_posAnalysis[k],zid=g_posZone[k];double open=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP),vol=PositionGetDouble(POSITION_VOLUME),profit=PositionGetDouble(POSITION_PROFIT);ENUM_POSITION_TYPE pt=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);string dir=pt==POSITION_TYPE_BUY?"BUY":"SELL";double mark=pt==POSITION_TYPE_BUY?tk.bid:tk.ask;string d=StringFormat("{\"trade_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\",\"direction\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,\"volume\":%.4f,\"entry_price\":%.5f,\"current_sl\":%.5f,\"tp\":%.5f,\"floating_profit\":%.2f,\"bridge_version\":\"1.31\",\"sequence_version\":\"%s\",\"comment\":\"%s\"}",JsonEscape(TradeId(aid,zid,tag)),JsonEscape(SetupName(tag)),JsonEscape(tag),dir,JsonEscape(g_grade),(long)pid,vol,open,sl,tp,profit,JsonEscape(SequenceEaVersion),JsonEscape(comment));SendJournal("POSITION_MARK",mark,aid,zid,d);}
}
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(!EnableJournalSync||trans.type!=TRADE_TRANSACTION_DEAL_ADD||trans.deal==0)return;ulong deal=trans.deal;if(!HistoryDealSelect(deal))return;if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=SequenceMagicNumber)return;if(HistoryDealGetString(deal,DEAL_SYMBOL)!=XauSymbol)return;
   ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);ENUM_DEAL_REASON reason=(ENUM_DEAL_REASON)HistoryDealGetInteger(deal,DEAL_REASON);ulong pid=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);string comment=HistoryDealGetString(deal,DEAL_COMMENT),tag=SetupTag(comment),aid=g_analysisId,zid=g_zoneId;double price=HistoryDealGetDouble(deal,DEAL_PRICE),vol=HistoryDealGetDouble(deal,DEAL_VOLUME),profit=HistoryDealGetDouble(deal,DEAL_PROFIT),commission=HistoryDealGetDouble(deal,DEAL_COMMISSION),swap=HistoryDealGetDouble(deal,DEAL_SWAP);
   int k=TrackIndex(pid);if(entry==DEAL_ENTRY_IN){k=EnsureTrack(pid,tag,aid,zid);string d=StringFormat("{\"trade_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\",\"grade\":\"%s\",\"position_id\":%I64d,\"deal_id\":%I64d,\"volume\":%.4f,\"bridge_version\":\"1.31\",\"sequence_version\":\"%s\",\"comment\":\"%s\"}",JsonEscape(TradeId(aid,zid,tag)),JsonEscape(SetupName(tag)),JsonEscape(tag),JsonEscape(g_grade),(long)pid,(long)deal,vol,JsonEscape(SequenceEaVersion),JsonEscape(comment));SendJournal("ENTRY_OPENED",price,aid,zid,d);return;}
   if(k>=0){aid=g_posAnalysis[k];zid=g_posZone[k];tag=g_posTag[k];}string ev="POSITION_EXIT";if(reason==DEAL_REASON_TP)ev="TP_HIT";else if(reason==DEAL_REASON_SL)ev="SL_HIT";double net=profit+commission+swap;string d=StringFormat("{\"trade_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\",\"position_id\":%I64d,\"deal_id\":%I64d,\"volume\":%.4f,\"net_profit\":%.2f,\"bridge_version\":\"1.31\",\"sequence_version\":\"%s\",\"comment\":\"%s\"}",JsonEscape(TradeId(aid,zid,tag)),JsonEscape(SetupName(tag)),JsonEscape(tag),(long)pid,(long)deal,vol,net,JsonEscape(SequenceEaVersion),JsonEscape(comment));SendJournal(ev,price,aid,zid,d);if(!AnyOpenTracked(aid,zid,tag)){string c=StringFormat("{\"trade_id\":\"%s\",\"setup\":\"%s\",\"tag\":\"%s\",\"bridge_version\":\"1.31\",\"sequence_version\":\"%s\"}",JsonEscape(TradeId(aid,zid,tag)),JsonEscape(SetupName(tag)),JsonEscape(tag),JsonEscape(SequenceEaVersion));SendJournal("TRADE_CLOSED",price,aid,zid,c);}
}
int OnInit()
{
   if(_Symbol!=XauSymbol){Print("Attach Data Bridge once to configured XAU chart only.");return INIT_FAILED;}if(CloudApiKey==""){Print("CloudApiKey is empty.");return INIT_PARAMETERS_INCORRECT;}SymbolSelect(DxySymbol,true);EventSetTimer(MathMax(10,SendEverySeconds));SendSnapshot("BOOTSTRAP");SendHeartbeat();RefreshPlanContext();MarkPositions();return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){EventKillTimer();}
void OnTimer(){SendSnapshot("LIVE");SendHeartbeat();RefreshPlanContext();MarkPositions();}

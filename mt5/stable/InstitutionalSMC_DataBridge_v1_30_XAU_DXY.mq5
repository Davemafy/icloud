#property strict
#property version "1.30"
#property description "Attach ONCE to XAU chart. Sends closed XAU D1/H4/H1/M15 + DXY D1/H4/H1, ATR/spread and optional high-impact USD calendar to SMC Cloud v6."

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

string JsonEscape(string s)
{
   StringReplace(s,"\\","\\\\");StringReplace(s,"\"","\\\"");StringReplace(s,"\r"," ");StringReplace(s,"\n"," ");return s;
}

double ATRValue(string sym,ENUM_TIMEFRAMES tf,int period=14)
{
   int h=iATR(sym,tf,period);if(h==INVALID_HANDLE)return 0;double b[];ArraySetAsSeries(b,true);double v=0;if(CopyBuffer(h,0,1,1,b)==1)v=b[0];IndicatorRelease(h);return v;
}

string BarsJson(string sym,ENUM_TIMEFRAMES tf,int count)
{
   MqlRates r[];int n=CopyRates(sym,tf,1,count,r);if(n<=0)return "[]";string s="[";
   for(int i=0;i<n;i++)
   {
      if(i>0)s+=",";
      s+=StringFormat("{\"ts\":%I64d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"tick_volume\":%I64d}",(long)r[i].time,r[i].open,r[i].high,r[i].low,r[i].close,(long)r[i].tick_volume);
   }
   return s+"]";
}

string NewsJson()
{
   if(!SendCalendarNews)return "[]";
   datetime now=TimeTradeServer();datetime from=now-NewsWindowHours*3600,to=now+NewsWindowHours*3600;MqlCalendarValue vals[];
   int n=CalendarValueHistory(vals,from,to,"","USD");if(n<=0)return "[]";string s="[";int used=0;
   for(int i=0;i<n;i++)
   {
      MqlCalendarEvent ev;if(!CalendarEventById(vals[i].event_id,ev))continue;if(ev.importance!=CALENDAR_IMPORTANCE_HIGH)continue;
      if(used++>0)s+=",";s+=StringFormat("{\"ts\":%I64d,\"currency\":\"USD\",\"title\":\"%s\",\"impact\":\"HIGH\"}",(long)vals[i].time,JsonEscape(ev.name));
   }
   return s+"]";
}

bool Post(string path,string body,string &response)
{
   string url=CloudBaseUrl+path,headers="Content-Type: application/json\r\nX-API-Key: "+CloudApiKey+"\r\n";char data[],result[];string rh;
   StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);if(ArraySize(data)>0)ArrayResize(data,ArraySize(data)-1);
   ResetLastError();int code=WebRequest("POST",url,headers,HttpTimeoutMs,data,result,rh);response=CharArrayToString(result,0,-1,CP_UTF8);
   if(code!=200){Print("SMC Bridge POST ",path," HTTP=",code," err=",GetLastError()," body=",response);return false;}return true;
}

bool SendSnapshot(string reason)
{
   MqlTick t;if(!SymbolInfoTick(XauSymbol,t))return false;double point=SymbolInfoDouble(XauSymbol,SYMBOL_POINT);if(point<=0)point=0.01;double spread=(t.ask-t.bid)/point;
   string body=StringFormat("{\"protocol\":6,\"kind\":\"FULL_HISTORY\",\"reason\":\"%s\",\"sent_at\":%I64d,\"xau_symbol\":\"%s\",\"dxy_symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"spread_points\":%.2f,\"point\":%.5f,\"atr_h1\":%.5f,\"atr_m15\":%.5f,",
      JsonEscape(reason),(long)TimeTradeServer(),JsonEscape(XauSymbol),JsonEscape(DxySymbol),t.bid,t.ask,spread,point,ATRValue(XauSymbol,PERIOD_H1),ATRValue(XauSymbol,PERIOD_M15));
   body+="\"xau_d1\":"+BarsJson(XauSymbol,PERIOD_D1,BarsD1)+",";
   body+="\"xau_h4\":"+BarsJson(XauSymbol,PERIOD_H4,BarsH4)+",";
   body+="\"xau_h1\":"+BarsJson(XauSymbol,PERIOD_H1,BarsH1)+",";
   body+="\"xau_m15\":"+BarsJson(XauSymbol,PERIOD_M15,BarsM15)+",";
   body+="\"dxy_d1\":"+BarsJson(DxySymbol,PERIOD_D1,BarsD1)+",";
   body+="\"dxy_h4\":"+BarsJson(DxySymbol,PERIOD_H4,BarsH4)+",";
   body+="\"dxy_h1\":"+BarsJson(DxySymbol,PERIOD_H1,BarsH1)+",";
   body+="\"news\":"+NewsJson()+"}";
   string response;bool ok=Post("/market/snapshot",body,response);if(ok)Print("SMC Bridge snapshot OK reason=",reason," bytes=",StringLen(body));return ok;
}

void SendHeartbeat()
{
   string b=StringFormat("{\"ts\":%I64d,\"ea\":\"InstitutionalSMC_DataBridge\",\"version\":\"1.30\",\"symbol\":\"%s\",\"account_login\":%I64d,\"details\":{\"dxy\":\"%s\"}}",(long)TimeTradeServer(),JsonEscape(XauSymbol),(long)AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(DxySymbol));string r;Post("/mt5/heartbeat",b,r);
}

int OnInit()
{
   if(_Symbol!=XauSymbol){Print("Attach Data Bridge once to configured XAU chart only. Chart=",_Symbol," XauSymbol=",XauSymbol);return INIT_FAILED;}
   if(CloudApiKey==""){Print("CloudApiKey is empty.");return INIT_PARAMETERS_INCORRECT;}
   SymbolSelect(DxySymbol,true);EventSetTimer(MathMax(10,SendEverySeconds));SendSnapshot("BOOTSTRAP");SendHeartbeat();return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){EventKillTimer();}
void OnTimer(){SendSnapshot("LIVE");SendHeartbeat();}

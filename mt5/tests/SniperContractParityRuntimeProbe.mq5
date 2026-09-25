#property strict
#property script_show_inputs
#property description "Trade Zone Master Sniper contract parity runtime probe. NO TRADING."

#include <TradeZoneCore\SniperContractParityV1.mqh>

input string CloudBaseUrl="__CLOUD_BASE_URL__";
input string CloudApiKey="__CLOUD_API_KEY__";
input int HttpTimeoutMs=5000;

string Trim(string s)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   return s;
}

string KV(string text,string key)
{
   string needle=key+"=";
   int p=StringFind(text,needle);
   if(p<0)return "";
   p+=StringLen(needle);
   int e=StringFind(text,"\n",p);
   if(e<0)e=StringLen(text);
   return Trim(StringSubstr(text,p,e-p));
}

string FirstKV(string text,string a,string b="",string c="")
{
   string v=KV(text,a);
   if(v==""&&b!="")v=KV(text,b);
   if(v==""&&c!="")v=KV(text,c);
   return v;
}

bool HttpGet(string path,string &response)
{
   if(CloudBaseUrl==""||CloudApiKey=="")return false;
   string url=CloudBaseUrl+path;
   string headers="X-API-Key: "+CloudApiKey+"\r\nAccept: text/plain\r\n";
   char data[],result[];
   string resultHeaders;
   ResetLastError();
   int code=WebRequest("GET",url,headers,HttpTimeoutMs,data,result,resultHeaders);
   if(code<0)
   {
      Print("SNIPER_PARITY_RUNTIME FAIL cloud-webrequest error=",GetLastError()," url=",url);
      return false;
   }
   response=CharArrayToString(result,0,-1,CP_UTF8);
   if(code!=200)
   {
      Print("SNIPER_PARITY_RUNTIME FAIL cloud-http=",code);
      return false;
   }
   return true;
}

void Result(string label,bool pass,string details="")
{
   Print("SNIPER_PARITY_RUNTIME ",(pass?"PASS ":"FAIL "),label,(details==""?"":" | "+details));
}

void OnStart()
{
   Print("SNIPER_PARITY_RUNTIME START | NO TRADING | contract=",TZ_SNIPER_PARITY_VERSION);

   string plan;
   if(!HttpGet("/mt5/plan",plan))
   {
      Result("LIVE_PLAN_FETCH",false,"Check MT5 WebRequest allow-list and cloud connectivity.");
      return;
   }
   Result("LIVE_PLAN_FETCH",true);

   string analysisId=KV(plan,"analysis_id");
   string zoneId=KV(plan,"zone_id");
   string direction=FirstKV(plan,"original_direction","direction");
   string currentGrade=FirstKV(plan,"current_grade","grade");
   string qmitText=FirstKV(plan,"qualified_mitigations","touch_count");
   int qualifiedMitigations=(int)StringToInteger(qmitText);
   string riskContext=KV(plan,"risk_context");
   string riskText=FirstKV(plan,"base_risk_pct","original_risk_pct","grade_risk_pct");
   double baseRiskPct=StringToDouble(riskText);
   string authority=KV(plan,"execution_authority");
   if(authority=="")authority="NONE";
   string expected=KV(plan,"contract_fingerprint");

   bool fieldsComplete=(
      analysisId!=""&&zoneId!=""&&direction!=""&&currentGrade!=""&&
      qmitText!=""&&riskContext!=""&&riskText!=""&&authority!=""
   );
   Result("AUTHORITATIVE_FIELDS",fieldsComplete,
      "analysis="+analysisId+" zone="+zoneId+" direction="+direction+
      " grade="+currentGrade+" qmit="+IntegerToString(qualifiedMitigations)+
      " context="+riskContext+" risk="+DoubleToString(baseRiskPct,8)+
      " authority="+authority);

   string actual=TZ_SniperContractFingerprint(
      analysisId,zoneId,direction,currentGrade,qualifiedMitigations,
      riskContext,baseRiskPct,authority
   );

   bool liveMatch=(fieldsComplete&&expected!=""&&expected==actual);
   Result("MATCH",liveMatch,"cloud="+expected+" native="+actual);

   // UNVERIFIED path: missing fingerprint MUST fail closed for a new entry.
   string missingFingerprint="";
   bool unverifiedEntrySafe=(fieldsComplete&&missingFingerprint!=""&&missingFingerprint==actual);
   Result("UNVERIFIED_BLOCKS_NEW_ENTRY",!unverifiedEntrySafe);

   // MISMATCH path: mutate one authoritative field locally only. Cloud is untouched.
   string mismatchHash=TZ_SniperContractFingerprint(
      analysisId,zoneId+"-LOCAL-MISMATCH",direction,currentGrade,qualifiedMitigations,
      riskContext,baseRiskPct,authority
   );
   bool mismatchEntrySafe=(expected!=""&&expected==mismatchHash);
   Result("MISMATCH_BLOCKS_NEW_ENTRY",!mismatchEntrySafe,
      "expected="+expected+" mutated="+mismatchHash);

   bool overall=(liveMatch&&!unverifiedEntrySafe&&!mismatchEntrySafe);
   Result("OVERALL",overall,overall?
      "MATCH permits parity trust; UNVERIFIED and MISMATCH fail closed.":
      "One or more parity runtime gates failed.");

   Print("SNIPER_PARITY_RUNTIME END | NO ORDERS WERE SENT.");
}

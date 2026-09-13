string ML24_Escape(string s){StringReplace(s,"\\","\\\\");StringReplace(s,"\"","\\\"");StringReplace(s,"\r"," ");StringReplace(s,"\n"," ");return s;}
string ML24_Bool(bool v){return v?"true":"false";}
bool ML24_Flag(string text,string key,bool def=false){string v=KV(text,key);if(v=="")return def;StringToLower(v);return (v=="1"||v=="true"||v=="yes"||v=="on");}
string ML24_ReadState(string key){int h=FileOpen("TradeZone\\sequence_state.txt",FILE_READ|FILE_TXT|FILE_ANSI);if(h==INVALID_HANDLE)return "";string needle=key+"=",out="";while(!FileIsEnding(h)){string line=FileReadString(h);if(StringFind(line,needle)==0){out=StringSubstr(line,StringLen(needle));break;}}FileClose(h);StringTrimLeft(out);StringTrimRight(out);return out;}
int ML24_StateInt(string key){string v=ML24_ReadState(key);return v==""?-1:(int)StringToInteger(v);}
void ML24_AddReason(string &csv,string reason){if(reason=="")return;if(csv!="")csv+=",";csv+="\""+ML24_Escape(reason)+"\"";}

bool ML24_Post(string path,string body,string &response)
{
   if(CloudApiKey=="")return false;
   string url=CloudBaseUrl+path;
   string headers="Content-Type: application/json\r\nX-API-Key: "+CloudApiKey+"\r\n";
   char data[],result[];string rh;
   StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);if(ArraySize(data)>0)ArrayResize(data,ArraySize(data)-1);
   ResetLastError();int code=WebRequest("POST",url,headers,ObserverHttpTimeoutMs,data,result,rh);
   response=CharArrayToString(result,0,-1,CP_UTF8);
   if(code!=200){ml24_post_errors++;Print("ML24 POST failed HTTP=",code," err=",GetLastError()," path=",path," body=",response);return false;}
   return true;
}

bool ML24_RefreshContext(bool force=false)
{
   datetime now=TimeCurrent();
   if(!force && now-ml24_last_plan_poll<MathMax(5,ObserverPollSeconds) && g_plan.valid)return true;
   ml24_last_plan_poll=now;
   string text;if(!HttpGet("/mt5/plan",text)){ml24_profile_ready=false;return false;}
   Plan p;ZeroMemory(p);if(!ParsePlanText(text,p)){ml24_profile_ready=false;g_plan.valid=false;return false;}
   if(p.analysis_id!=g_lastAnalysis){g_lastAnalysis=p.analysis_id;ResetPlanState();ml24_last_bar=0;}
   g_plan=p;
   if(g_plan.zone_state=="FAILED_FLIP_CANDIDATE"){g_flipCandidate=true;if(g_flipAcceptedAt==0)g_flipAcceptedAt=now;}
   ml24_live_block=(KV(text,"live_block")=="1");
   ml24_live_block_reason=KV(text,"live_block_reason");
   ml24_cloud_regime=KV(text,"market_regime");if(ml24_cloud_regime=="")ml24_cloud_regime="UNKNOWN";
   ml24_allow_ict=ML24_Flag(text,"model_ict_sniper",true);
   ml24_allow_reentry=ML24_Flag(text,"model_ict_deep_reentry",true);
   ml24_allow_momentum=EnableMomentumPullbackModel&&ML24_Flag(text,"model_momentum_pullback",false);
   ml24_allow_vwap=EnableVWAPProxyModel&&ML24_Flag(text,"model_vwap_proxy_reclaim",false);
   ml24_allow_orb=EnableOpeningRangeRetestModel&&ML24_Flag(text,"model_opening_range_retest",false);
   ml24_allow_flip=ML24_Flag(text,"model_accepted_zone_flip",true);
   ml24_profile_ready=true;
   return true;
}

double ML24_Efficiency(MqlRates &r[],int n){n=MathMin(n,ArraySize(r)-2);if(n<3)return 0;double path=0;for(int i=1;i<=n;i++)path+=MathAbs(r[i].close-r[i+1].close);if(path<=0)return 0;return MathMin(1.0,MathAbs(r[1].close-r[n+1].close)/path);}
string ML24_LocalRegime(MqlRates &r[]){if(ArraySize(r)<80)return "UNKNOWN";double fast=ATR(r,7,1),slow=ATR(r,28,1),eff=ML24_Efficiency(r,24);if(fast<=0||slow<=0)return "UNKNOWN";double vr=fast/slow;if(vr>=1.45&&eff<=0.28)return "EXHAUSTION";if(vr>=1.22&&eff>=0.34)return "EXPANSION";if(vr<=0.76)return "COMPRESSION";if(eff>=0.46)return "TREND";return "RANGE";}
bool ML24_LocalAllows(string model,string regime){if(model=="MOMENTUM_PULLBACK")return regime=="TREND"||regime=="EXPANSION";if(model=="VWAP_PROXY_RECLAIM")return regime=="TREND";if(model=="OPENING_RANGE_RETEST")return regime=="TREND"||regime=="EXPANSION";return true;}
bool ML24_RecentZone(MqlRates &r[],int bars){int n=MathMin(bars,ArraySize(r)-2);for(int i=1;i<=n;i++)if(r[i].high>=g_plan.zone_low&&r[i].low<=g_plan.zone_high)return true;return false;}
bool ML24_DirectionalResume(MqlRates &r[],bool buy,double a,double minBodyATR=0.20){if(ArraySize(r)<4||a<=0)return false;double body=MathAbs(r[1].close-r[1].open);if(body<minBodyATR*a)return false;if(buy)return r[1].close>r[1].open&&r[1].close>r[2].high;return r[1].close<r[1].open&&r[1].close<r[2].low;}

bool ML24_BuildMomentum(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;if(ArraySize(r)<90||a<=0)return false;int mx=MathMin(45,ArraySize(r)-8);
   double rmin=MathMin(MomentumRetraceMin,MomentumRetraceMax),rmax=MathMax(MomentumRetraceMin,MomentumRetraceMax);
   for(int br=4;br<=mx;br++)
   {
      int bp=-1;double bos=0;if(!OlderPivot(r,br+2,MathMin(br+35,ArraySize(r)-3),buy,bp,bos))continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);if(!broke||!StrongDisp(r,br,a,MathMax(0.65,ReentryDisplacementATR*0.80),buy))continue;
      int ap=-1;double anchor=0;if(!OlderPivot(r,br+2,MathMin(br+45,ArraySize(r)-3),!buy,ap,anchor))continue;
      double imp=buy?r[br].high:r[br].low;for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
      double d=MathAbs(imp-anchor);if(d<a)continue;double lo,hi;if(buy){lo=imp-d*rmax;hi=imp-d*rmin;}else{lo=imp+d*rmin;hi=imp+d*rmax;}if(lo>hi){double x=lo;lo=hi;hi=x;}
      bool touched=false;double inv=buy?DBL_MAX:-DBL_MAX;for(int i=1;i<br;i++){if(r[i].high>=lo&&r[i].low<=hi)touched=true;if(buy)inv=MathMin(inv,r[i].low);else inv=MathMax(inv,r[i].high);}
      if(!touched||!ML24_DirectionalResume(r,buy,a,0.20)||inv==DBL_MAX||inv==-DBL_MAX)continue;
      sig.valid=true;sig.buy=buy;sig.reentry=true;sig.flip=false;sig.anchor_idx=ap;sig.break_idx=br;sig.pd_idx=1;sig.anchor_price=inv;sig.break_level=bos;sig.impulse_extreme=imp;sig.ote_low=lo;sig.ote_high=hi;sig.pd_low=lo;sig.pd_high=hi;sig.entry_low=lo;sig.entry_high=hi;sig.pd_type="MOM_PULLBACK";return true;
   }
   return false;
}

double ML24_VWAP(MqlRates &r[],int start,int count){int end=MathMin(start+count,ArraySize(r));if(start<0||start>=end)return 0;double pv=0,w=0;for(int i=start;i<end;i++){double wt=(double)r[i].tick_volume;if(wt<=0)wt=1;double tp=(r[i].high+r[i].low+r[i].close)/3.0;pv+=tp*wt;w+=wt;}return w>0?pv/w:0;}
bool ML24_BuildVWAP(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false;if(ArraySize(r)<VWAPLookbackBars+40||a<=0)return false;int half=MathMax(20,VWAPLookbackBars/2);
   double recent=ML24_VWAP(r,1,VWAPLookbackBars),old=ML24_VWAP(r,1+half,VWAPLookbackBars);if(recent<=0||old<=0)return false;if(buy&&recent<=old)return false;if(!buy&&recent>=old)return false;
   double band=MathMax(_Point*5,a*VWAPBandATR),lo=recent-band,hi=recent+band;bool touched=false;for(int i=2;i<=MathMin(10,ArraySize(r)-2);i++)if(r[i].high>=lo&&r[i].low<=hi){touched=true;break;}
   if(!touched||!ML24_DirectionalResume(r,buy,a,0.18))return false;if(buy&&r[1].close<=recent)return false;if(!buy&&r[1].close>=recent)return false;
   double inv=buy?r[1].low:r[1].high;for(int i=1;i<=MathMin(12,ArraySize(r)-2);i++){if(buy)inv=MathMin(inv,r[i].low);else inv=MathMax(inv,r[i].high);}
   sig.valid=true;sig.buy=buy;sig.reentry=true;sig.flip=false;sig.anchor_idx=12;sig.break_idx=1;sig.pd_idx=1;sig.anchor_price=inv;sig.break_level=recent;sig.impulse_extreme=r[1].close;sig.ote_low=lo;sig.ote_high=hi;sig.pd_low=lo;sig.pd_high=hi;sig.entry_low=lo;sig.entry_high=hi;sig.pd_type="VWAP_PROXY_RECLAIM";return true;
}

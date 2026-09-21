#property strict
#property version   "3.21"
#property description "DEMO/PAPER XAU M1 institutional sequence: primary sniper + continuation re-entry + accepted-zone flip + thesis risk + tester replay."

#include <Trade/Trade.mqh>
CTrade trade;

enum ENUM_SMC_MODE { LIVE_CLOUD=0, TESTER_FILE=1 };
input ENUM_SMC_MODE OperatingMode=LIVE_CLOUD;
input string CloudBaseUrl="https://YOUR-SERVICE.up.railway.app";
input string CloudApiKey="";
input string TesterPlanFile="SMC_v6_tester_plans.csv";
input ulong MagicNumber=5632001;
input int PollSeconds=15;
input int HttpTimeoutMs=5000;

// One risk budget per directional thesis. DEMO defaults only.
input double ThesisRiskPct=0.50;
input double PrimaryRiskShare=0.60;
input double Reentry1RiskShare=0.30;
input double Reentry2RiskShare=0.10;
input double FlipRiskMultiplier=0.75;       // conservative until flip expectancy is proven
input int MaxReentriesPerThesis=2;
input double MaxDailyLossR=2.0;
input double MaxSpreadPoints=35;
input int MaxSlippagePoints=20;

// M1 sniper execution.
input int SwingLookback=60;
input int SweepWindowBars=30;
input double SweepBufferPoints=5;
input int ATRPeriod=14;
input double MinDisplacementATR=0.80;
input double SLBufferATR=0.15;
input double OTE_Min=0.618;
input double OTE_Max=0.786;
input double OTE_Reference=0.705;
input double MaxEntryChaseATR=0.10;
input bool EnableFVG=true;
input bool EnableOrderBlock=true;
input bool EnableIFVG=true;

// Continuation re-entry.
input bool EnableReentries=true;
input bool RequireInternalSweepForReentry=true;
input int ReentryLookbackBars=45;
input double ReentryDisplacementATR=0.80;

// Zone-flip engine. Invalidation itself is NEVER an entry.
input bool EnableZoneFlip=true;
input double M15SingleBodyFractionBeyond=0.60;
input double M15SingleBodyATR=0.40;
input double M15DoubleBodyATR=0.20;
input double FlipBreakDisplacementATR=0.80;
input int FlipRetestMaxBars=60;
input bool RequireFlipRetest=true;

// Trade management.
input double BreakEvenArmAtR=1.00;
input int BEStructureLookback=4;
input double RunnerTrailStartR=1.50;
input ENUM_TIMEFRAMES RunnerTrailTF=PERIOD_M5;
input int RunnerTrailLookbackBars=4;
input double RunnerTrailATRMultiple=1.20;
input double RunnerStructureATRBuffer=0.10;
input double TP1VolumePct=35;
input double TP2VolumePct=30;
input double RunnerVolumePct=35;

struct Plan
{
   bool valid;
   string analysis_id,zone_id,ea_mode,grade,setup_type,zone_state;
   string original_direction,flip_direction,core_method;
   double core_low,core_high,zone_low,zone_high;
   double original_t1,original_t2,original_t3,original_run;
   double flip_t1,flip_t2,flip_t3,flip_run;
   double min_disp_atr,min_rr;
   datetime epoch;
};

struct Signal
{
   bool valid,buy,reentry,flip;
   int anchor_idx,break_idx,pd_idx;
   double anchor_price,break_level,impulse_extreme;
   double ote_low,ote_high,pd_low,pd_high,entry_low,entry_high;
   string pd_type;
};

Plan g_plan;
datetime g_lastPlanPoll=0,g_lastTradeBar=0,g_flipAcceptedAt=0;
string g_lastAnalysis="",g_lastSequence="";
bool g_flipCandidate=false;
int g_primaryEntries=0,g_reentries=0,g_flipPrimaryEntries=0,g_flipReentries=0;

Plan testerPlans[];

string Trim(string s){ StringTrimLeft(s); StringTrimRight(s); return s; }
string KV(string text,string key)
{
   string needle=key+"="; int p=StringFind(text,needle); if(p<0) return "";
   p+=StringLen(needle); int e=StringFind(text,"\n",p); if(e<0) e=StringLen(text);
   return Trim(StringSubstr(text,p,e-p));
}

bool IsTester(){ return (bool)MQLInfoInteger(MQL_TESTER); }
bool IsDemo(){ return (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO; }

bool ParsePlanText(string text,Plan &p)
{
   p.valid=false;
   p.analysis_id=KV(text,"analysis_id"); p.zone_id=KV(text,"zone_id"); p.ea_mode=KV(text,"ea_mode");
   p.grade=KV(text,"grade"); p.setup_type=KV(text,"setup_type"); p.zone_state=KV(text,"zone_state");
   p.original_direction=KV(text,"original_direction"); p.flip_direction=KV(text,"flip_direction"); p.core_method=KV(text,"core_method");
   p.core_low=StringToDouble(KV(text,"core_low")); p.core_high=StringToDouble(KV(text,"core_high"));
   p.zone_low=StringToDouble(KV(text,"zone_low")); p.zone_high=StringToDouble(KV(text,"zone_high"));
   p.original_t1=StringToDouble(KV(text,"original_target1")); p.original_t2=StringToDouble(KV(text,"original_target2"));
   p.original_t3=StringToDouble(KV(text,"original_target3")); p.original_run=StringToDouble(KV(text,"original_runner"));
   p.flip_t1=StringToDouble(KV(text,"flip_target1")); p.flip_t2=StringToDouble(KV(text,"flip_target2"));
   p.flip_t3=StringToDouble(KV(text,"flip_target3")); p.flip_run=StringToDouble(KV(text,"flip_runner"));
   p.min_disp_atr=StringToDouble(KV(text,"min_displacement_atr")); if(p.min_disp_atr<=0) p.min_disp_atr=MinDisplacementATR;
   p.min_rr=StringToDouble(KV(text,"min_rr")); if(p.min_rr<=0) p.min_rr=1.5;
   p.valid=(p.analysis_id!="" && p.zone_id!="" && p.zone_low>0 && p.zone_high>p.zone_low && p.ea_mode!="NO_TRADE");
   return p.valid;
}

bool HttpGet(string path,string &response)
{
   if(CloudApiKey=="") return false;
   string url=CloudBaseUrl+path;
   string headers="X-API-Key: "+CloudApiKey+"\r\nAccept: text/plain\r\n";
   char data[],result[]; string resultHeaders;
   ResetLastError();
   int code=WebRequest("GET",url,headers,HttpTimeoutMs,data,result,resultHeaders);
   if(code<0){ Print("WebRequest failed error=",GetLastError()," URL=",url); return false; }
   response=CharArrayToString(result,0,-1,CP_UTF8);
   if(code!=200){ Print("Cloud plan HTTP ",code," body=",response); return false; }
   return true;
}

void ResetPlanState()
{
   g_flipCandidate=false; g_flipAcceptedAt=0; g_lastSequence="";
   g_primaryEntries=0; g_reentries=0; g_flipPrimaryEntries=0; g_flipReentries=0;
}

bool RefreshLivePlan()
{
   string text; if(!HttpGet("/mt5/plan",text)) return false;
   if(KV(text,"live_block")=="1"){ g_plan.valid=false; Print("Cloud live safety block: ",KV(text,"live_block_reason")); return false; }
   Plan p; if(!ParsePlanText(text,p)) return false;
   if(p.analysis_id!=g_lastAnalysis){ g_lastAnalysis=p.analysis_id; ResetPlanState(); }
   g_plan=p;
   if(g_plan.zone_state=="FAILED_FLIP_CANDIDATE"){ g_flipCandidate=true; if(g_flipAcceptedAt==0) g_flipAcceptedAt=TimeCurrent(); }
   return true;
}

bool LoadTesterPlans()
{
   int flags=FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON;
   int h=FileOpen(TesterPlanFile,flags,','); if(h==INVALID_HANDLE){ Print("Tester plan file missing in FILE_COMMON: ",TesterPlanFile," err=",GetLastError()); return false; }
   // fixed header from app.backtest
   for(int i=0;i<21 && !FileIsEnding(h);i++) FileReadString(h);
   ArrayResize(testerPlans,0);
   while(!FileIsEnding(h))
   {
      Plan p; ZeroMemory(p);
      string sepoch=FileReadString(h); if(sepoch=="") break;
      p.epoch=(datetime)StringToInteger(sepoch);
      p.analysis_id=FileReadString(h); p.zone_id=FileReadString(h); p.ea_mode=FileReadString(h); p.grade=FileReadString(h);
      p.original_direction=FileReadString(h); p.flip_direction=FileReadString(h);
      p.core_low=StringToDouble(FileReadString(h)); p.core_high=StringToDouble(FileReadString(h));
      p.zone_low=StringToDouble(FileReadString(h)); p.zone_high=StringToDouble(FileReadString(h));
      p.original_t1=StringToDouble(FileReadString(h)); p.original_t2=StringToDouble(FileReadString(h)); p.original_t3=StringToDouble(FileReadString(h)); p.original_run=StringToDouble(FileReadString(h));
      p.flip_t1=StringToDouble(FileReadString(h)); p.flip_t2=StringToDouble(FileReadString(h)); p.flip_t3=StringToDouble(FileReadString(h)); p.flip_run=StringToDouble(FileReadString(h));
      p.min_disp_atr=StringToDouble(FileReadString(h)); p.min_rr=StringToDouble(FileReadString(h));
      p.valid=(p.zone_low>0 && p.zone_high>p.zone_low);
      int n=ArraySize(testerPlans); ArrayResize(testerPlans,n+1); testerPlans[n]=p;
   }
   FileClose(h); Print("Loaded tester plans: ",ArraySize(testerPlans)); return ArraySize(testerPlans)>0;
}

bool SelectTesterPlan(datetime now)
{
   int best=-1;
   for(int i=0;i<ArraySize(testerPlans);i++) if(testerPlans[i].epoch<=now) best=i; else break;
   if(best<0) return false;
   Plan p=testerPlans[best];
   if(p.analysis_id!=g_lastAnalysis){ g_lastAnalysis=p.analysis_id; ResetPlanState(); }
   g_plan=p; return g_plan.valid;
}

bool RefreshPlan()
{
   if(OperatingMode==TESTER_FILE || IsTester()) return SelectTesterPlan(TimeCurrent());
   if(TimeCurrent()-g_lastPlanPoll<PollSeconds && g_plan.valid) return true;
   g_lastPlanPoll=TimeCurrent(); return RefreshLivePlan();
}

double TR(MqlRates &r[],int i)
{
   double pc=(i+1<ArraySize(r)?r[i+1].close:r[i].close);
   return MathMax(r[i].high-r[i].low,MathMax(MathAbs(r[i].high-pc),MathAbs(r[i].low-pc)));
}
double ATR(MqlRates &r[],int period,int start=1)
{
   if(ArraySize(r)<start+period+1) return 0; double s=0; for(int i=start;i<start+period;i++) s+=TR(r,i); return s/period;
}
bool PivotHigh(MqlRates &r[],int i)
{
   if(i<2 || i+2>=ArraySize(r)) return false;
   return r[i].high>r[i-1].high && r[i].high>r[i-2].high && r[i].high>r[i+1].high && r[i].high>r[i+2].high;
}
bool PivotLow(MqlRates &r[],int i)
{
   if(i<2 || i+2>=ArraySize(r)) return false;
   return r[i].low<r[i-1].low && r[i].low<r[i-2].low && r[i].low<r[i+1].low && r[i].low<r[i+2].low;
}
bool OlderPivot(MqlRates &r[],int start,int end,bool highSide,int &idx,double &level)
{
   end=MathMin(end,ArraySize(r)-3);
   for(int i=MathMax(start,2);i<=end;i++)
   {
      if(highSide && PivotHigh(r,i)){idx=i;level=r[i].high;return true;}
      if(!highSide && PivotLow(r,i)){idx=i;level=r[i].low;return true;}
   }
   return false;
}
bool StrongDisp(MqlRates &r[],int i,double a,double minAtr,bool buy)
{
   if(i<1 || i>=ArraySize(r) || a<=0) return false;
   double body=MathAbs(r[i].close-r[i].open),range=r[i].high-r[i].low;
   if(range<a*minAtr || body<range*0.55) return false;
   return buy?(r[i].close>r[i].open):(r[i].close<r[i].open);
}
bool TouchZone(MqlRates &b){ return b.high>=g_plan.zone_low && b.low<=g_plan.zone_high; }

void OTE(bool buy,double anchor,double impulse,double &lo,double &hi)
{
   double d=MathAbs(impulse-anchor);
   if(buy){ lo=impulse-d*OTE_Max; hi=impulse-d*OTE_Min; }
   else { lo=impulse+d*OTE_Min; hi=impulse+d*OTE_Max; }
   if(lo>hi){double x=lo;lo=hi;hi=x;}
}

bool Intersect(double a1,double a2,double b1,double b2,double &lo,double &hi)
{
   lo=MathMax(MathMin(a1,a2),MathMin(b1,b2)); hi=MathMin(MathMax(a1,a2),MathMax(b1,b2)); return lo<=hi;
}

bool FindFreshPD(MqlRates &r[],bool buy,int anchorIdx,int breakIdx,double oteLo,double oteHi,int &pdIdx,double &pdLo,double &pdHi,string &pdType,double &eLo,double &eHi)
{
   // FVG first: three-candle imbalance created after the structural break.
   if(EnableFVG)
   {
      for(int i=MathMax(2,breakIdx-1);i>=2;i--)
      {
         double lo=0,hi=0; bool ok=false;
         if(buy && r[i+1].high<r[i-1].low){lo=r[i+1].high;hi=r[i-1].low;ok=true;}
         if(!buy && r[i+1].low>r[i-1].high){lo=r[i-1].high;hi=r[i+1].low;ok=true;}
         double x1,x2; if(ok && Intersect(lo,hi,oteLo,oteHi,x1,x2)){pdIdx=i;pdLo=lo;pdHi=hi;pdType="FVG";eLo=x1;eHi=x2;return true;}
      }
   }
   // Order block: last opposing candle before displacement, only if it overlaps OTE.
   if(EnableOrderBlock)
   {
      for(int i=breakIdx+1;i<=MathMin(anchorIdx-1,breakIdx+6);i++)
      {
         bool opp=buy?(r[i].close<r[i].open):(r[i].close>r[i].open); if(!opp) continue;
         double lo=MathMin(r[i].open,r[i].close),hi=MathMax(r[i].open,r[i].close),x1,x2;
         if(Intersect(lo,hi,oteLo,oteHi,x1,x2)){pdIdx=i;pdLo=lo;pdHi=hi;pdType="OB";eLo=x1;eHi=x2;return true;}
      }
   }
   return false;
}

bool BuildPrimary(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false; int maxSweep=MathMin(SweepWindowBars,ArraySize(r)-8); double buf=SweepBufferPoints*_Point;
   for(int sw=6;sw<=maxSweep;sw++)
   {
      int li=-1,ms=-1; double liquidity=0,mss=0;
      if(!OlderPivot(r,sw+2,SwingLookback,!buy,li,liquidity)) continue;
      if(!OlderPivot(r,sw+2,SwingLookback,buy,ms,mss)) continue;
      bool swept=buy?(r[sw].low<liquidity-buf && r[sw].close>liquidity):(r[sw].high>liquidity+buf && r[sw].close<liquidity);
      if(!swept || !TouchZone(r[sw])) continue;
      int br=-1;
      for(int j=sw-1;j>=3;j--)
      {
         bool broke=buy?(r[j].close>mss):(r[j].close<mss);
         if(broke && StrongDisp(r,j,a,MathMax(MinDisplacementATR,g_plan.min_disp_atr),buy)){br=j;break;}
      }
      if(br<3) continue;
      double anchor=buy?r[sw].low:r[sw].high,imp=buy?r[br].high:r[br].low;
      for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
      if(MathAbs(imp-anchor)<a) continue;
      double ol,oh; OTE(buy,anchor,imp,ol,oh);
      int pi; double pl,ph,el,eh; string pt;
      if(!FindFreshPD(r,buy,sw,br,ol,oh,pi,pl,ph,pt,el,eh)) continue;
      sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=false;sig.anchor_idx=sw;sig.break_idx=br;sig.pd_idx=pi;
      sig.anchor_price=anchor;sig.break_level=mss;sig.impulse_extreme=imp;sig.ote_low=ol;sig.ote_high=oh;sig.pd_low=pl;sig.pd_high=ph;sig.entry_low=el;sig.entry_high=eh;sig.pd_type=pt;return true;
   }
   return false;
}

bool HasInternalSweep(MqlRates &r[],bool buy,int br,int anchor,double buf)
{
   int pi; double p;
   if(!OlderPivot(r,anchor+2,SwingLookback,!buy,pi,p)) return false;
   for(int i=br+1;i<=anchor && i<ArraySize(r);i++)
   {
      if(buy && r[i].low<p-buf && r[i].close>p) return true;
      if(!buy && r[i].high>p+buf && r[i].close<p) return true;
   }
   return false;
}

bool BuildReentry(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false; double buf=SweepBufferPoints*_Point; int mx=MathMin(ReentryLookbackBars,ArraySize(r)-8);
   for(int br=3;br<=mx;br++)
   {
      int bp; double bos;
      if(!OlderPivot(r,br+2,SwingLookback,buy,bp,bos)) continue;
      bool broke=buy?(r[br].close>bos):(r[br].close<bos);
      if(!broke || !StrongDisp(r,br,a,ReentryDisplacementATR,buy)) continue;
      int ap; double anchor;
      if(!OlderPivot(r,br+2,SwingLookback,!buy,ap,anchor) || ap<=br) continue;
      if(RequireInternalSweepForReentry && !HasInternalSweep(r,buy,br,ap,buf)) continue;
      double imp=buy?r[br].high:r[br].low; for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
      if(MathAbs(imp-anchor)<a) continue;
      double ol,oh; OTE(buy,anchor,imp,ol,oh); int pi; double pl,ph,el,eh; string pt;
      if(!FindFreshPD(r,buy,ap,br,ol,oh,pi,pl,ph,pt,el,eh)) continue;
      sig.valid=true;sig.buy=buy;sig.reentry=true;sig.flip=false;sig.anchor_idx=ap;sig.break_idx=br;sig.pd_idx=pi;sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=imp;sig.ote_low=ol;sig.ote_high=oh;sig.pd_low=pl;sig.pd_high=ph;sig.entry_low=el;sig.entry_high=eh;sig.pd_type="RE-"+pt;return true;
   }
   return false;
}

bool M15Acceptance()
{
   MqlRates r[]; ArraySetAsSeries(r,true); if(CopyRates(_Symbol,PERIOD_M15,0,20,r)<6) return false; double a=ATR(r,ATRPeriod,1); if(a<=0)return false;
   bool originalSell=(g_plan.original_direction=="SELL"); double boundary=originalSell?g_plan.zone_high:g_plan.zone_low;
   double body=MathAbs(r[1].close-r[1].open); double top=MathMax(r[1].open,r[1].close),bot=MathMin(r[1].open,r[1].close);
   double beyond=originalSell?MathMax(0.0,top-MathMax(bot,boundary)):MathMax(0.0,MathMin(top,boundary)-bot);
   bool closeBeyond=originalSell?(r[1].close>boundary):(r[1].close<boundary);
   bool single=closeBeyond && body>0 && beyond/body>=M15SingleBodyFractionBeyond && body>=M15SingleBodyATR*a;
   double b1=MathAbs(r[1].close-r[1].open),b2=MathAbs(r[2].close-r[2].open);
   bool two=originalSell?(r[1].close>boundary && r[2].close>boundary):(r[1].close<boundary && r[2].close<boundary);
   two=two && b1>=M15DoubleBodyATR*a && b2>=M15DoubleBodyATR*a;
   if(single||two){ if(g_flipAcceptedAt==0) g_flipAcceptedAt=r[1].time; return true; } return false;
}

bool BuildFlip(MqlRates &r[],double a,bool buy,Signal &sig)
{
   sig.valid=false; if(!g_flipCandidate || g_flipAcceptedAt==0) return false;
   int ret=-1; int mx=MathMin(FlipRetestMaxBars,ArraySize(r)-8);
   // Find a post-acceptance retest of the old zone from the opposite side.
   for(int i=3;i<=mx;i++)
   {
      if(r[i].time<g_flipAcceptedAt) continue;
      bool touched=TouchZone(r[i]); if(!touched) continue;
      bool fromFlipSide=buy?(r[i].open>=g_plan.zone_high || r[i].high>=g_plan.zone_high):(r[i].open<=g_plan.zone_low || r[i].low<=g_plan.zone_low);
      if(fromFlipSide){ret=i;break;}
   }
   if(RequireFlipRetest && ret<3) return false;
   if(ret<3) ret=mx;
   int bp; double bos;
   if(!OlderPivot(r,ret+2,SwingLookback,buy,bp,bos)) return false;
   int br=-1;
   for(int j=ret-1;j>=3;j--)
   {
      bool broke=buy?(r[j].close>bos):(r[j].close<bos);
      if(broke && StrongDisp(r,j,a,FlipBreakDisplacementATR,buy)){br=j;break;}
   }
   if(br<3) return false;
   double anchor=buy?r[ret].low:r[ret].high,imp=buy?r[br].high:r[br].low; for(int j=br;j>=1;j--){if(buy)imp=MathMax(imp,r[j].high);else imp=MathMin(imp,r[j].low);}
   if(MathAbs(imp-anchor)<a) return false;
   double ol,oh; OTE(buy,anchor,imp,ol,oh); int pi; double pl,ph,el,eh; string pt;
   if(!FindFreshPD(r,buy,ret,br,ol,oh,pi,pl,ph,pt,el,eh)) return false;
   sig.valid=true;sig.buy=buy;sig.reentry=false;sig.flip=true;sig.anchor_idx=ret;sig.break_idx=br;sig.pd_idx=pi;sig.anchor_price=anchor;sig.break_level=bos;sig.impulse_extreme=imp;sig.ote_low=ol;sig.ote_high=oh;sig.pd_low=pl;sig.pd_high=ph;sig.entry_low=el;sig.entry_high=eh;sig.pd_type="FLIP-"+pt;return true;
}

bool EntryAtValue(bool buy,double price,Signal &s,double a)
{
   if(price>=s.entry_low && price<=s.entry_high) return true;
   double d=MathMin(MathAbs(price-s.entry_low),MathAbs(price-s.entry_high)); return d<=a*MaxEntryChaseATR;
}

double NormalizeVolume(double v)
{
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),mx=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),st=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(st<=0)return 0; v=MathMax(mn,MathMin(mx,v)); return MathFloor(v/st+1e-9)*st;
}
double LotsForRisk(double entry,double sl,double money)
{
   double tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE),ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),d=MathAbs(entry-sl); if(tv<=0||ts<=0||d<=0||money<=0)return 0;
   return NormalizeVolume(money/((d/ts)*tv));
}
double ThesisBudget(bool flip){ double x=AccountInfoDouble(ACCOUNT_BALANCE)*ThesisRiskPct/100.0; return flip?x*FlipRiskMultiplier:x; }

double TodayPnL()
{
   MqlDateTime x; TimeToStruct(TimeCurrent(),x); x.hour=0;x.min=0;x.sec=0; datetime from=StructToTime(x); if(!HistorySelect(from,TimeCurrent())) return 0; double p=0;
   for(int i=0;i<HistoryDealsTotal();i++){ulong t=HistoryDealGetTicket(i);if(t==0)continue;if((ulong)HistoryDealGetInteger(t,DEAL_MAGIC)!=MagicNumber)continue;if(HistoryDealGetString(t,DEAL_SYMBOL)!=_Symbol)continue;p+=HistoryDealGetDouble(t,DEAL_PROFIT)+HistoryDealGetDouble(t,DEAL_SWAP)+HistoryDealGetDouble(t,DEAL_COMMISSION);}return p;
}
bool AnyOurPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i);if(t&&PositionGetString(POSITION_SYMBOL)==_Symbol&&(ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber)return true;} return false;
}
bool AllProtected()
{
   bool any=false; for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i);if(!t)continue;if(PositionGetString(POSITION_SYMBOL)!=_Symbol||(ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue;any=true;double o=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL);ENUM_POSITION_TYPE ty=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);if(sl<=0)return false;if(ty==POSITION_TYPE_BUY&&sl<o-_Point)return false;if(ty==POSITION_TYPE_SELL&&sl>o+_Point)return false;}return any;
}

bool RiskGuards()
{
   if(!IsTester() && !IsDemo()) return false; if(!g_plan.valid || g_plan.ea_mode=="WATCH_ONLY" || g_plan.ea_mode=="NO_TRADE") return false;
   MqlTick t;if(!SymbolInfoTick(_Symbol,t))return false;if((t.ask-t.bid)/_Point>MaxSpreadPoints)return false;
   double maxLoss=AccountInfoDouble(ACCOUNT_BALANCE)*ThesisRiskPct/100.0*MaxDailyLossR;if(TodayPnL()<=-maxLoss)return false;return true;
}

int Targets(bool flip,bool buy,double &t1,double &t2,double &t3,double &run)
{
   if(flip){t1=g_plan.flip_t1;t2=g_plan.flip_t2;t3=g_plan.flip_t3;run=g_plan.flip_run;}
   else{t1=g_plan.original_t1;t2=g_plan.original_t2;t3=g_plan.original_t3;run=g_plan.original_run;}
   int n=0;if(t1>0)n++;if(t2>0)n++;if(t3>0)n++;if(run>0)n++;return n;
}
bool ObjectiveReached(bool flip,bool buy,double mark)
{
   double t1,t2,t3,run;Targets(flip,buy,t1,t2,t3,run);double f=run>0?run:(t3>0?t3:(t2>0?t2:t1));if(f<=0)return false;return buy?(mark>=f):(mark<=f);
}

bool SendOrders(bool buy,double entry,double sl,double lots,bool flip,string tag,string pd)
{
   double t1,t2,t3,run; int nt=Targets(flip,buy,t1,t2,t3,run);if(nt<=0)return false;
   trade.SetExpertMagicNumber(MagicNumber);trade.SetDeviationInPoints(MaxSlippagePoints);
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      // Netting fallback: one position to T1; do not fake partial legs.
      string c="SMCV6 "+tag+" "+pd; return buy?trade.Buy(lots,_Symbol,0,sl,t1,c):trade.Sell(lots,_Symbol,0,sl,t1,c);
   }
   double s=TP1VolumePct+TP2VolumePct+RunnerVolumePct;if(s<=0)s=100;double l1=NormalizeVolume(lots*TP1VolumePct/s),l2=NormalizeVolume(lots*TP2VolumePct/s),lr=NormalizeVolume(lots*RunnerVolumePct/s);double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   bool ok=true;
   if(l1>=mn){string c="SMCV6 "+tag+" T1";bool sent=(buy?trade.Buy(l1,_Symbol,0,sl,t1,c):trade.Sell(l1,_Symbol,0,sl,t1,c));if(!sent)ok=false;}
   if(l2>=mn&&t2>0){string c="SMCV6 "+tag+" T2";bool sent=(buy?trade.Buy(l2,_Symbol,0,sl,t2,c):trade.Sell(l2,_Symbol,0,sl,t2,c));if(!sent)ok=false;}
   if(lr>=mn){string c="SMCV6 "+tag+" RUN";bool sent=(buy?trade.Buy(lr,_Symbol,0,sl,0,c):trade.Sell(lr,_Symbol,0,sl,0,c));if(!sent)ok=false;} return ok;
}

bool StructuralProgress(bool buy,MqlRates &r[])
{
   if(ArraySize(r)<BEStructureLookback+3)return false;if(buy){double h=r[2].high;for(int i=2;i<=BEStructureLookback+1;i++)h=MathMax(h,r[i].high);return r[1].close>h;}double l=r[2].low;for(int i=2;i<=BEStructureLookback+1;i++)l=MathMin(l,r[i].low);return r[1].close<l;
}

// Recover the ORIGINAL stop distance for R-multiple management.
// POSITION_SL is mutable; after BE it equals the entry and must never be used
// as the denominator for runner trailing. Prefer the opening order's SL so this
// survives terminal/EA restarts. Fall back to the current SL only before BE.
double InitialRiskDistanceForPosition(double openPrice,double currentSL)
{
   long positionId=(long)PositionGetInteger(POSITION_IDENTIFIER);
   double best=0.0;long earliest=0;
   if(positionId>0&&HistorySelectByPosition(positionId))
   {
      int total=HistoryOrdersTotal();
      for(int i=0;i<total;i++)
      {
         ulong ord=HistoryOrderGetTicket(i);if(ord==0)continue;
         ENUM_ORDER_TYPE ot=(ENUM_ORDER_TYPE)HistoryOrderGetInteger(ord,ORDER_TYPE);
         if(ot!=ORDER_TYPE_BUY&&ot!=ORDER_TYPE_SELL)continue;
         double osl=HistoryOrderGetDouble(ord,ORDER_SL);if(osl<=0)continue;
         long when=(long)HistoryOrderGetInteger(ord,ORDER_TIME_SETUP_MSC);
         double d=MathAbs(openPrice-osl);
         if(d<=_Point)continue;
         if(earliest==0||when<earliest){earliest=when;best=d;}
      }
   }
   if(best>_Point)return best;
   double fallback=MathAbs(openPrice-currentSL);
   if(currentSL>0&&fallback>_Point)return fallback;
   return 0.0;
}

void ManagePositions()
{
   MqlRates m1[],m5[];ArraySetAsSeries(m1,true);ArraySetAsSeries(m5,true);if(CopyRates(_Symbol,PERIOD_M1,0,30,m1)<20)return;double a1=ATR(m1,ATRPeriod,1);bool hm5=CopyRates(_Symbol,RunnerTrailTF,0,30,m5)>=20;double a5=hm5?ATR(m5,ATRPeriod,1):0;MqlTick tk;if(!SymbolInfoTick(_Symbol,tk))return;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);if(!ticket)continue;if(PositionGetString(POSITION_SYMBOL)!=_Symbol||(ulong)PositionGetInteger(POSITION_MAGIC)!=MagicNumber)continue;ENUM_POSITION_TYPE ty=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);bool buy=ty==POSITION_TYPE_BUY;double o=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP),mark=buy?tk.bid:tk.ask;string c=PositionGetString(POSITION_COMMENT);
      double init=InitialRiskDistanceForPosition(o,sl);if(init<=0)continue;double rnow=buy?(mark-o)/init:(o-mark)/init;double desired=sl;bool change=false;
      if(rnow>=BreakEvenArmAtR&&StructuralProgress(buy,m1)){double be=o;if((buy&&(sl==0||be>desired))||(!buy&&(sl==0||be<desired))){desired=be;change=true;}}
      if(StringFind(c," RUN")>=0&&hm5&&rnow>=RunnerTrailStartR)
      {
         double st=buy?m5[1].low:m5[1].high;for(int k=1;k<=RunnerTrailLookbackBars;k++){if(buy)st=MathMin(st,m5[k].low);else st=MathMax(st,m5[k].high);}double structural=buy?st-a5*RunnerStructureATRBuffer:st+a5*RunnerStructureATRBuffer;double at=buy?mark-a5*RunnerTrailATRMultiple:mark+a5*RunnerTrailATRMultiple;double dyn=buy?MathMax(structural,at):MathMin(structural,at);if((buy&&dyn>desired)||(!buy&&(desired==0||dyn<desired))){desired=dyn;change=true;}
      }
      if(!change)continue;desired=NormalizeDouble(desired,_Digits);if((buy&&sl>0&&desired<=sl+_Point)||(!buy&&sl>0&&desired>=sl-_Point))continue;trade.PositionModify(ticket,desired,tp);
   }
}

void Evaluate()
{
   if(!RefreshPlan()||!RiskGuards())return;
   if(EnableZoneFlip && !g_flipCandidate && M15Acceptance()){g_flipCandidate=true;Print("SMC v6: original zone accepted/invalidation confirmed -> FLIP_CANDIDATE. No instant reverse entry.");}
   MqlRates r[];ArraySetAsSeries(r,true);if(CopyRates(_Symbol,PERIOD_M1,0,180,r)<120)return;datetime cb=r[1].time;if(cb==g_lastTradeBar)return;double a=ATR(r,ATRPeriod,1);if(a<=0)return;MqlTick tk;if(!SymbolInfoTick(_Symbol,tk))return;

   bool origBuy=(g_plan.original_direction=="BUY"),flipBuy=(g_plan.flip_direction=="BUY"); Signal sig;ZeroMemory(sig);string tag="";bool useFlip=false;double share=0;
   // Original primary/re-entry is disabled immediately after accepted invalidation.
   if(!g_flipCandidate)
   {
      if(g_primaryEntries==0 && !AnyOurPosition()){if(BuildPrimary(r,a,origBuy,sig)){tag="P0";share=PrimaryRiskShare;}}
      else if(EnableReentries && g_reentries<MaxReentriesPerThesis && AllProtected() && !ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask))
      {if(BuildReentry(r,a,origBuy,sig)){tag="R"+IntegerToString(g_reentries+1);share=(g_reentries==0?Reentry1RiskShare:Reentry2RiskShare);}}
   }
   else if(EnableZoneFlip && !AnyOurPosition())
   {
      useFlip=true;
      if(g_flipPrimaryEntries==0){if(BuildFlip(r,a,flipBuy,sig)){tag="F0";share=PrimaryRiskShare;}}
   }
   else if(EnableZoneFlip && g_flipPrimaryEntries>0 && EnableReentries && g_flipReentries<MaxReentriesPerThesis && AllProtected() && !ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask))
   {
      useFlip=true;if(BuildReentry(r,a,flipBuy,sig)){sig.flip=true;tag="FR"+IntegerToString(g_flipReentries+1);share=(g_flipReentries==0?Reentry1RiskShare:Reentry2RiskShare);}
   }
   if(!sig.valid)return;double entry=sig.buy?tk.ask:tk.bid;if(!EntryAtValue(sig.buy,entry,sig,a))return;
   string seq=g_plan.analysis_id+"|"+tag+"|"+IntegerToString((int)r[sig.break_idx].time)+"|"+sig.pd_type;if(seq==g_lastSequence)return;
   double sl=sig.buy?sig.anchor_price-a*SLBufferATR:sig.anchor_price+a*SLBufferATR;sl=NormalizeDouble(sl,_Digits);entry=NormalizeDouble(entry,_Digits);
   double risk=ThesisBudget(useFlip)*share;double lots=LotsForRisk(entry,sl,risk);if(lots<=0)return;
   if(SendOrders(sig.buy,entry,sl,lots,useFlip,tag,sig.pd_type))
   {
      if(useFlip){if(tag=="F0")g_flipPrimaryEntries++;else g_flipReentries++;}else{if(tag=="P0")g_primaryEntries++;else g_reentries++;}
      g_lastSequence=seq;g_lastTradeBar=cb;Print("SMCv6 ",tag," opened. entry=",entry," sl=",sl," OTE=",sig.ote_low,"-",sig.ote_high," PD=",sig.pd_type," riskMoney=",risk);
   }
}

int OnInit()
{
   if(_Period!=PERIOD_M1){Print("Attach Sequence EA to XAUUSD M1 only.");return INIT_PARAMETERS_INCORRECT;}
   if(!IsTester() && !IsDemo()){Print("DEMO/PAPER ONLY build; refusing non-demo account.");return INIT_FAILED;}
   if(ThesisRiskPct<=0||ThesisRiskPct>2.0)return INIT_PARAMETERS_INCORRECT;if(PrimaryRiskShare+Reentry1RiskShare+Reentry2RiskShare>1.0001)return INIT_PARAMETERS_INCORRECT;
   trade.SetExpertMagicNumber(MagicNumber);
   if(OperatingMode==TESTER_FILE || IsTester()){if(!LoadTesterPlans())return INIT_FAILED;}
   EventSetTimer(MathMax(1,PollSeconds));return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){EventKillTimer();}
void OnTimer(){if(OperatingMode==LIVE_CLOUD&&!IsTester())RefreshPlan();}
void OnTick(){ManagePositions();Evaluate();}

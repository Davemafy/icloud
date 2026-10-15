#property strict
#property version   "1.15"
#property description "DEMO/PAPER London + New York 08:00 session sniper: nearest H1 swing/FVG reference, no arbitrary setup timeout."

#include <Trade/Trade.mqh>

CTrade g_trade;

enum SS_STAGE
{
   SS_WAIT_REFERENCE=0,
   SS_ARMED=1,
   SS_SWEEP_FOUND=2,
   SS_RECLAIMED=3,
   SS_DISPLACED=4,
   SS_DONE=5
};

enum SS_SIDE
{
   SS_NONE=0,
   SS_BUY=1,
   SS_SELL=-1
};

enum SS_EXT_KIND
{
   SS_EXT_NONE=0,
   SS_EXT_SWING=1,
   SS_EXT_FVG=2,
   SS_EXT_FVG_SWING_CLUSTER=3
};

string ExtKindName(const SS_EXT_KIND kind)
{
   if(kind==SS_EXT_SWING) return "SWING";
   if(kind==SS_EXT_FVG) return "FVG";
   if(kind==SS_EXT_FVG_SWING_CLUSTER) return "FVG+SWING";
   return "NONE";
}

struct SS_SESSION
{
   string   name;
   int      local_day_key;
   datetime ref_start_server;
   datetime ref_end_server;
   datetime cash_open_server;
   bool     reference_ready;
   bool     ext_low_valid;
   bool     ext_high_valid;
   SS_EXT_KIND ext_low_kind;
   SS_EXT_KIND ext_high_kind;
   double   ext_low_distal;
   double   ext_high_distal;
   datetime ext_low_source_time;
   datetime ext_high_source_time;
   double   ref_high;
   double   ref_low;
   double   ref_mid;
   double   ext_low;
   double   ext_high;
   SS_STAGE stage;
   SS_SIDE  side;
   datetime sweep_time;
   double   sweep_extreme;
   double   mss_level;
   datetime displacement_time;
   double   breaker_low;
   double   breaker_high;
   double   breaker_wick_extreme;
   bool     traded;
   string   last_reason;
};

input string InpTradeSymbol="";
input ulong  InpMagicNumber=6510010;
input bool   InpEnableLondon=true;
input bool   InpEnableNewYork=true;

// The key zone is the local 08:00-09:00 reference candle.
// Times are session-local and converted to broker-server time automatically.
input int InpReferenceHourLocal=8;
input int InpReferenceMinuteLocal=0;
input int InpReferenceMinutes=60;
input int InpNewYorkCashOpenHourLocal=9;
input int InpNewYorkCashOpenMinuteLocal=30;

// Use 9999 for automatic broker UTC offset. A manual value is useful in Strategy Tester.
input int InpManualBrokerUtcOffsetMinutes=9999;

// Nearest external H1 reference is selected independently above and below the
// 08:00-09:00 session candle: confirmed swing OR still-unfilled H1 FVG,
// whichever has the nearest eligible external price. FVG distance uses the
// nearest still-unfilled (proximal) edge.
input int    InpExternalH1LookbackBars=72;
input int    InpMinH1FVGPoints=1;

// Sniper sequence: external reference interaction -> reclaim -> displacement + micro MSS -> breaker retest -> close.
input int    InpMicroMSSLookbackBars=18;
input int    InpBreakerOriginLookbackBars=8;
input int    InpATRPeriod=14;
input double InpMinDisplacementATR=0.60;
input double InpStopBufferATR=0.08;
input double InpMinRR=2.0;

// Risk controls. DEMO/PAPER ONLY. One trade per session by design.
input double InpBaseRiskPercent=0.25;
input double InpNewYorkPreCashOpenRiskMultiplier=0.50;
input int    InpMaxSpreadPoints=50;

// Management: bank about 70% at the 0.50 Fibonacci of the 08:00-09:00
// reference range; leave about 30% to the opposite reference-side objective.
input double InpPartialPercent=70.0;
input double InpRunnerPercent=30.0;
input double InpMaxSplitDeviationPct=10.0;
input bool   InpActivateRunnerTrailAtReferenceMid=true;
input int    InpRunnerTrailLookbackBars=30;
input double InpRunnerTrailBufferATR=0.08;
input bool   InpStopAfterFirstWinningTrade=false;

SS_SESSION g_london;
SS_SESSION g_newyork;
datetime   g_last_m1_bar=0;
datetime   g_last_state_write=0;
bool       g_stop_for_day=false;
int        g_stop_day_key=0;
string     g_symbol="";

int DaysInMonth(const int y,const int m)
{
   if(m==2)
   {
      bool leap=((y%4==0 && y%100!=0) || (y%400==0));
      return leap?29:28;
   }
   if(m==4 || m==6 || m==9 || m==11) return 30;
   return 31;
}

int DayOfWeekForDate(const int y,const int m,const int d)
{
   MqlDateTime x;
   ZeroMemory(x);
   x.year=y; x.mon=m; x.day=d; x.hour=12;
   datetime t=StructToTime(x);
   MqlDateTime out;
   TimeToStruct(t,out);
   return out.day_of_week;
}

int NthSunday(const int y,const int m,const int nth)
{
   int dow=DayOfWeekForDate(y,m,1);
   int first=1+((7-dow)%7);
   return first+(nth-1)*7;
}

int LastSunday(const int y,const int m)
{
   int last=DaysInMonth(y,m);
   int dow=DayOfWeekForDate(y,m,last);
   return last-dow;
}

bool LondonDstForLocalDate(const int y,const int m,const int d)
{
   if(m>3 && m<10) return true;
   if(m<3 || m>10) return false;
   if(m==3)  return d>=LastSunday(y,3);
   if(m==10) return d<LastSunday(y,10);
   return false;
}

bool NewYorkDstForLocalDate(const int y,const int m,const int d)
{
   if(m>3 && m<11) return true;
   if(m<3 || m>11) return false;
   if(m==3)  return d>=NthSunday(y,3,2);
   if(m==11) return d<NthSunday(y,11,1);
   return false;
}

int ServerUtcOffsetSeconds()
{
   if(InpManualBrokerUtcOffsetMinutes!=9999)
      return InpManualBrokerUtcOffsetMinutes*60;

   datetime server=TimeTradeServer();
   if(server<=0) server=TimeCurrent();
   datetime gmt=TimeGMT();
   if(gmt<=0) return 0;
   return (int)(server-gmt);
}

int SessionUtcOffsetSeconds(const bool london,const MqlDateTime &local_date)
{
   if(london)
      return LondonDstForLocalDate(local_date.year,local_date.mon,local_date.day)?3600:0;
   return NewYorkDstForLocalDate(local_date.year,local_date.mon,local_date.day)?-4*3600:-5*3600;
}

int DayKey(const MqlDateTime &d)
{
   return d.year*10000+d.mon*100+d.day;
}

datetime LocalNaive(const MqlDateTime &date,const int hour,const int minute)
{
   MqlDateTime d=date;
   d.hour=hour; d.min=minute; d.sec=0;
   return StructToTime(d);
}

void ResetSession(SS_SESSION &s,const string name,const int day_key)
{
   s.name=name;
   s.local_day_key=day_key;
   s.ref_start_server=0;
   s.ref_end_server=0;
   s.cash_open_server=0;
   s.reference_ready=false;
   s.ext_low_valid=false;
   s.ext_high_valid=false;
   s.ext_low_kind=SS_EXT_NONE;
   s.ext_high_kind=SS_EXT_NONE;
   s.ext_low_distal=0;
   s.ext_high_distal=0;
   s.ext_low_source_time=0;
   s.ext_high_source_time=0;
   s.ref_high=0;
   s.ref_low=0;
   s.ref_mid=0;
   s.ext_low=0;
   s.ext_high=0;
   s.stage=SS_WAIT_REFERENCE;
   s.side=SS_NONE;
   s.sweep_time=0;
   s.sweep_extreme=0;
   s.mss_level=0;
   s.displacement_time=0;
   s.breaker_low=0;
   s.breaker_high=0;
   s.breaker_wick_extreme=0;
   s.traded=false;
   s.last_reason="WAIT_REFERENCE";
}

bool BuildSessionClock(SS_SESSION &s,const bool london,const datetime now_server)
{
   int server_off=ServerUtcOffsetSeconds();
   datetime now_utc=now_server-server_off;

   int seed_off=london?0:-5*3600;
   MqlDateTime seed;
   TimeToStruct(now_utc+seed_off,seed);
   int local_off=SessionUtcOffsetSeconds(london,seed);

   datetime local_now_naive=now_utc+local_off;
   MqlDateTime local_now;
   TimeToStruct(local_now_naive,local_now);

   // Always use TODAY in the session's local calendar. Before 08:00,
   // WAIT_REFERENCE means no prior-day levels and no entry eligibility.
   // This is a session-identity boundary, not an intraday setup timeout.
   datetime cycle_ref_local=LocalNaive(local_now,InpReferenceHourLocal,InpReferenceMinuteLocal);
   MqlDateTime cycle_date=local_now;
   local_off=SessionUtcOffsetSeconds(london,cycle_date);

   int key=DayKey(cycle_date);
   if(s.local_day_key!=key)
   {
      string prefix=london?"SS_LONDON_":"SS_NEW_YORK_";
      for(int j=ObjectsTotal(0,0,-1)-1;j>=0;j--)
      {
         string object_name=ObjectName(0,j,0,-1);
         if(StringFind(object_name,prefix)==0)
            ObjectDelete(0,object_name);
      }
      ResetSession(s,london?"LONDON":"NEW_YORK",key);
   }

   datetime end_local=cycle_ref_local+InpReferenceMinutes*60;
   datetime cash_local=LocalNaive(cycle_date,InpNewYorkCashOpenHourLocal,InpNewYorkCashOpenMinuteLocal);

   s.ref_start_server=(cycle_ref_local-local_off)+server_off;
   s.ref_end_server=(end_local-local_off)+server_off;
   s.cash_open_server=(cash_local-local_off)+server_off;
   return true;
}

bool LoadReferenceCandle(SS_SESSION &s)
{
   if(s.reference_ready) return true;

   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();
   if(now<s.ref_end_server) return false;

   MqlRates m1[];
   int copied=CopyRates(g_symbol,PERIOD_M1,s.ref_start_server,s.ref_end_server-1,m1);
   if(copied<45)
   {
      s.last_reason="REFERENCE_DATA_INCOMPLETE";
      return false;
   }

   double hi=-DBL_MAX;
   double lo=DBL_MAX;
   for(int i=0;i<copied;i++)
   {
      if(m1[i].high>hi) hi=m1[i].high;
      if(m1[i].low<lo)  lo=m1[i].low;
   }
   if(hi<=lo || hi<=0 || lo<=0)
   {
      s.last_reason="REFERENCE_RANGE_INVALID";
      return false;
   }

   s.ref_high=hi;
   s.ref_low=lo;
   s.ref_mid=(hi+lo)*0.5;

   // Pull only H1 information that existed before the session reference began.
   // CopyRates stores the oldest copied bar at the lowest physical index here.
   MqlRates h1[];
   datetime from=s.ref_start_server-(InpExternalH1LookbackBars+3)*3600;
   int n=CopyRates(g_symbol,PERIOD_H1,from,s.ref_start_server-1,h1);

   double swing_low=-DBL_MAX;
   double swing_high=DBL_MAX;
   datetime swing_low_time=0;
   datetime swing_high_time=0;

   bool fvg_low_valid=false;
   bool fvg_high_valid=false;
   double fvg_low_prox=-DBL_MAX;
   double fvg_low_distal=0;
   datetime fvg_low_time=0;
   double fvg_high_prox=DBL_MAX;
   double fvg_high_distal=0;
   datetime fvg_high_time=0;

   double point=SymbolInfoDouble(g_symbol,SYMBOL_POINT);
   double min_gap=MathMax(point,(double)InpMinH1FVGPoints*point);

   if(n>=5)
   {
      // Confirmed H1 swing candidates strictly outside the completed session range.
      for(int i=1;i<n-1;i++)
      {
         bool is_swing_low=(h1[i].low<h1[i-1].low && h1[i].low<=h1[i+1].low);
         bool is_swing_high=(h1[i].high>h1[i-1].high && h1[i].high>=h1[i+1].high);

         if(is_swing_low && h1[i].low<s.ref_low && h1[i].low>swing_low)
         {
            swing_low=h1[i].low;
            swing_low_time=h1[i].time;
         }
         if(is_swing_high && h1[i].high>s.ref_high && h1[i].high<swing_high)
         {
            swing_high=h1[i].high;
            swing_high_time=h1[i].time;
         }
      }

      // H1 FVG candidates. A fully filled gap is discarded. If partially filled,
      // use the nearest edge of the still-unfilled remainder as the proximal edge.
      for(int i=2;i<n;i++)
      {
         // Bullish FVG below price: [older high = distal, newer low = proximal].
         double bull_distal=h1[i-2].high;
         double bull_original_prox=h1[i].low;
         if((bull_original_prox-bull_distal)>=min_gap)
         {
            bool fully_filled=false;
            double remaining_prox=bull_original_prox;
            for(int j=i+1;j<n;j++)
            {
               if(h1[j].low<=bull_distal)
               {
                  fully_filled=true;
                  break;
               }
               if(h1[j].low<remaining_prox)
                  remaining_prox=h1[j].low;
            }

            if(!fully_filled && remaining_prox<s.ref_low)
            {
               // Nearest downside reference = highest eligible price below ref low.
               if(!fvg_low_valid || remaining_prox>fvg_low_prox)
               {
                  fvg_low_valid=true;
                  fvg_low_prox=remaining_prox;
                  fvg_low_distal=bull_distal;
                  fvg_low_time=h1[i].time;
               }
            }
         }

         // Bearish FVG above price: [newer high = proximal, older low = distal].
         double bear_original_prox=h1[i].high;
         double bear_distal=h1[i-2].low;
         if((bear_distal-bear_original_prox)>=min_gap)
         {
            bool fully_filled=false;
            double remaining_prox=bear_original_prox;
            for(int j=i+1;j<n;j++)
            {
               if(h1[j].high>=bear_distal)
               {
                  fully_filled=true;
                  break;
               }
               if(h1[j].high>remaining_prox)
                  remaining_prox=h1[j].high;
            }

            if(!fully_filled && remaining_prox>s.ref_high)
            {
               // Nearest upside reference = lowest eligible price above ref high.
               if(!fvg_high_valid || remaining_prox<fvg_high_prox)
               {
                  fvg_high_valid=true;
                  fvg_high_prox=remaining_prox;
                  fvg_high_distal=bear_distal;
                  fvg_high_time=h1[i].time;
               }
            }
         }
      }
   }

   bool swing_low_valid=(swing_low>-DBL_MAX/2);
   bool swing_high_valid=(swing_high<DBL_MAX/2);

   // Downside: whichever is nearer to the session low wins.
   if(fvg_low_valid && (!swing_low_valid || fvg_low_prox>=swing_low))
   {
      s.ext_low=fvg_low_prox;
      s.ext_low_distal=fvg_low_distal;
      s.ext_low_source_time=fvg_low_time;
      s.ext_low_kind=SS_EXT_FVG;
      if(swing_low_valid && swing_low>=fvg_low_distal && swing_low<=fvg_low_prox)
         s.ext_low_kind=SS_EXT_FVG_SWING_CLUSTER;
      s.ext_low_valid=true;
   }
   else if(swing_low_valid)
   {
      s.ext_low=swing_low;
      s.ext_low_distal=0;
      s.ext_low_source_time=swing_low_time;
      s.ext_low_kind=SS_EXT_SWING;
      s.ext_low_valid=true;
   }

   // Upside: whichever is nearer to the session high wins.
   if(fvg_high_valid && (!swing_high_valid || fvg_high_prox<=swing_high))
   {
      s.ext_high=fvg_high_prox;
      s.ext_high_distal=fvg_high_distal;
      s.ext_high_source_time=fvg_high_time;
      s.ext_high_kind=SS_EXT_FVG;
      if(swing_high_valid && swing_high>=fvg_high_prox && swing_high<=fvg_high_distal)
         s.ext_high_kind=SS_EXT_FVG_SWING_CLUSTER;
      s.ext_high_valid=true;
   }
   else if(swing_high_valid)
   {
      s.ext_high=swing_high;
      s.ext_high_distal=0;
      s.ext_high_source_time=swing_high_time;
      s.ext_high_kind=SS_EXT_SWING;
      s.ext_high_valid=true;
   }

   s.reference_ready=true;
   s.stage=SS_ARMED;
   s.last_reason="ARMED_NEAREST_H1_SWING_OR_FVG";
   return true;
}

double M1ATR()
{
   int handle=iATR(g_symbol,PERIOD_M1,InpATRPeriod);
   if(handle==INVALID_HANDLE) return 0;
   double buf[];
   int n=CopyBuffer(handle,0,1,1,buf);
   IndicatorRelease(handle);
   if(n!=1) return 0;
   return buf[0];
}

double RecentMicroSwing(const SS_SIDE side)
{
   int need=InpMicroMSSLookbackBars+4;
   MqlRates r[];
   ArraySetAsSeries(r,true);
   int n=CopyRates(g_symbol,PERIOD_M1,0,need,r);
   if(n<7) return 0;

   for(int j=2;j<n-1;j++)
   {
      if(side==SS_BUY)
      {
         if(r[j].high>r[j-1].high && r[j].high>=r[j+1].high)
            return r[j].high;
      }
      else if(side==SS_SELL)
      {
         if(r[j].low<r[j-1].low && r[j].low<=r[j+1].low)
            return r[j].low;
      }
   }
   return 0;
}

bool FindBreaker(const SS_SIDE side,double &body_low,double &body_high,double &wick_extreme)
{
   int need=InpBreakerOriginLookbackBars+3;
   MqlRates r[];
   ArraySetAsSeries(r,true);
   int n=CopyRates(g_symbol,PERIOD_M1,0,need,r);
   if(n<4) return false;

   for(int j=2;j<n;j++)
   {
      bool bearish=r[j].close<r[j].open;
      bool bullish=r[j].close>r[j].open;
      if(side==SS_BUY && bearish)
      {
         body_low=MathMin(r[j].open,r[j].close);
         body_high=MathMax(r[j].open,r[j].close);
         wick_extreme=r[j].low;
         return true;
      }
      if(side==SS_SELL && bullish)
      {
         body_low=MathMin(r[j].open,r[j].close);
         body_high=MathMax(r[j].open,r[j].close);
         wick_extreme=r[j].high;
         return true;
      }
   }
   return false;
}

double SpreadPoints()
{
   MqlTick tick;
   if(!SymbolInfoTick(g_symbol,tick)) return DBL_MAX;
   double point=SymbolInfoDouble(g_symbol,SYMBOL_POINT);
   if(point<=0) return DBL_MAX;
   return (tick.ask-tick.bid)/point;
}

double NormalizeVolume(double lots)
{
   double vmin=SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=vmin;
   lots=MathFloor(lots/step)*step;
   if(lots<vmin) return 0;
   lots=MathMin(vmax,lots);
   int digits=2;
   if(step>=1.0) digits=0;
   else if(step>=0.1) digits=1;
   else if(step>=0.01) digits=2;
   else digits=3;
   return NormalizeDouble(lots,digits);
}

double RiskLots(const SS_SIDE side,const double entry,const double stop,const double risk_pct)
{
   if(entry<=0 || stop<=0 || risk_pct<=0) return 0;
   ENUM_ORDER_TYPE type=(side==SS_BUY?ORDER_TYPE_BUY:ORDER_TYPE_SELL);
   double one_lot_pl=0;
   if(!OrderCalcProfit(type,g_symbol,1.0,entry,stop,one_lot_pl)) return 0;
   double loss=MathAbs(one_lot_pl);
   if(loss<=0) return 0;
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money=equity*(risk_pct/100.0);
   if(risk_money<=0) return 0;
   return NormalizeVolume(risk_money/loss);
}

bool SplitVolume7030(const double total,double &partial_lots,double &runner_lots)
{
   partial_lots=0;
   runner_lots=0;
   double vmin=SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_MIN);
   double step=SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_STEP);
   if(vmin<=0 || step<=0 || total<=0) return false;

   double sum=InpPartialPercent+InpRunnerPercent;
   if(sum<=0) return false;
   double runner_ratio=InpRunnerPercent/sum;

   double runner_steps=MathRound((total*runner_ratio)/step);
   runner_lots=runner_steps*step;
   partial_lots=total-runner_lots;

   runner_lots=NormalizeVolume(runner_lots);
   partial_lots=NormalizeVolume(partial_lots);
   if(runner_lots<vmin || partial_lots<vmin) return false;

   double actual_total=partial_lots+runner_lots;
   if(actual_total<=0 || actual_total>total+step*0.25) return false;

   double actual_partial_pct=100.0*partial_lots/actual_total;
   if(MathAbs(actual_partial_pct-InpPartialPercent)>InpMaxSplitDeviationPct)
      return false;
   return true;
}

bool CloseOwnPositionByComment(const string exact_comment)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;
      if(PositionGetString(POSITION_COMMENT)!=exact_comment) continue;
      return g_trade.PositionClose(ticket);
   }
   return true;
}

bool LatestProtectedTrailSwing(const long position_type,const datetime entry_time,double &swing_price)
{
   swing_price=0;
   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();
   datetime trail_from=(datetime)(now-InpRunnerTrailLookbackBars*60);
   datetime entry_from=(datetime)(entry_time-120);
   datetime from=(trail_from>entry_from?trail_from:entry_from);

   MqlRates r[];
   int n=CopyRates(g_symbol,PERIOD_M1,from,now-1,r);
   if(n<7) return false;

   for(int i=n-3;i>=2;i--)
   {
      if(r[i].time<=entry_time) continue;

      if(position_type==POSITION_TYPE_BUY)
      {
         bool pivot=(r[i].low<r[i-1].low && r[i].low<=r[i+1].low);
         if(!pivot) continue;
         bool protected_swing=true;
         for(int j=i+1;j<n;j++)
         {
            if(r[j].low<=r[i].low){protected_swing=false;break;}
         }
         if(protected_swing){swing_price=r[i].low;return true;}
      }
      else if(position_type==POSITION_TYPE_SELL)
      {
         bool pivot=(r[i].high>r[i-1].high && r[i].high>=r[i+1].high);
         if(!pivot) continue;
         bool protected_swing=true;
         for(int j=i+1;j<n;j++)
         {
            if(r[j].high>=r[i].high){protected_swing=false;break;}
         }
         if(protected_swing){swing_price=r[i].high;return true;}
      }
   }
   return false;
}

bool SessionWindowOpen(const SS_SESSION &s,const datetime closed_bar_time)
{
   return (closed_bar_time>=s.ref_end_server);
}

void JournalEvent(const SS_SESSION &s,const string event,const string detail)
{
   FolderCreate("TradeZone");
   FolderCreate("TradeZone\\SessionSniper");
   int h=FileOpen("TradeZone\\SessionSniper\\session_journal.csv",
                  FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,",");
   if(h==INVALID_HANDLE) return;
   if(FileSize(h)==0)
      FileWrite(h,"ts","session","day_key","event","side","ref_high","ref_low","ext_high","ext_low","detail");
   FileSeek(h,0,SEEK_END);
   string side=(s.side==SS_BUY?"BUY":(s.side==SS_SELL?"SELL":"NONE"));
   FileWrite(h,(long)TimeTradeServer(),s.name,s.local_day_key,event,side,
             DoubleToString(s.ref_high,_Digits),DoubleToString(s.ref_low,_Digits),
             s.ext_high_valid?DoubleToString(s.ext_high,_Digits):"",
             s.ext_low_valid?DoubleToString(s.ext_low,_Digits):"",detail);
   FileClose(h);
}

void UpsertSessionHLine(const string name,const double price,const ENUM_LINE_STYLE style,const int width,const string label)
{
   if(price<=0)
   {
      ObjectDelete(0,name);
      return;
   }
   if(ObjectFind(0,name)<0)
      ObjectCreate(0,name,OBJ_HLINE,0,0,price);
   ObjectSetDouble(0,name,OBJPROP_PRICE,price);
   ObjectSetInteger(0,name,OBJPROP_STYLE,style);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,width);
   ObjectSetString(0,name,OBJPROP_TEXT,label);
}

void DrawSessionLevels(const SS_SESSION &s)
{
   if(!s.reference_ready) return;
   string prefix="SS_"+s.name+"_";

   UpsertSessionHLine(prefix+"REF_HIGH",s.ref_high,STYLE_SOLID,2,s.name+" REF HIGH");
   UpsertSessionHLine(prefix+"REF_LOW",s.ref_low,STYLE_SOLID,2,s.name+" REF LOW");
   UpsertSessionHLine(prefix+"REF_MID",s.ref_mid,STYLE_DOT,1,s.name+" REF 0.50");

   if(s.ext_high_valid)
   {
      UpsertSessionHLine(prefix+"EXT_HIGH",s.ext_high,STYLE_DASH,1,
                         s.name+" EXT HIGH "+ExtKindName(s.ext_high_kind)+" PROX");
      if(s.ext_high_kind==SS_EXT_FVG || s.ext_high_kind==SS_EXT_FVG_SWING_CLUSTER)
         UpsertSessionHLine(prefix+"EXT_HIGH_FVG_DISTAL",s.ext_high_distal,STYLE_DOT,1,
                            s.name+" EXT HIGH FVG DISTAL");
      else
         ObjectDelete(0,prefix+"EXT_HIGH_FVG_DISTAL");
   }
   else
   {
      ObjectDelete(0,prefix+"EXT_HIGH");
      ObjectDelete(0,prefix+"EXT_HIGH_FVG_DISTAL");
   }

   if(s.ext_low_valid)
   {
      UpsertSessionHLine(prefix+"EXT_LOW",s.ext_low,STYLE_DASH,1,
                         s.name+" EXT LOW "+ExtKindName(s.ext_low_kind)+" PROX");
      if(s.ext_low_kind==SS_EXT_FVG || s.ext_low_kind==SS_EXT_FVG_SWING_CLUSTER)
         UpsertSessionHLine(prefix+"EXT_LOW_FVG_DISTAL",s.ext_low_distal,STYLE_DOT,1,
                            s.name+" EXT LOW FVG DISTAL");
      else
         ObjectDelete(0,prefix+"EXT_LOW_FVG_DISTAL");
   }
   else
   {
      ObjectDelete(0,prefix+"EXT_LOW");
      ObjectDelete(0,prefix+"EXT_LOW_FVG_DISTAL");
   }
}

bool PositionExistsByMagic()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)==InpMagicNumber &&
         PositionGetString(POSITION_SYMBOL)==g_symbol)
         return true;
   }
   return false;
}

bool ExecuteSessionTrade(SS_SESSION &s,const datetime now_bar)
{
   MqlTick tick;
   if(!SymbolInfoTick(g_symbol,tick)) return false;
   if(SpreadPoints()>InpMaxSpreadPoints)
   {
      s.last_reason="SPREAD_HIGH";
      return false;
   }
   if(PositionExistsByMagic())
   {
      s.last_reason="SESSION_SNIPER_POSITION_ALREADY_OPEN";
      return false;
   }

   double atr=M1ATR();
   if(atr<=0)
   {
      s.last_reason="ATR_UNAVAILABLE";
      return false;
   }

   double point=SymbolInfoDouble(g_symbol,SYMBOL_POINT);
   long broker_stops=(long)SymbolInfoInteger(g_symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double broker_buffer=(double)broker_stops*point;
   double spread_buffer=(tick.ask-tick.bid)*1.20;
   double buffer=MathMax(broker_buffer,MathMax(spread_buffer,atr*InpStopBufferATR));

   double entry=(s.side==SS_BUY?tick.ask:tick.bid);
   double stop=0;
   double full_target=0;
   double partial_target=s.ref_mid;

   if(s.side==SS_BUY)
   {
      stop=MathMin(s.sweep_extreme,s.breaker_wick_extreme)-buffer;
      full_target=s.ref_high;
      if(!(stop<entry && partial_target>entry && full_target>partial_target))
      {
         s.last_reason="BUY_GEOMETRY_INVALID";
         return false;
      }
   }
   else if(s.side==SS_SELL)
   {
      stop=MathMax(s.sweep_extreme,s.breaker_wick_extreme)+buffer;
      full_target=s.ref_low;
      if(!(stop>entry && partial_target<entry && full_target<partial_target))
      {
         s.last_reason="SELL_GEOMETRY_INVALID";
         return false;
      }
   }
   else return false;

   double risk=MathAbs(entry-stop);
   double reward=MathAbs(full_target-entry);
   double rr=(risk>0?reward/risk:0);
   if(rr<InpMinRR)
   {
      s.last_reason="RR_BELOW_MINIMUM_"+DoubleToString(rr,2);
      return false;
   }

   double risk_pct=InpBaseRiskPercent;
   if(s.name=="NEW_YORK" && now_bar<s.cash_open_server)
      risk_pct*=InpNewYorkPreCashOpenRiskMultiplier;

   double total_lots=RiskLots(s.side,entry,stop,risk_pct);
   if(total_lots<=0)
   {
      s.last_reason="LOT_CALC_FAILED";
      return false;
   }

   double partial_lots=0;
   double runner_lots=0;
   if(!SplitVolume7030(total_lots,partial_lots,runner_lots))
   {
      s.last_reason="BROKER_VOLUME_CANNOT_REPRESENT_70_30";
      JournalEvent(s,"ORDER_BLOCKED",s.last_reason);
      return false;
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(20);

   string partial_comment="SS "+s.name+" P70";
   string runner_comment="SS "+s.name+" R30";
   bool runner_ok=false;
   bool partial_ok=false;

   // Open the runner first. If the 70% leg cannot open, close the runner immediately
   // so the bundle never leaves unintended residual risk.
   if(s.side==SS_BUY)
      runner_ok=g_trade.Buy(runner_lots,g_symbol,0,stop,0,runner_comment);
   else
      runner_ok=g_trade.Sell(runner_lots,g_symbol,0,stop,0,runner_comment);

   if(!runner_ok)
   {
      s.last_reason="RUNNER_ORDER_FAILED_"+IntegerToString((int)g_trade.ResultRetcode());
      JournalEvent(s,"ORDER_REJECTED",s.last_reason);
      return false;
   }

   if(s.side==SS_BUY)
      partial_ok=g_trade.Buy(partial_lots,g_symbol,0,stop,partial_target,partial_comment);
   else
      partial_ok=g_trade.Sell(partial_lots,g_symbol,0,stop,partial_target,partial_comment);

   if(!partial_ok)
   {
      string fail_reason="PARTIAL_ORDER_FAILED_"+IntegerToString((int)g_trade.ResultRetcode());
      CloseOwnPositionByComment(runner_comment);
      s.last_reason=fail_reason;
      JournalEvent(s,"ORDER_BUNDLE_ABORTED",s.last_reason);
      return false;
   }

   s.traded=true;
   s.stage=SS_DONE;
   s.last_reason="ENTRY_OPENED_70_30_RR_"+DoubleToString(rr,2);
   JournalEvent(s,"ENTRY_OPENED",s.last_reason+
      "|p70="+DoubleToString(partial_lots,2)+
      "|r30="+DoubleToString(runner_lots,2)+
      "|mid="+DoubleToString(partial_target,_Digits)+
      "|runner_objective_telemetry="+DoubleToString(full_target,_Digits)+"|runner_tp=NONE");
   return true;
}

void ProcessSession(SS_SESSION &s,const bool london,const MqlRates &bar)
{
   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();

   BuildSessionClock(s,london,now);
   if(now<s.ref_end_server)
   {
      s.last_reason=(now<s.ref_start_server?"WAIT_TODAYS_REFERENCE_START":"BUILDING_TODAYS_REFERENCE");
      return;
   }
   if(!LoadReferenceCandle(s)) return;
   DrawSessionLevels(s);

   if(g_stop_for_day)
   {
      s.last_reason="DAILY_STOP_AFTER_WIN";
      return;
   }
   if(s.traded || s.stage==SS_DONE) return;
   if(!SessionWindowOpen(s,bar.time)) return;

   bool bullish=bar.close>bar.open;
   bool bearish=bar.close<bar.open;

   // No clock expiry. A developing setup ends only by structural consumption
   // or when the next local 08:00 reference lifecycle replaces it.
   if(s.side==SS_BUY && s.stage>=SS_SWEEP_FOUND && s.stage<SS_DONE && bar.high>=s.ref_high)
   {
      s.stage=SS_DONE;
      s.last_reason="BUY_OBJECTIVE_REACHED_BEFORE_ENTRY";
      JournalEvent(s,"SESSION_CONSUMED",s.last_reason);
      return;
   }
   if(s.side==SS_SELL && s.stage>=SS_SWEEP_FOUND && s.stage<SS_DONE && bar.low<=s.ref_low)
   {
      s.stage=SS_DONE;
      s.last_reason="SELL_OBJECTIVE_REACHED_BEFORE_ENTRY";
      JournalEvent(s,"SESSION_CONSUMED",s.last_reason);
      return;
   }

   if(s.stage==SS_ARMED)
   {
      bool long_sweep=s.ext_low_valid && bar.low<=s.ref_low && bar.low<=s.ext_low;
      bool short_sweep=s.ext_high_valid && bar.high>=s.ref_high && bar.high>=s.ext_high;

      if(long_sweep && short_sweep)
      {
         s.stage=SS_DONE;
         s.last_reason="AMBIGUOUS_TWO_SIDED_SWEEP";
         JournalEvent(s,"SESSION_BLOCKED",s.last_reason);
         return;
      }

      if(long_sweep)
      {
         s.side=SS_BUY;
         s.sweep_time=bar.time;
         s.sweep_extreme=bar.low;
         s.mss_level=RecentMicroSwing(SS_BUY);
         s.stage=SS_SWEEP_FOUND;
         string hit_kind=ExtKindName(s.ext_low_kind);
         s.last_reason=(s.mss_level>0?"BUY_NEAREST_EXTERNAL_"+hit_kind+"_HIT":"BUY_"+hit_kind+"_HIT_NO_MSS_LEVEL");
         JournalEvent(s,"EXTERNAL_SWEEP",s.last_reason);
         return;
      }

      if(short_sweep)
      {
         s.side=SS_SELL;
         s.sweep_time=bar.time;
         s.sweep_extreme=bar.high;
         s.mss_level=RecentMicroSwing(SS_SELL);
         s.stage=SS_SWEEP_FOUND;
         string hit_kind=ExtKindName(s.ext_high_kind);
         s.last_reason=(s.mss_level>0?"SELL_NEAREST_EXTERNAL_"+hit_kind+"_HIT":"SELL_"+hit_kind+"_HIT_NO_MSS_LEVEL");
         JournalEvent(s,"EXTERNAL_SWEEP",s.last_reason);
         return;
      }

      if(!s.ext_low_valid && !s.ext_high_valid)
         s.last_reason="NO_QUALIFIED_EXTERNAL_H1_SWING_OR_FVG";
      return;
   }

   if(s.stage==SS_SWEEP_FOUND)
   {
      if(s.side==SS_BUY && bar.time>s.sweep_time && bullish && bar.close>s.ref_low)
      {
         s.stage=SS_RECLAIMED;
         s.last_reason="BUY_REFERENCE_LOW_RECLAIMED";
         JournalEvent(s,"REFERENCE_RECLAIM",s.last_reason);
         return;
      }
      if(s.side==SS_SELL && bar.time>s.sweep_time && bearish && bar.close<s.ref_high)
      {
         s.stage=SS_RECLAIMED;
         s.last_reason="SELL_REFERENCE_HIGH_RECLAIMED";
         JournalEvent(s,"REFERENCE_RECLAIM",s.last_reason);
         return;
      }
      return;
   }

   if(s.stage==SS_RECLAIMED)
   {
      double atr=M1ATR();
      if(atr<=0 || s.mss_level<=0) return;
      double body=MathAbs(bar.close-bar.open);
      bool displaced=(body>=atr*InpMinDisplacementATR);

      if(s.side==SS_BUY && bullish && displaced && bar.close>s.mss_level)
      {
         double bl,bh,we;
         if(!FindBreaker(SS_BUY,bl,bh,we))
         {
            s.last_reason="BUY_MSS_NO_BREAKER";
            return;
         }
         s.breaker_low=bl; s.breaker_high=bh; s.breaker_wick_extreme=we;
         s.displacement_time=bar.time;
         s.stage=SS_DISPLACED;
         s.last_reason="BUY_MSS_DISPLACEMENT_CONFIRMED";
         JournalEvent(s,"MSS_DISPLACEMENT",s.last_reason);
         return;
      }

      if(s.side==SS_SELL && bearish && displaced && bar.close<s.mss_level)
      {
         double bl,bh,we;
         if(!FindBreaker(SS_SELL,bl,bh,we))
         {
            s.last_reason="SELL_MSS_NO_BREAKER";
            return;
         }
         s.breaker_low=bl; s.breaker_high=bh; s.breaker_wick_extreme=we;
         s.displacement_time=bar.time;
         s.stage=SS_DISPLACED;
         s.last_reason="SELL_MSS_DISPLACEMENT_CONFIRMED";
         JournalEvent(s,"MSS_DISPLACEMENT",s.last_reason);
         return;
      }
      return;
   }

   if(s.stage==SS_DISPLACED)
   {
            if(bar.time<=s.displacement_time) return;

      bool overlaps=(bar.low<=s.breaker_high && bar.high>=s.breaker_low);
      double mid=(s.breaker_low+s.breaker_high)*0.5;

      if(s.side==SS_BUY && overlaps && bullish && bar.close>=mid)
      {
         s.last_reason="BUY_BREAKER_RETEST_DIRECTIONAL_CLOSE";
         JournalEvent(s,"BREAKER_RETEST",s.last_reason);
         ExecuteSessionTrade(s,bar.time);
         return;
      }

      if(s.side==SS_SELL && overlaps && bearish && bar.close<=mid)
      {
         s.last_reason="SELL_BREAKER_RETEST_DIRECTIONAL_CLOSE";
         JournalEvent(s,"BREAKER_RETEST",s.last_reason);
         ExecuteSessionTrade(s,bar.time);
         return;
      }
   }
}

void ManageRunnerTrail()
{
   if(!InpActivateRunnerTrailAtReferenceMid) return;

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol,tick)) return;
   double atr=M1ATR();
   if(atr<=0) return;

   double point=SymbolInfoDouble(g_symbol,SYMBOL_POINT);
   long broker_stops=(long)SymbolInfoInteger(g_symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double broker_buffer=(double)broker_stops*point;
   double spread_buffer=(tick.ask-tick.bid)*1.20;
   double buffer=MathMax(broker_buffer,MathMax(spread_buffer,atr*InpRunnerTrailBufferATR));

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;

      string comment=PositionGetString(POSITION_COMMENT);
      if(StringFind(comment," R30")<0) continue;

      long type=PositionGetInteger(POSITION_TYPE);
      double sl=PositionGetDouble(POSITION_SL);
      double tp=PositionGetDouble(POSITION_TP);
      datetime entry_time=(datetime)PositionGetInteger(POSITION_TIME);

      double ref_mid=0;
      if(StringFind(comment,"LONDON")>=0) ref_mid=g_london.ref_mid;
      else if(StringFind(comment,"NEW_YORK")>=0) ref_mid=g_newyork.ref_mid;
      if(ref_mid<=0) continue;

      bool midpoint_reached=false;
      if(type==POSITION_TYPE_BUY) midpoint_reached=(tick.bid>=ref_mid);
      else if(type==POSITION_TYPE_SELL) midpoint_reached=(tick.ask<=ref_mid);
      if(!midpoint_reached) continue;

      double swing=0;
      if(!LatestProtectedTrailSwing(type,entry_time,swing)) continue;

      double desired=0;
      if(type==POSITION_TYPE_BUY)
      {
         desired=NormalizeDouble(swing-buffer,_Digits);
         double max_allowed=NormalizeDouble(tick.bid-broker_buffer,_Digits);
         desired=MathMin(desired,max_allowed);
         if(desired<=0 || desired>=tick.bid) continue;
         if(sl>0 && desired<=sl+point) continue;
      }
      else if(type==POSITION_TYPE_SELL)
      {
         desired=NormalizeDouble(swing+buffer,_Digits);
         double min_allowed=NormalizeDouble(tick.ask+broker_buffer,_Digits);
         desired=MathMax(desired,min_allowed);
         if(desired<=tick.ask) continue;
         if(sl>0 && desired>=sl-point) continue;
      }
      if(!g_trade.PositionModify(ticket,desired,tp))
         Print("SessionSniper v0.15 runner trail modify failed ticket=",ticket,
               " desiredSL=",desired," retcode=",g_trade.ResultRetcode());
   }
}

void WriteState()
{
   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();
   if(now-g_last_state_write<5) return;
   g_last_state_write=now;

   FolderCreate("TradeZone");
   FolderCreate("TradeZone\\SessionSniper");
   int h=FileOpen("TradeZone\\SessionSniper\\state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;

   FileWriteString(h,"version=0.14\r\n");
   FileWriteString(h,"paper_only=1\r\n");
   FileWriteString(h,"symbol="+g_symbol+"\r\n");
   FileWriteString(h,"restart_safe="+(PositionExistsByMagic()?"0":"1")+"\r\n");
   FileWriteString(h,"stop_for_day="+(g_stop_for_day?"1":"0")+"\r\n");
   FileWriteString(h,"management=70_PERCENT_AT_REFERENCE_MID_30_PERCENT_TRAIL_ONLY_NO_HARD_TP\r\n");

   FileWriteString(h,"london_day="+IntegerToString(g_london.local_day_key)+"\r\n");
   FileWriteString(h,"london_stage="+IntegerToString((int)g_london.stage)+"\r\n");
   FileWriteString(h,"london_reason="+g_london.last_reason+"\r\n");
   FileWriteString(h,"london_ref_high="+DoubleToString(g_london.ref_high,_Digits)+"\r\n");
   FileWriteString(h,"london_ref_low="+DoubleToString(g_london.ref_low,_Digits)+"\r\n");
   FileWriteString(h,"london_ext_high="+(g_london.ext_high_valid?DoubleToString(g_london.ext_high,_Digits):"NONE")+"\r\n");
   FileWriteString(h,"london_ext_high_kind="+ExtKindName(g_london.ext_high_kind)+"\r\n");
   FileWriteString(h,"london_ext_high_distal="+((g_london.ext_high_valid && g_london.ext_high_distal>0)?DoubleToString(g_london.ext_high_distal,_Digits):"NONE")+"\r\n");
   FileWriteString(h,"london_ext_low="+(g_london.ext_low_valid?DoubleToString(g_london.ext_low,_Digits):"NONE")+"\r\n");
   FileWriteString(h,"london_ext_low_kind="+ExtKindName(g_london.ext_low_kind)+"\r\n");
   FileWriteString(h,"london_ext_low_distal="+((g_london.ext_low_valid && g_london.ext_low_distal>0)?DoubleToString(g_london.ext_low_distal,_Digits):"NONE")+"\r\n");

   FileWriteString(h,"ny_day="+IntegerToString(g_newyork.local_day_key)+"\r\n");
   FileWriteString(h,"ny_stage="+IntegerToString((int)g_newyork.stage)+"\r\n");
   FileWriteString(h,"ny_reason="+g_newyork.last_reason+"\r\n");
   FileWriteString(h,"ny_ref_high="+DoubleToString(g_newyork.ref_high,_Digits)+"\r\n");
   FileWriteString(h,"ny_ref_low="+DoubleToString(g_newyork.ref_low,_Digits)+"\r\n");
   FileWriteString(h,"ny_ext_high="+(g_newyork.ext_high_valid?DoubleToString(g_newyork.ext_high,_Digits):"NONE")+"\r\n");
   FileWriteString(h,"ny_ext_high_kind="+ExtKindName(g_newyork.ext_high_kind)+"\r\n");
   FileWriteString(h,"ny_ext_high_distal="+((g_newyork.ext_high_valid && g_newyork.ext_high_distal>0)?DoubleToString(g_newyork.ext_high_distal,_Digits):"NONE")+"\r\n");
   FileWriteString(h,"ny_ext_low="+(g_newyork.ext_low_valid?DoubleToString(g_newyork.ext_low,_Digits):"NONE")+"\r\n");
   FileWriteString(h,"ny_ext_low_kind="+ExtKindName(g_newyork.ext_low_kind)+"\r\n");
   FileWriteString(h,"ny_ext_low_distal="+((g_newyork.ext_low_valid && g_newyork.ext_low_distal>0)?DoubleToString(g_newyork.ext_low_distal,_Digits):"NONE")+"\r\n");
   FileClose(h);
}

void ResetDailyStopIfNeeded()
{
   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();
   MqlDateTime d;
   TimeToStruct(now,d);
   int key=DayKey(d);
   if(g_stop_day_key!=key)
   {
      g_stop_day_key=key;
      g_stop_for_day=false;
   }
}


/*
 * Standalone chart observations only. The panel never changes trading
 * authority, session state, risk or the stable Institutional Sequence EA.
 * Objects have their own SS_INFO prefix so a new session can clear old
 * reference HLines without accidentally deleting this panel.
 */
string SS_PanelStatus(const SS_SESSION &s,const datetime now)
{
   if(s.ref_start_server<=0 || s.ref_end_server<=0) return "WAITING FOR CLOCK";
   if(now<s.ref_start_server) return "WAITING";
   if(now<s.ref_end_server) return "BUILDING REFERENCE";
   if(!s.reference_ready)
   {
      if(s.last_reason=="REFERENCE_DATA_INCOMPLETE") return "DATA INCOMPLETE";
      return "WAITING FOR CLOSED DATA";
   }
   if(s.stage==SS_ARMED) return "ARMED";
   if(s.stage==SS_SWEEP_FOUND) return "SWEEP FOUND";
   if(s.stage==SS_RECLAIMED) return "RECLAIMED";
   if(s.stage==SS_DISPLACED) return "DISPLACED";
   if(s.stage==SS_DONE) return "DONE";
   return "WAITING";
}

string SS_Price(const double value)
{
   return DoubleToString(value,(int)SymbolInfoInteger(g_symbol,SYMBOL_DIGITS));
}

string SS_ReferenceLine(const SS_SESSION &s)
{
   if(!s.reference_ready) return "H: --  L: --  MID: --";
   return "H: "+SS_Price(s.ref_high)+"  L: "+SS_Price(s.ref_low)+"  MID: "+SS_Price(s.ref_mid);
}

string SS_ExternalLine(const SS_SESSION &s)
{
   if(!s.reference_ready) return "H1 BSL: --    H1 SSL: --";
   string bsl=s.ext_high_valid?(ExtKindName(s.ext_high_kind)+" "+SS_Price(s.ext_high)):"NONE";
   string ssl=s.ext_low_valid?(ExtKindName(s.ext_low_kind)+" "+SS_Price(s.ext_low)):"NONE";
   return "H1 BSL: "+bsl+"  |  SSL: "+ssl;
}

void SS_DrawPanelRow(const int row,const string value,const color ink)
{
   string name="SS_INFO_ROW_"+IntegerToString(row);
   if(ObjectFind(0,name)<0)
      ObjectCreate(0,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_CORNER,CORNER_RIGHT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_ANCHOR,ANCHOR_RIGHT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,27);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,52+row*19);
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,9);
   ObjectSetString(0,name,OBJPROP_FONT,"Consolas");
   ObjectSetInteger(0,name,OBJPROP_COLOR,ink);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,name,OBJPROP_HIDDEN,true);
   ObjectSetString(0,name,OBJPROP_TEXT,value);
}

void SS_DrawInformationPanel()
{
   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();

   string bg="SS_INFO_BACKGROUND";
   if(ObjectFind(0,bg)<0)
      ObjectCreate(0,bg,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,bg,OBJPROP_CORNER,CORNER_RIGHT_UPPER);
   ObjectSetInteger(0,bg,OBJPROP_XDISTANCE,14);
   ObjectSetInteger(0,bg,OBJPROP_YDISTANCE,40);
   ObjectSetInteger(0,bg,OBJPROP_XSIZE,465);
   ObjectSetInteger(0,bg,OBJPROP_YSIZE,194);
   ObjectSetInteger(0,bg,OBJPROP_BGCOLOR,C'13,21,32');
   ObjectSetInteger(0,bg,OBJPROP_COLOR,C'68,91,115');
   ObjectSetInteger(0,bg,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,bg,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,bg,OBJPROP_HIDDEN,true);

   SS_DrawPanelRow(0,"SESSION SNIPER v0.15  |  DEMO ONLY",clrWhite);
   SS_DrawPanelRow(1,"LONDON  "+IntegerToString(g_london.local_day_key)+"  |  "+SS_PanelStatus(g_london,now),clrLightSkyBlue);
   SS_DrawPanelRow(2,SS_ReferenceLine(g_london),clrWhite);
   SS_DrawPanelRow(3,SS_ExternalLine(g_london),clrSilver);
   SS_DrawPanelRow(4,"STAGE: "+SS_PanelStatus(g_london,now)+" | "+g_london.last_reason,clrSilver);
   SS_DrawPanelRow(5,"NEW YORK  "+IntegerToString(g_newyork.local_day_key)+"  |  "+SS_PanelStatus(g_newyork,now),clrLightSkyBlue);
   SS_DrawPanelRow(6,SS_ReferenceLine(g_newyork),clrWhite);
   SS_DrawPanelRow(7,SS_ExternalLine(g_newyork),clrSilver);
   SS_DrawPanelRow(8,"STAGE: "+SS_PanelStatus(g_newyork,now)+" | "+g_newyork.last_reason,clrSilver);
   ChartRedraw(0);
}

void SS_RemoveInformationPanel()
{
   ObjectDelete(0,"SS_INFO_BACKGROUND");
   for(int i=0;i<9;i++)
      ObjectDelete(0,"SS_INFO_ROW_"+IntegerToString(i));
}

int OnInit()
{
   long mode=AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode!=ACCOUNT_TRADE_MODE_DEMO)
   {
      Print("SessionSniper v0.15 HARD BLOCK: DEMO account required.");
      return INIT_FAILED;
   }
   long margin_mode=AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(margin_mode!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("SessionSniper v0.15 HARD BLOCK: hedging-mode MT5 account required for exact 70/30 legs.");
      return INIT_FAILED;
   }

   g_symbol=(StringLen(InpTradeSymbol)>0?InpTradeSymbol:_Symbol);
   if(!SymbolSelect(g_symbol,true))
   {
      Print("SessionSniper v0.15: cannot select symbol ",g_symbol);
      return INIT_FAILED;
   }

   ResetSession(g_london,"LONDON",0);
   ResetSession(g_newyork,"NEW_YORK",0);
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   EventSetTimer(1);
   Print("SessionSniper v0.15 active. DEMO/PAPER ONLY. London/NY 08:00 local reference; nearest external H1 swing or unfilled FVG contract.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   SS_RemoveInformationPanel();
   EventKillTimer();
}

void OnTimer()
{
   ResetDailyStopIfNeeded();
   datetime now=TimeTradeServer();
   if(now<=0) now=TimeCurrent();
   if(InpEnableLondon) BuildSessionClock(g_london,true,now);
   if(InpEnableNewYork) BuildSessionClock(g_newyork,false,now);
   ManageRunnerTrail();
   SS_DrawInformationPanel();
   WriteState();
}

void OnTick()
{
   ResetDailyStopIfNeeded();
   ManageRunnerTrail();

   datetime bar0=iTime(g_symbol,PERIOD_M1,0);
   if(bar0<=0 || bar0==g_last_m1_bar)
   {
      WriteState();
      return;
   }
   g_last_m1_bar=bar0;

   MqlRates bar[];
   ArraySetAsSeries(bar,true);
   if(CopyRates(g_symbol,PERIOD_M1,0,3,bar)<3)
      return;

   if(InpEnableLondon)
      ProcessSession(g_london,true,bar[1]);
   if(InpEnableNewYork)
      ProcessSession(g_newyork,false,bar[1]);

   WriteState();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(!HistoryDealSelect(trans.deal)) return;

   if((ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=InpMagicNumber) return;
   long entry_type=HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   if(entry_type!=DEAL_ENTRY_OUT && entry_type!=DEAL_ENTRY_OUT_BY) return;

   double net=HistoryDealGetDouble(trans.deal,DEAL_PROFIT)
             +HistoryDealGetDouble(trans.deal,DEAL_SWAP)
             +HistoryDealGetDouble(trans.deal,DEAL_COMMISSION);

   if(InpStopAfterFirstWinningTrade && net>0)
   {
      g_stop_for_day=true;
      Print("SessionSniper v0.15: positive closed trade -> daily stop engaged.");
   }
}

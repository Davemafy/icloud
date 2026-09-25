#property strict
#property script_show_inputs
#property description "Trade Zone Master Sniper 6.5.90 historical data exporter. NO TRADING."

input string XauSymbol="XAUUSD";
input string DxySymbol="DXYUSD";
input datetime TestStart=D'2026.06.01 00:00';
input datetime TestEnd=D'2026.08.31 23:59';
input bool ExportUsdNews=true;
input string OutputFolder="TradeZoneBacktest\\MasterSniperV659";

struct ExportStat
{
   string name;
   int rows;
};

string ImpactName(ENUM_CALENDAR_EVENT_IMPORTANCE importance)
{
   if(importance==CALENDAR_IMPORTANCE_HIGH)return "HIGH";
   if(importance==CALENDAR_IMPORTANCE_MODERATE)return "MEDIUM";
   if(importance==CALENDAR_IMPORTANCE_LOW)return "LOW";
   return "NONE";
}

datetime WarmupStart(ENUM_TIMEFRAMES tf)
{
   int days=2;
   if(tf==PERIOD_D1)days=500;
   else if(tf==PERIOD_H4)days=180;
   else if(tf==PERIOD_H1)days=60;
   else if(tf==PERIOD_M15)days=15;
   else if(tf==PERIOD_M1)days=2;
   return TestStart-(datetime)(days*86400);
}

bool EnsureHistory(string symbol,ENUM_TIMEFRAMES tf,datetime from,datetime to)
{
   if(!SymbolSelect(symbol,true))
   {
      Print("HISTORY_EXPORT FAIL symbol select ",symbol," err=",GetLastError());
      return false;
   }

   MqlRates probe[];
   ResetLastError();
   int copied=CopyRates(symbol,tf,from,to,probe);
   if(copied<=0)
   {
      Print("HISTORY_EXPORT FAIL CopyRates ",symbol," tf=",EnumToString(tf)," err=",GetLastError());
      return false;
   }
   return true;
}

int ExportBars(string fileName,string symbol,ENUM_TIMEFRAMES tf)
{
   datetime from=WarmupStart(tf);
   datetime to=TestEnd+PeriodSeconds(tf);
   if(!EnsureHistory(symbol,tf,from,to))return -1;

   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   MqlRates bars[];
   ArraySetAsSeries(bars,false);
   ResetLastError();
   int copied=CopyRates(symbol,tf,from,to,bars);
   if(copied<=0)
   {
      Print("HISTORY_EXPORT FAIL CopyRates ",symbol," tf=",EnumToString(tf)," err=",GetLastError());
      return -1;
   }

   string path=OutputFolder+"\\"+fileName;
   int h=FileOpen(path,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(h==INVALID_HANDLE)
   {
      Print("HISTORY_EXPORT FAIL FileOpen ",path," err=",GetLastError());
      return -1;
   }

   FileWrite(h,"ts","open","high","low","close","tick_volume");
   int rows=0;
   for(int i=0;i<copied;i++)
   {
      if(bars[i].time<=0)continue;
      FileWrite(
         h,
         (long)bars[i].time,
         DoubleToString(bars[i].open,digits),
         DoubleToString(bars[i].high,digits),
         DoubleToString(bars[i].low,digits),
         DoubleToString(bars[i].close,digits),
         (long)bars[i].tick_volume
      );
      rows++;
   }
   FileClose(h);
   Print("HISTORY_EXPORT PASS ",fileName," rows=",rows);
   return rows;
}

int ExportNewsCsv()
{
   string path=OutputFolder+"\\news.csv";
   int h=FileOpen(path,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(h==INVALID_HANDLE)
   {
      Print("HISTORY_EXPORT FAIL news FileOpen err=",GetLastError());
      return -1;
   }

   FileWrite(h,"ts","currency","title","impact");
   if(!ExportUsdNews)
   {
      FileClose(h);
      Print("HISTORY_EXPORT PASS news.csv rows=0 (disabled)");
      return 0;
   }

   datetime from=TestStart-7*86400;
   datetime to=TestEnd+86400;
   MqlCalendarValue values[];
   ResetLastError();
   int count=CalendarValueHistory(values,from,to,"","USD");
   if(count<0)
   {
      int err=GetLastError();
      FileClose(h);
      Print("HISTORY_EXPORT WARN economic calendar unavailable err=",err,"; empty news.csv created.");
      return 0;
   }

   int rows=0;
   ulong lastEvent=0;
   datetime lastTime=0;
   for(int i=0;i<count;i++)
   {
      if(values[i].time<from||values[i].time>to)continue;
      if(values[i].event_id==lastEvent&&values[i].time==lastTime)continue;

      MqlCalendarEvent eventInfo;
      if(!CalendarEventById(values[i].event_id,eventInfo))continue;

      FileWrite(
         h,
         (long)values[i].time,
         "USD",
         eventInfo.name,
         ImpactName(eventInfo.importance)
      );
      lastEvent=values[i].event_id;
      lastTime=values[i].time;
      rows++;
   }

   FileClose(h);
   Print("HISTORY_EXPORT PASS news.csv rows=",rows);
   return rows;
}

bool ValidRange()
{
   if(TestStart<=0||TestEnd<=0||TestEnd<=TestStart)
   {
      Print("HISTORY_EXPORT FAIL invalid TestStart/TestEnd.");
      return false;
   }
   return true;
}

void WriteManifest(ExportStat &stats[],int newsRows)
{
   string manifest=OutputFolder+"\\export_manifest.txt";
   int h=FileOpen(manifest,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE)
   {
      Print("HISTORY_EXPORT FAIL manifest FileOpen err=",GetLastError());
      return;
   }

   FileWriteString(h,"contract=MASTER_SNIPER_V659_HISTORY_EXPORT_V1\r\n");
   FileWriteString(h,"xau_symbol="+XauSymbol+"\r\n");
   FileWriteString(h,"dxy_symbol="+DxySymbol+"\r\n");
   FileWriteString(h,"test_start="+IntegerToString((int)TestStart)+"\r\n");
   FileWriteString(h,"test_end="+IntegerToString((int)TestEnd)+"\r\n");
   FileWriteString(h,"news_rows="+IntegerToString(newsRows)+"\r\n");
   for(int i=0;i<ArraySize(stats);i++)
      FileWriteString(h,stats[i].name+"_rows="+IntegerToString(stats[i].rows)+"\r\n");
   FileClose(h);
}

void OnStart()
{
   Print("HISTORY_EXPORT START | NO TRADING | Master Sniper 6.5.90 replay input");
   if(!ValidRange())return;

   FolderCreate("TradeZoneBacktest",FILE_COMMON);
   FolderCreate(OutputFolder,FILE_COMMON);

   ExportStat stats[];
   ArrayResize(stats,8);
   stats[0].name="XAU_D1.csv";stats[0].rows=ExportBars(stats[0].name,XauSymbol,PERIOD_D1);
   stats[1].name="XAU_H4.csv";stats[1].rows=ExportBars(stats[1].name,XauSymbol,PERIOD_H4);
   stats[2].name="XAU_H1.csv";stats[2].rows=ExportBars(stats[2].name,XauSymbol,PERIOD_H1);
   stats[3].name="XAU_M15.csv";stats[3].rows=ExportBars(stats[3].name,XauSymbol,PERIOD_M15);
   stats[4].name="XAU_M1.csv";stats[4].rows=ExportBars(stats[4].name,XauSymbol,PERIOD_M1);
   stats[5].name="DXY_D1.csv";stats[5].rows=ExportBars(stats[5].name,DxySymbol,PERIOD_D1);
   stats[6].name="DXY_H4.csv";stats[6].rows=ExportBars(stats[6].name,DxySymbol,PERIOD_H4);
   stats[7].name="DXY_H1.csv";stats[7].rows=ExportBars(stats[7].name,DxySymbol,PERIOD_H1);

   int newsRows=ExportNewsCsv();
   bool ok=(newsRows>=0);
   for(int i=0;i<ArraySize(stats);i++)
      if(stats[i].rows<=0)ok=false;

   WriteManifest(stats,newsRows);

   if(ok)
   {
      Print("HISTORY_EXPORT PASS OVERALL | folder=Common\\Files\\",OutputFolder);
      Print("HISTORY_EXPORT END | NO ORDERS WERE SENT.");
   }
   else
   {
      Print("HISTORY_EXPORT FAIL OVERALL | one or more required history files were empty.");
   }
}

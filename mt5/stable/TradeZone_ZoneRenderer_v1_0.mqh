#ifndef TRADEZONE_ZONE_RENDERER_V1_0_MQH
#define TRADEZONE_ZONE_RENDERER_V1_0_MQH

// Visual-only chart renderer. It never sends orders, changes positions, or alters risk.
// V659 presentation: muted Primary shading, outline-only Reserve context, and explicit
// read-only execution-ownership labels so a visible zone cannot be mistaken for authority.
#define TZR_PREFIX "AITS_ZONE_"
#define TZR_MAX_ZONES 4

input bool RenderCloudZones=true;
input bool RenderZonesOnAllXauTimeframes=true;
input bool RenderReserveZones=true;
input bool RenderZoneLabels=true;
input int RenderZoneHistoryHours=24;
input int RenderZoneFutureHours=48;

struct TZR_Zone
{
   bool valid;
   string id;
   string role;
   string direction;
   string state;
   string grade;
   string source_tf;
   datetime source_ts;
   int touches;
   double zone_low;
   double zone_high;
   double core_low;
   double core_high;
   bool execution_authority;
   bool active_thesis;
};

TZR_Zone g_tzrZones[TZR_MAX_ZONES];
int g_tzrZoneCount=0;
string g_tzrAnalysisId="";
string g_tzrSelectedZoneId="";
bool g_tzrThesisLocked=false;
string g_tzrThesisDirection="";
string g_tzrThesisStatus="";
string g_tzrThesisOwnerZoneId="";
bool g_tzrThesisOwnerPresent=false;
bool g_tzrOppositeExecutionBlocked=false;
bool g_tzrNoChase=false;
bool g_tzrFreshM1Required=false;
double g_tzrNextObjective=0.0;

string TZR_KV(string text,string key)
{
   string needle=key+"=";
   int p=StringFind(text,needle);
   if(p<0)return "";
   int from=p+StringLen(needle);
   int e=StringFind(text,"\n",from);
   if(e<0)e=StringLen(text);
   string value=StringSubstr(text,from,e-from);
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

void TZR_ResetOne(int idx)
{
   if(idx<0 || idx>=TZR_MAX_ZONES)return;
   g_tzrZones[idx].valid=false;
   g_tzrZones[idx].id="";
   g_tzrZones[idx].role="";
   g_tzrZones[idx].direction="";
   g_tzrZones[idx].state="";
   g_tzrZones[idx].grade="";
   g_tzrZones[idx].source_tf="";
   g_tzrZones[idx].source_ts=0;
   g_tzrZones[idx].touches=0;
   g_tzrZones[idx].zone_low=0;
   g_tzrZones[idx].zone_high=0;
   g_tzrZones[idx].core_low=0;
   g_tzrZones[idx].core_high=0;
   g_tzrZones[idx].execution_authority=false;
   g_tzrZones[idx].active_thesis=false;
}

void TZR_Reset()
{
   for(int i=0;i<TZR_MAX_ZONES;i++)TZR_ResetOne(i);
   g_tzrZoneCount=0;
   g_tzrAnalysisId="";
   g_tzrSelectedZoneId="";
   g_tzrThesisLocked=false;
   g_tzrThesisDirection="";
   g_tzrThesisStatus="";
   g_tzrThesisOwnerZoneId="";
   g_tzrThesisOwnerPresent=false;
   g_tzrOppositeExecutionBlocked=false;
   g_tzrNoChase=false;
   g_tzrFreshM1Required=false;
   g_tzrNextObjective=0.0;
}

bool TZR_ReadFeed()
{
   string text;
   if(!Get("/mt5/zones",text))return false;

   TZR_Reset();
   g_tzrAnalysisId=TZR_KV(text,"analysis_id");
   g_tzrSelectedZoneId=TZR_KV(text,"selected_zone_id");
   g_tzrThesisLocked=(TZR_KV(text,"active_thesis_locked")=="1");
   g_tzrThesisDirection=TZR_KV(text,"active_thesis_direction");
   g_tzrThesisStatus=TZR_KV(text,"active_thesis_status");
   g_tzrThesisOwnerZoneId=TZR_KV(text,"active_thesis_owner_zone_id");
   g_tzrThesisOwnerPresent=(TZR_KV(text,"active_thesis_owner_zone_present")=="1");
   g_tzrOppositeExecutionBlocked=(TZR_KV(text,"active_thesis_opposite_execution_blocked")=="1");
   g_tzrNoChase=(TZR_KV(text,"active_thesis_no_chase")=="1");
   g_tzrFreshM1Required=(TZR_KV(text,"active_thesis_fresh_m1_confirmation_required")=="1");
   g_tzrNextObjective=StringToDouble(TZR_KV(text,"active_thesis_next_objective"));

   int count=(int)StringToInteger(TZR_KV(text,"zone_count"));
   count=MathMax(0,MathMin(TZR_MAX_ZONES,count));

   for(int i=0;i<count;i++)
   {
      string p="zone"+IntegerToString(i+1)+"_";
      TZR_Zone z;
      z.valid=true;
      z.id=TZR_KV(text,p+"id");
      z.role=TZR_KV(text,p+"role");
      z.direction=TZR_KV(text,p+"direction");
      z.state=TZR_KV(text,p+"state");
      z.grade=TZR_KV(text,p+"grade");
      z.source_tf=TZR_KV(text,p+"source_tf");
      z.source_ts=(datetime)StringToInteger(TZR_KV(text,p+"source_ts"));
      z.touches=(int)StringToInteger(TZR_KV(text,p+"touches"));
      z.zone_low=StringToDouble(TZR_KV(text,p+"zone_low"));
      z.zone_high=StringToDouble(TZR_KV(text,p+"zone_high"));
      z.core_low=StringToDouble(TZR_KV(text,p+"core_low"));
      z.core_high=StringToDouble(TZR_KV(text,p+"core_high"));
      z.execution_authority=(TZR_KV(text,p+"execution_authority")=="1");
      z.active_thesis=(TZR_KV(text,p+"active_thesis")=="1");

      if(z.id=="" || z.zone_low<=0 || z.zone_high<=z.zone_low || z.core_low<=0 || z.core_high<=z.core_low)
         z.valid=false;
      g_tzrZones[i]=z;
   }
   g_tzrZoneCount=count;
   return true;
}

string TZR_SafeName(string s)
{
   StringReplace(s," ","_");
   StringReplace(s,"|","_");
   StringReplace(s,"/","_");
   StringReplace(s,"\\","_");
   StringReplace(s,">","_");
   StringReplace(s,"<","_");
   return s;
}

void TZR_DeleteObjects(long chart)
{
   int total=ObjectsTotal(chart,0,-1);
   for(int i=total-1;i>=0;i--)
   {
      string name=ObjectName(chart,i,0,-1);
      if(StringFind(name,TZR_PREFIX)==0)ObjectDelete(chart,name);
   }
}

color TZR_EnvelopeColor(string direction,bool reserve)
{
   if(direction=="BUY")return reserve?C'86,116,92':C'76,132,88';
   return reserve?C'126,100,108':C'150,92,108';
}

color TZR_CoreColor(string direction,bool reserve)
{
   if(direction=="BUY")return reserve?C'98,130,103':C'58,151,79';
   return reserve?C'142,111,119':C'174,78,99';
}

bool TZR_Rect(long chart,string name,datetime left,datetime right,double low,double high,color c,ENUM_LINE_STYLE style,int width,bool fill)
{
   if(low<=0 || high<=low || right<=left)return false;
   if(!ObjectCreate(chart,name,OBJ_RECTANGLE,0,left,high,right,low))return false;
   ObjectSetInteger(chart,name,OBJPROP_COLOR,c);
   ObjectSetInteger(chart,name,OBJPROP_STYLE,style);
   ObjectSetInteger(chart,name,OBJPROP_WIDTH,width);
   ObjectSetInteger(chart,name,OBJPROP_FILL,fill);
   ObjectSetInteger(chart,name,OBJPROP_BACK,true);
   ObjectSetInteger(chart,name,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(chart,name,OBJPROP_SELECTED,false);
   ObjectSetInteger(chart,name,OBJPROP_HIDDEN,true);
   ObjectSetInteger(chart,name,OBJPROP_ZORDER,width);
   return true;
}

bool TZR_Label(long chart,string name,datetime when,double price,string text,color c)
{
   if(!RenderZoneLabels || text=="" || price<=0)return false;
   if(!ObjectCreate(chart,name,OBJ_TEXT,0,when,price))return false;
   ObjectSetString(chart,name,OBJPROP_TEXT,text);
   ObjectSetString(chart,name,OBJPROP_FONT,"Arial");
   ObjectSetInteger(chart,name,OBJPROP_FONTSIZE,8);
   ObjectSetInteger(chart,name,OBJPROP_COLOR,c);
   ObjectSetInteger(chart,name,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
   ObjectSetInteger(chart,name,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(chart,name,OBJPROP_SELECTED,false);
   ObjectSetInteger(chart,name,OBJPROP_HIDDEN,true);
   ObjectSetInteger(chart,name,OBJPROP_ZORDER,4);
   return true;
}

void TZR_DrawZone(long chart,TZR_Zone &z,int idx)
{
   if(!z.valid)return;
   bool reserve=(z.role=="RESERVE");
   if(reserve && !RenderReserveZones)return;

   datetime now=TimeTradeServer();
   if(now<=0)now=TimeCurrent();
   int hist=MathMax(1,RenderZoneHistoryHours);
   int future=MathMax(1,RenderZoneFutureHours);
   datetime left=z.source_ts;
   datetime floor_time=now-hist*3600;
   if(left<=0 || left>now || left<floor_time)left=floor_time;
   datetime right=now+future*3600;

   string base=TZR_PREFIX+IntegerToString(idx+1)+"_"+TZR_SafeName(z.id)+"_";
   ENUM_LINE_STYLE env_style=reserve?STYLE_DOT:STYLE_SOLID;
   ENUM_LINE_STYLE core_style=reserve?STYLE_DASH:STYLE_SOLID;
   int core_width=z.active_thesis?3:(reserve?1:2);
   color env_color=TZR_EnvelopeColor(z.direction,reserve);
   color core_color=TZR_CoreColor(z.direction,reserve);

   // Primary keeps soft shading; Reserve is outline-only context so it cannot
   // visually compete with the actionable primary zone.
   TZR_Rect(chart,base+"ENV",left,right,z.zone_low,z.zone_high,env_color,env_style,1,!reserve);
   TZR_Rect(chart,base+"CORE",left,right,z.core_low,z.core_high,core_color,core_style,core_width,!reserve);

   string label=z.direction+" "+z.role;
   if(z.grade!="")label+=" | "+z.grade;
   if(z.state!="")label+=" | "+z.state;
   label+=" | T"+IntegerToString(z.touches);
   if(z.active_thesis)
      label+=" | EXECUTION OWNER";
   else if(reserve)
      label+=" | CONTEXT ONLY";
   else if(g_tzrThesisLocked)
      label+=" | WATCH ONLY | NO M1 AUTHORITY";
   else if(z.execution_authority)
      label+=" | EXECUTION";
   else
      label+=" | MAP CONTEXT";
   TZR_Label(chart,base+"LBL",left,z.zone_high,label,z.active_thesis?clrGold:core_color);
}

void TZR_Render()
{
   long chart=ChartFirst();
   while(chart>=0)
   {
      if(ChartSymbol(chart)==XauSymbol && (RenderZonesOnAllXauTimeframes || ChartPeriod(chart)==PERIOD_M1))
      {
         TZR_DeleteObjects(chart);
         if(RenderCloudZones)
         {
            for(int i=0;i<TZR_MAX_ZONES;i++)
               if(g_tzrZones[i].valid)TZR_DrawZone(chart,g_tzrZones[i],i);
         }
         ChartRedraw(chart);
      }
      chart=ChartNext(chart);
   }
}

void TZR_RefreshAndRender()
{
   if(!RenderCloudZones)
   {
      TZR_Reset();
      TZR_Render();
      return;
   }
   if(TZR_ReadFeed())TZR_Render();
}

void TZR_ClearAll()
{
   long chart=ChartFirst();
   while(chart>=0)
   {
      if(ChartSymbol(chart)==XauSymbol)
      {
         TZR_DeleteObjects(chart);
         ChartRedraw(chart);
      }
      chart=ChartNext(chart);
   }
   TZR_Reset();
}

#endif

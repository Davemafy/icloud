void ML24_ProcessCandidate(int index,int rejectedIndex,string model,string role,bool buy,bool flipBranch,Signal &sig,bool pattern,bool entryValue,bool zoneContext,bool recentZone,bool runtimeKnown,bool guardOk,bool cloudAllowed,bool localAllowed,bool path,bool priorityBlocked,MqlRates &r[],double a,MqlTick &tk,datetime barTs)
{
   if(!pattern&&(!ObserveRejectedCandidates||!zoneContext||index!=rejectedIndex))return;
   string reasons="";
   if(!runtimeKnown)ML24_AddReason(reasons,"RUNTIME_STATE_UNKNOWN");
   if(ml24_live_block)ML24_AddReason(reasons,"CLOUD_LIVE_BLOCK:"+ml24_live_block_reason);
   if(!guardOk)ML24_AddReason(reasons,"RISK_GUARD_BLOCK");
   if(!cloudAllowed)ML24_AddReason(reasons,"CLOUD_MODEL_NOT_ALLOWED");
   if(!localAllowed)ML24_AddReason(reasons,"LOCAL_REGIME_NOT_ALLOWED");
   if(!path)ML24_AddReason(reasons,"EXECUTION_PATH_NOT_ACTIVE");
   if(priorityBlocked)ML24_AddReason(reasons,"HIGHER_PRIORITY_MODEL_AVAILABLE");
   if(!pattern)ML24_AddReason(reasons,"PATTERN_NOT_COMPLETE");
   if(pattern&&!entryValue)ML24_AddReason(reasons,"ENTRY_NOT_AT_VALUE");
   bool eligible=runtimeKnown&&guardOk&&cloudAllowed&&localAllowed&&path&&!priorityBlocked&&pattern&&entryValue;
   ML24_SendCandidate(model,role,buy,flipBranch,sig,pattern,eligible,reasons,zoneContext,recentZone,cloudAllowed,localAllowed,priorityBlocked,r,a,tk,barTs);
}

void ML24_ObserveClosedBar()
{
   if(!EnableMLObservation||OperatingMode!=LIVE_CLOUD||IsTester())return;
   if(!ML24_RefreshContext(false)||!g_plan.valid||!ml24_profile_ready)return;
   if(EnableZoneFlip&&!g_flipCandidate&&M15Acceptance())g_flipCandidate=true;

   MqlRates r[];ArraySetAsSeries(r,true);
   if(CopyRates(_Symbol,PERIOD_M1,0,480,r)<160)return;
   datetime barTs=r[1].time;if(barTs<=0||barTs==ml24_last_bar)return;ml24_last_bar=barTs;
   double a=ATR(r,ATRPeriod,1);if(a<=0)return;
   MqlTick tk;if(!SymbolInfoTick(_Symbol,tk))return;
   string regime=ML24_LocalRegime(r);
   bool origBuy=(g_plan.original_direction=="BUY"),flipBuy=(g_plan.flip_direction=="BUY");
   bool recentZone=ML24_RecentZone(r,ObservationLookbackBars);
   bool zoneContext=recentZone||(ML24_ZoneDistance((tk.ask+tk.bid)/2.0)<=a*ObservationZoneDistanceATR)||g_flipCandidate;
   bool guardOk=RiskGuards()&&!ml24_live_block;

   string runtimeVersion=ML24_ReadState("version");bool runtimeKnown=(runtimeVersion!="");
   int rp=ML24_StateInt("primary_entries"),rr=ML24_StateInt("reentries"),rfp=ML24_StateInt("flip_primary_entries"),rfr=ML24_StateInt("flip_reentries"),ropen=ML24_StateInt("open_positions");
   if(!runtimeKnown){rp=0;rr=0;rfp=0;rfr=0;ropen=0;}
   bool flipActive=g_flipCandidate||rfp>0||rfr>0;

   Signal sIctP,sIctR,sMom,sVwap,sOrb,sFlipP,sFlipR;
   ZeroMemory(sIctP);ZeroMemory(sIctR);ZeroMemory(sMom);ZeroMemory(sVwap);ZeroMemory(sOrb);ZeroMemory(sFlipP);ZeroMemory(sFlipR);
   bool pIctP=BuildPrimary(r,a,origBuy,sIctP);
   bool pIctR=BuildReentry(r,a,origBuy,sIctR);
   bool pMom=ML24_BuildMomentum(r,a,origBuy,sMom);
   bool pVwap=ML24_BuildVWAP(r,a,origBuy,sVwap);
   bool pOrb=ML24_BuildORB(r,a,origBuy,sOrb);
   bool pFlipP=false,pFlipR=false;
   if(flipActive){pFlipP=BuildFlip(r,a,flipBuy,sFlipP);pFlipR=BuildReentry(r,a,flipBuy,sFlipR);if(pFlipR)sFlipR.flip=true;}

   bool eIctP=ML24_EntryValue(sIctP,tk,a),eIctR=ML24_EntryValue(sIctR,tk,a),eMom=ML24_EntryValue(sMom,tk,a),eVwap=ML24_EntryValue(sVwap,tk,a),eOrb=ML24_EntryValue(sOrb,tk,a),eFlipP=ML24_EntryValue(sFlipP,tk,a),eFlipR=ML24_EntryValue(sFlipR,tk,a);

   bool primaryPath=!flipActive&&rp==0&&ropen==0;
   bool reentryPath=!flipActive&&EnableReentries&&rp>0&&rr<MaxReentriesPerThesis&&ropen>0&&AllProtected()&&!ObjectiveReached(false,origBuy,origBuy?tk.bid:tk.ask);
   bool flipPrimaryPath=flipActive&&EnableZoneFlip&&rfp==0&&ropen==0;
   bool flipReentryPath=flipActive&&EnableZoneFlip&&EnableReentries&&rfp>0&&rfr<MaxReentriesPerThesis&&ropen>0&&AllProtected()&&!ObjectiveReached(true,flipBuy,flipBuy?tk.bid:tk.ask);
   string altRole=primaryPath?"PRIMARY":reentryPath?"REENTRY":"INACTIVE";

   bool setupCont=(g_plan.setup_type=="CONTINUATION");
   bool localMom=ML24_LocalAllows("MOMENTUM_PULLBACK",regime),localVwap=ML24_LocalAllows("VWAP_PROXY_RECLAIM",regime),localOrb=ML24_LocalAllows("OPENING_RANGE_RETEST",regime);
   bool pathOrbPrimary=primaryPath&&EnableAlternativePrimary&&setupCont&&recentZone&&ml24_allow_orb&&localOrb;
   bool pathMomPrimary=primaryPath&&EnableAlternativePrimary&&setupCont&&recentZone&&ml24_allow_momentum&&localMom;
   bool pathVwapPrimary=primaryPath&&EnableAlternativePrimary&&setupCont&&recentZone&&ml24_allow_vwap&&localVwap;
   bool pathMomRe=reentryPath&&ml24_allow_momentum&&localMom;
   bool pathVwapRe=reentryPath&&ml24_allow_vwap&&localVwap;
   bool pathOrbRe=reentryPath&&ml24_allow_orb&&localOrb;
   bool orbPriority=(altRole=="PRIMARY")?(pathOrbPrimary&&pOrb):(pathOrbRe&&pOrb);
   bool momPriority=(altRole=="PRIMARY")?(pathMomPrimary&&pMom):(pathMomRe&&pMom);
   bool vwapPriority=(altRole=="PRIMARY")?(pathVwapPrimary&&pVwap):(pathVwapRe&&pVwap);

   int rejectedIndex=(RejectedSampleEveryBars<=1)?(ml24_reject_cursor%7):((int)(barTs/60/RejectedSampleEveryBars)%7);ml24_reject_cursor++;

   ML24_ProcessCandidate(0,rejectedIndex,"ICT_SNIPER","PRIMARY",origBuy,false,sIctP,pIctP,eIctP,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_ict,true,primaryPath,false,r,a,tk,barTs);
   ML24_ProcessCandidate(1,rejectedIndex,"ICT_DEEP_REENTRY","REENTRY",origBuy,false,sIctR,pIctR,eIctR,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_reentry,true,reentryPath,false,r,a,tk,barTs);

   bool momPath=(altRole=="PRIMARY")?pathMomPrimary:pathMomRe;
   bool momBlocked=(altRole=="PRIMARY")?(pIctP||orbPriority):pIctR;
   ML24_ProcessCandidate(2,rejectedIndex,"MOMENTUM_PULLBACK",altRole,origBuy,false,sMom,pMom,eMom,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_momentum,localMom,momPath,momBlocked,r,a,tk,barTs);

   bool vwapPath=(altRole=="PRIMARY")?pathVwapPrimary:pathVwapRe;
   bool vwapBlocked=(altRole=="PRIMARY")?(pIctP||orbPriority||momPriority):(pIctR||momPriority);
   ML24_ProcessCandidate(3,rejectedIndex,"VWAP_PROXY_RECLAIM",altRole,origBuy,false,sVwap,pVwap,eVwap,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_vwap,localVwap,vwapPath,vwapBlocked,r,a,tk,barTs);

   bool orbPath=(altRole=="PRIMARY")?pathOrbPrimary:pathOrbRe;
   bool orbBlocked=(altRole=="PRIMARY")?pIctP:(pIctR||momPriority||vwapPriority);
   ML24_ProcessCandidate(4,rejectedIndex,"OPENING_RANGE_RETEST",altRole,origBuy,false,sOrb,pOrb,eOrb,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_orb,localOrb,orbPath,orbBlocked,r,a,tk,barTs);

   ML24_ProcessCandidate(5,rejectedIndex,"ACCEPTED_ZONE_FLIP","FLIP_PRIMARY",flipBuy,true,sFlipP,pFlipP,eFlipP,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_flip,true,flipPrimaryPath,false,r,a,tk,barTs);
   ML24_ProcessCandidate(6,rejectedIndex,"ACCEPTED_ZONE_FLIP_REENTRY","FLIP_REENTRY",flipBuy,true,sFlipR,pFlipR,eFlipR,zoneContext,recentZone,runtimeKnown,guardOk,ml24_allow_flip,true,flipReentryPath,false,r,a,tk,barTs);

   ML24_WriteState(regime);
}

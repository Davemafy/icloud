from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import statistics, uuid
from typing import Optional

from .config import SETTINGS
from .models import Analysis, Bar, Direction, Grade, LiquidityLevel, MarketSnapshot, Zone, ZoneState
from .risk_matrix import RISK_MODEL, execution_grade_eligible, flip_risk_pct, original_risk_pct, zone_risk_context

GRADE_RANK={Grade.A_PLUS:0,Grade.A:1,Grade.B_PLUS:2,Grade.REJECT:9}
TF_RANK={"D1>H4>H1":0,"D1>H4":1,"H4>H1":2,"D1>H1":3,"H4":4,"H1":5}

@dataclass
class Origin:
    direction: Direction; low: float; high: float; source_ts: int; tf: str
    displacement_index: int; strength: float; fvg: bool

@dataclass
class Candidate:
    direction: Direction; low: float; high: float; source_tf: str; source_ts: int
    method: str; components: list[Origin]

def _rng(b:Bar)->float:return max(0.0,b.high-b.low)
def _body(b:Bar)->float:return abs(b.close-b.open)
def atr(bars:list[Bar],n:int=14)->float:
    if not bars:return 0.0
    tr=[]
    for i,b in enumerate(bars):
        pc=bars[i-1].close if i else b.close
        tr.append(max(b.high-b.low,abs(b.high-pc),abs(b.low-pc)))
    x=tr[-n:]; return sum(x)/max(1,len(x))
def _median_range(bars:list[Bar],n:int=20)->float:
    x=[_rng(b) for b in bars[-n:] if _rng(b)>0]; return statistics.median(x) if x else 0.0

def _pivot_high(a:list[Bar],i:int)->bool:
    return i>=2 and i+2<len(a) and all(a[i].high>a[j].high for j in range(i-2,i+3) if j!=i)
def _pivot_low(a:list[Bar],i:int)->bool:
    return i>=2 and i+2<len(a) and all(a[i].low<a[j].low for j in range(i-2,i+3) if j!=i)
def _pivots(a:list[Bar],n:int=8):
    hs=[];ls=[]
    for i in range(2,len(a)-2):
        if _pivot_high(a,i):hs.append((i,a[i].high))
        if _pivot_low(a,i):ls.append((i,a[i].low))
    return hs[-n:],ls[-n:]

def structure_bias(a:list[Bar])->Direction:
    hs,ls=_pivots(a,4)
    if len(hs)>=2 and len(ls)>=2:
        if hs[-1][1]>hs[-2][1] and ls[-1][1]>ls[-2][1]:return Direction.BUY
        if hs[-1][1]<hs[-2][1] and ls[-1][1]<ls[-2][1]:return Direction.SELL
    return Direction.NEUTRAL

def _fvg(a:list[Bar],i:int,d:Direction)->bool:
    if i<1 or i+1>=len(a):return False
    return a[i+1].low>a[i-1].high if d==Direction.BUY else a[i+1].high<a[i-1].low

def displacement_origins(a:list[Bar],tf:str,max_items:int=18)->list[Origin]:
    if len(a)<30:return []
    med=_median_range(a,20); out=[]
    if med<=0:return out
    for i in range(max(8,len(a)-180),len(a)-1):
        b=a[i]; r=_rng(b)
        if r<1.55*med or _body(b)/max(r,1e-9)<0.55:continue
        d=Direction.BUY if b.close>b.open else Direction.SELL
        prev=a[max(0,i-8):i]
        broke=b.close>max(x.high for x in prev) if d==Direction.BUY else b.close<min(x.low for x in prev)
        if not broke:continue
        oi=None
        for j in range(i-1,max(-1,i-6),-1):
            opp=(d==Direction.BUY and a[j].close<a[j].open) or (d==Direction.SELL and a[j].close>a[j].open)
            if opp:oi=j;break
        if oi is None:oi=i-1
        o=a[oi]; lo,hi=sorted((o.open,o.close))
        if lo==hi:lo,hi=o.low,o.high
        out.append(Origin(d,lo,hi,o.ts,tf,i,round(r/med,3),_fvg(a,i,d)))
    ded=[]
    for o in reversed(out):
        if any(o.direction==x.direction and _overlap(o.low,o.high,x.low,x.high,0) for x in ded):continue
        ded.append(o)
        if len(ded)>=max_items:break
    return list(reversed(ded))

def _overlap(a:float,b:float,c:float,d:float,pad:float=0)->bool:return not (b<c-pad or d<a-pad)
def _cluster(origins:list[Origin],preferred:Origin):
    lo=max(x.low for x in origins); hi=min(x.high for x in origins)
    if lo<=hi:return lo,hi,"STRICT_PREEXISTING_HTF_OVERLAP"
    return preferred.low,preferred.high,"PARENT_SUPPORTED_HTF_REFINEMENT"

def build_candidates(s:MarketSnapshot)->list[Candidate]:
    d1=displacement_origins(s.xau_d1,"D1");h4=displacement_origins(s.xau_h4,"H4");h1=displacement_origins(s.xau_h1,"H1")
    pad=max(.01,.2*(s.atr_h1 or atr(s.xau_h1))); out=[]
    for d in (Direction.BUY,Direction.SELL):
        D=[x for x in d1 if x.direction==d];H=[x for x in h4 if x.direction==d];I=[x for x in h1 if x.direction==d]
        for x in I:
            ph=[q for q in H if _overlap(q.low,q.high,x.low,x.high,pad)]
            pd=[q for q in D if _overlap(q.low,q.high,x.low,x.high,2*pad)]
            if ph and pd:
                h=min(ph,key=lambda q:abs((q.low+q.high-x.low-x.high)/2));dd=min(pd,key=lambda q:abs((q.low+q.high-x.low-x.high)/2))
                lo,hi,m=_cluster([dd,h,x],x);out.append(Candidate(d,lo,hi,"D1>H4>H1",x.source_ts,m,[dd,h,x]))
            elif ph:
                h=min(ph,key=lambda q:abs((q.low+q.high-x.low-x.high)/2));lo,hi,m=_cluster([h,x],x);out.append(Candidate(d,lo,hi,"H4>H1",x.source_ts,m,[h,x]))
            elif pd:
                dd=min(pd,key=lambda q:abs((q.low+q.high-x.low-x.high)/2));lo,hi,m=_cluster([dd,x],x);out.append(Candidate(d,lo,hi,"D1>H1",x.source_ts,m,[dd,x]))
        for h in H:
            if any(c.direction==d and _overlap(c.low,c.high,h.low,h.high,pad) for c in out):continue
            pd=[q for q in D if _overlap(q.low,q.high,h.low,h.high,2*pad)]
            if pd:
                dd=min(pd,key=lambda q:abs((q.low+q.high-h.low-h.high)/2));lo,hi,m=_cluster([dd,h],h);out.append(Candidate(d,lo,hi,"D1>H4",h.source_ts,m,[dd,h]))
            else:out.append(Candidate(d,h.low,h.high,"H4",h.source_ts,"H4_CONFIRMED_ORIGIN",[h]))
    return out

def liquidity_map(s:MarketSnapshot)->list[LiquidityLevel]:
    raw=[];now=s.mid
    for tf,a,n in (("D1",s.xau_d1,5),("H4",s.xau_h4,8),("H1",s.xau_h1,12)):
        hs,ls=_pivots(a,n)
        raw += [(f"{tf}_BSL",p,tf) for _,p in hs]+[(f"{tf}_SSL",p,tf) for _,p in ls]
    if len(s.xau_d1)>=2:raw += [("PDH",s.xau_d1[-2].high,"D1"),("PDL",s.xau_d1[-2].low,"D1")]
    base=int(now//10)*10
    raw += [("PSY",float(base+k*10),"PSY") for k in range(-4,6)]
    out=[];seen=[]
    for label,p,tf in sorted(raw,key=lambda x:x[1]):
        if p<=0 or any(abs(p-q)<max(s.point*5,.05) for q in seen):continue
        seen.append(p);out.append(LiquidityLevel(label=label,price=round(p,5),side="ABOVE" if p>now else "BELOW",source_tf=tf,distance=round(abs(p-now),5)))
    return out

def _bias(s:MarketSnapshot)->Direction:
    v=[structure_bias(s.xau_d1),structure_bias(s.xau_h4),structure_bias(s.xau_h1)]
    if v.count(Direction.BUY)>=2:return Direction.BUY
    if v.count(Direction.SELL)>=2:return Direction.SELL
    return Direction.NEUTRAL

def _dxy(s:MarketSnapshot)->Direction:
    v=[structure_bias(s.dxy_d1),structure_bias(s.dxy_h4),structure_bias(s.dxy_h1)]
    if v.count(Direction.BUY)>v.count(Direction.SELL):return Direction.BUY
    if v.count(Direction.SELL)>v.count(Direction.BUY):return Direction.SELL
    return Direction.NEUTRAL

def _location_score(d:Direction,mid:float,s:MarketSnapshot,liq:list[LiquidityLevel])->float:
    score=0.0
    for a,n,w in ((s.xau_d1,80,2.5),(s.xau_h4,120,2),(s.xau_h1,160,1.5)):
        t=a[-n:] if len(a)>=n else a
        if not t:continue
        hi=max(x.high for x in t);lo=min(x.low for x in t);eq=(hi+lo)/2;width=max(hi-lo,1e-9);pos=max(0,min(1,(mid-lo)/width))
        score += w*pos if d==Direction.SELL else w*(1-pos)
        if (d==Direction.SELL and mid>=eq) or (d==Direction.BUY and mid<=eq):score+=.75*w
    cap=1.5*(s.atr_h1 or atr(s.xau_h1))
    if d==Direction.SELL:near=[x for x in liq if x.side=="ABOVE" and 0<x.price-mid<=cap]
    else:near=[x for x in liq if x.side=="BELOW" and 0<mid-x.price<=cap]
    return round(score+min(2,.35*len(near)),4)

def _touches(lo:float,hi:float,source_ts:int,m15:list[Bar])->int:
    n=0;eng=False
    for b in m15:
        if b.ts<=source_ts:continue
        hit=b.high>=lo and b.low<=hi
        if hit and not eng:n+=1;eng=True
        elif not hit:eng=False
    return n

def _targets(d:Direction,ref:float,liq:list[LiquidityLevel])->list[float]:
    vals=sorted({x.price for x in liq if x.price>ref}) if d==Direction.BUY else sorted({x.price for x in liq if x.price<ref},reverse=True)
    return vals[:4]

def _zone(c:Candidate,s:MarketSnapshot,liq:list[LiquidityLevel],bias:Direction,n:int)->Zone:
    mid=(c.low+c.high)/2;loc=_location_score(c.direction,mid,s,liq); h1a=s.atr_h1 or atr(s.xau_h1);m15a=s.atr_m15 or atr(s.xau_m15)
    cap=max(1e-9,min(1.5*h1a,.75*atr(s.xau_h4),.30*atr(s.xau_d1)))
    zlo,zhi=c.low,c.high;notes=[]
    if c.direction==Direction.SELL:
        near=[x for x in liq if x.price>=zhi and x.price-mid<=cap]
        if near:
            q=max(near,key=lambda x:x.price);zhi=max(zhi,q.price+.15*m15a);notes.append(f"distal_liquidity:{q.label}@{q.price:.3f}")
    else:
        near=[x for x in liq if x.price<=zlo and mid-x.price<=cap]
        if near:
            q=min(near,key=lambda x:x.price);zlo=min(zlo,q.price-.15*m15a);notes.append(f"distal_liquidity:{q.label}@{q.price:.3f}")
    touches=_touches(zlo,zhi,c.source_ts,s.xau_m15); conf=[]
    if ">" in c.source_tf:conf.append("HTF_OVERLAP")
    if any(x.fvg for x in c.components):conf.append("HISTORICAL_DISPLACEMENT_FVG")
    if any(x.strength>=2 for x in c.components):conf.append("INSTITUTIONAL_DISPLACEMENT")
    if loc>=7:conf.append("PREMIUM_DISCOUNT_EXTREMITY")
    if notes:conf.append("EXTERNAL_LIQUIDITY_ADJACENCY")
    ot=_targets(c.direction,mid,liq); flip=c.direction.opposite();ft=_targets(flip,zhi if flip==Direction.BUY else zlo,liq)
    clear=abs(ot[0]-mid) if ot else 0;counter=bias not in (Direction.NEUTRAL,c.direction); need=SETTINGS.clear_run_countertrend if counter else SETTINGS.clear_run_with_trend
    if touches>=SETTINGS.zone_retire_touch_count or len(set(conf))<SETTINGS.zone_min_independent_confluences or clear<need:grade=Grade.REJECT
    else:
        score=(2 if c.source_tf=="D1>H4>H1" else 1 if ">" in c.source_tf else 0)+(2 if loc>=8 else 1 if loc>=6 else 0)+(1 if touches==0 else 0)+(1 if "INSTITUTIONAL_DISPLACEMENT" in conf else 0)
        grade=Grade.A_PLUS if score>=6 else Grade.A if score>=4 else Grade.B_PLUS
    vals=ot+[0]*(4-len(ot));fvals=ft+[0]*(4-len(ft));inv=zhi if c.direction==Direction.SELL else zlo
    dxy=_dxy(s);support="NEUTRAL" if dxy==Direction.NEUTRAL else "SUPPORT" if ((c.direction==Direction.SELL and dxy==Direction.BUY) or (c.direction==Direction.BUY and dxy==Direction.SELL)) else "CONFLICT"
    return Zone(zone_id=f"Z_{c.source_tf.replace('>','')}_{c.direction.value}_{n}",original_direction=c.direction,flip_direction=flip,setup_type="REVERSAL" if counter else "CONTINUATION",source_tf=c.source_tf,grade=grade,state=ZoneState.RETIRED if touches>=SETTINGS.zone_retire_touch_count else ZoneState.ACTIVE,core_low=round(c.low,5),core_high=round(c.high,5),core_method=c.method,location_score=loc,zone_low=round(zlo,5),zone_high=round(zhi,5),touch_count=touches,confluences=sorted(set(conf)),independent_confluence_count=len(set(conf)),source_ts=c.source_ts,invalidation_level=round(inv,5),invalidation_rule="M15 accepted body beyond OUTER envelope: one >=60% body and >=0.40 ATR, or two closes each >=0.20 ATR. Wick-only does not invalidate.",original_target1=vals[0],original_target2=vals[1],original_target3=vals[2],original_runner=vals[3],flip_target1=fvals[0],flip_target2=fvals[1],flip_target3=fvals[2],flip_runner=fvals[3],clear_run=round(clear,5),countertrend=counter,dxy_support=support,notes=["PRE-ANALYSIS core uses CLOSED D1/H4/H1 evidence only; later M1 execution OB/FVG cannot redefine it.",*notes])

def evaluate_zone_state(z:Zone,m15:list[Bar],atr_m15_value:float=0.0)->ZoneState:
    if z.state==ZoneState.RETIRED or len(m15)<2:return z.state
    a=atr_m15_value or atr(m15)
    if a<=0:return z.state
    boundary=z.zone_high if z.original_direction==Direction.SELL else z.zone_low
    def frac(b:Bar):
        body=max(_body(b),1e-9);top=max(b.open,b.close);bottom=min(b.open,b.close)
        beyond=max(0,top-max(bottom,boundary)) if z.original_direction==Direction.SELL else max(0,min(top,boundary)-bottom)
        return beyond/body
    last=m15[-1]; beyond=last.close>boundary if z.original_direction==Direction.SELL else last.close<boundary
    single=beyond and frac(last)>=SETTINGS.m15_single_accept_body_fraction and _body(last)>=SETTINGS.m15_single_accept_body_atr*a
    x,y=m15[-2],m15[-1]
    two=((x.close>boundary and y.close>boundary) if z.original_direction==Direction.SELL else (x.close<boundary and y.close<boundary)) and _body(x)>=SETTINGS.m15_double_accept_body_atr*a and _body(y)>=SETTINGS.m15_double_accept_body_atr*a
    return ZoneState.FAILED_FLIP_CANDIDATE if single or two else ZoneState.ACTIVE

def build_analysis(s:MarketSnapshot,generated_at:Optional[int]=None)->Analysis:
    now=generated_at or int(datetime.now(timezone.utc).timestamp());liq=liquidity_map(s);bias=_bias(s)
    zones=[_zone(c,s,liq,bias,i+1) for i,c in enumerate(build_candidates(s))]
    zones=[z for z in zones if z.grade!=Grade.REJECT and z.state!=ZoneState.RETIRED]
    best=[]
    for d in (Direction.BUY,Direction.SELL):
        side=[z for z in zones if z.original_direction==d]
        if side:
            side.sort(key=lambda z:(GRADE_RANK[z.grade],TF_RANK.get(z.source_tf,9),-z.location_score,z.touch_count,((z.core_low+z.core_high)/2 if d==Direction.BUY else -(z.core_low+z.core_high)/2)))
            best.append(side[0])
    for z in best:z.state=evaluate_zone_state(z,s.xau_m15,s.atr_m15)
    selected="";exe=[z for z in best if execution_grade_eligible(z)]
    if exe:exe.sort(key=lambda z:(GRADE_RANK[z.grade],-z.location_score));selected=exe[0].zone_id
    above=sorted([x for x in liq if x.side=="ABOVE"],key=lambda x:x.distance);below=sorted([x for x in liq if x.side=="BELOW"],key=lambda x:x.distance)
    primary=(above[0] if bias==Direction.BUY and above else below[0] if bias==Direction.SELL and below else (sorted(liq,key=lambda x:x.distance)[0] if liq else None))
    guards=[]
    if not s.complete():guards.append("NO_COMPLETE_HISTORY_CONTEXT")
    if s.spread_points>SETTINGS.max_spread_points:guards.append(f"SPREAD_HIGH:{s.spread_points:.1f}")
    if now-s.sent_at>SETTINGS.max_snapshot_age_seconds:guards.append("SNAPSHOT_STALE")
    return Analysis(analysis_id=f"A_{now}_{uuid.uuid4().hex[:8]}",generated_at=now,snapshot_at=s.sent_at,overall_bias=bias,primary_liquidity=f"{primary.label}@{primary.price:.5f}" if primary else "",liquidity_map=liq,zones=best,selected_zone_id=selected,trader_brief=f"D1/H4/H1 consensus={bias.value}. DXY={_dxy(s).value} analysis-only. {len(best)} two-branch XAU zone(s).",approved=not any(x in guards for x in ("NO_COMPLETE_HISTORY_CONTEXT","SNAPSHOT_STALE")),execution_policy={"core":"PREEXISTING_CLOSED_D1_H4_H1_ONLY","primary":["HTF_LOCATION","EXTERNAL_SWEEP","M1_MSS_BODY_CLOSE","DISPLACEMENT","NEW_M1_DEALING_RANGE","PREMIUM_DISCOUNT","OTE_618_786","FRESH_PD_ARRAY","RETRACE_ENTRY"],"reentry":["THESIS_VALID","OBJECTIVE_OPEN","CONTINUATION_BOS","NEW_DISPLACEMENT","NEW_M1_DEALING_RANGE","INTERNAL_LIQUIDITY","PREMIUM_DISCOUNT","FRESH_PD_ARRAY"],"flip":["M15_ACCEPTANCE_INVALIDATION","NO_INSTANT_REVERSE","OPPOSITE_SIDE_RETEST","M1_MSS_BOS","DISPLACEMENT","NEW_M1_DEALING_RANGE","PREMIUM_DISCOUNT","OTE","FRESH_PD_ARRAY"],"risk":["ONE_BUDGET_PER_THESIS","NO_AVERAGING_DOWN","NO_SL_WIDENING","STRUCTURE_AWARE_BE","LIQUIDITY_PARTIALS","M5_ATR_RUNNER_TRAIL"]},guards=guards)

def active_plan_text(a:Analysis,snapshot:Optional[MarketSnapshot]=None)->str:
    z=next((z for z in a.zones if z.zone_id==a.selected_zone_id),None);lines={"protocol":str(SETTINGS.protocol_version),"cloud_version":SETTINGS.app_version,"analysis_id":a.analysis_id,"generated_at":str(a.generated_at),"approved":"1" if a.approved else "0","overall_bias":a.overall_bias.value,"primary_liquidity":a.primary_liquidity,"paper_only":"1" if SETTINGS.paper_only else "0"}
    if not z:
        lines.update({"ea_mode":"NO_TRADE","zone_id":"","reason":"NO_EXECUTION_GRADE_ZONE"});return "\n".join(f"{k}={v}" for k,v in lines.items())+"\n"
    state=evaluate_zone_state(z,snapshot.xau_m15,snapshot.atr_m15) if snapshot else z.state
    executable=a.approved and execution_grade_eligible(z)
    if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled:executable=executable and a.ai_approved
    current_grade=z.grade.value
    qualified_mitigations=int(z.touch_count or 0)
    for note in list(z.notes or []):
        text=str(note)
        if text.startswith("current_execution_grade:"):
            current_grade=text.split(":",1)[1]
        elif text.startswith("qualified_mitigations:"):
            try: qualified_mitigations=int(float(text.split(":",1)[1]))
            except (TypeError,ValueError): pass
    lines.update({"ea_mode":"DUAL_BRANCH" if executable else "WATCH_ONLY","zone_id":z.zone_id,"zone_state":state.value,"setup_type":z.setup_type,"source_tf":z.source_tf,"grade":z.grade.value,"current_grade":current_grade,"qualified_mitigations":str(qualified_mitigations),"original_direction":z.original_direction.value,"flip_direction":z.flip_direction.value,"core_method":z.core_method,"core_low":f"{z.core_low:.5f}","core_high":f"{z.core_high:.5f}","zone_low":f"{z.zone_low:.5f}","zone_high":f"{z.zone_high:.5f}","location_score":f"{z.location_score:.4f}","touch_count":str(z.touch_count),"invalidation_level":f"{z.invalidation_level:.5f}","min_displacement_atr":"0.80","min_rr":"1.50","original_target1":f"{z.original_target1:.5f}","original_target2":f"{z.original_target2:.5f}","original_target3":f"{z.original_target3:.5f}","original_runner":f"{z.original_runner:.5f}","flip_target1":f"{z.flip_target1:.5f}","flip_target2":f"{z.flip_target2:.5f}","flip_target3":f"{z.flip_target3:.5f}","flip_runner":f"{z.flip_runner:.5f}","requires_sweep":"1","flip_requires_retest":"1","flip_invalidation_is_not_entry":"1","execution_contract":"V6_PRIMARY_REENTRY_FLIP_THESIS_RISK","risk_model":RISK_MODEL,"risk_epoch":SETTINGS.research_risk_epoch,"validation_initial_capital":f"{SETTINGS.research_validation_initial_capital:.2f}","risk_context":zone_risk_context(z),"grade_risk_pct":f"{original_risk_pct(z):.2f}","original_risk_pct":f"{original_risk_pct(z):.2f}","flip_risk_pct":f"{flip_risk_pct(z):.2f}","bplus_reduced_risk":"0","bplus_execution_authority":"0","dxy_support":z.dxy_support})
    return "\n".join(f"{k}={v}" for k,v in lines.items())+"\n"

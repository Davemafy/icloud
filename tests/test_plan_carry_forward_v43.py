from datetime import datetime, timedelta, timezone
import json
import uuid

from app.config import SETTINGS
from app.db import DB
from app.engine import active_plan_text
from app.models import Bias, Direction, DxyImplication, Grade, InstitutionalAnalysis, Zone
from app.service import load_active_execution_analysis


def _analysis(now, *, ai_used=True, mode=Direction.SELL_ONLY, generated_offset_min=180):
    z=Zone(zone_id=f"Z_{uuid.uuid4().hex[:8]}", instrument="XAUUSD", direction=Direction.SELL_ONLY,
           zone_low=4374.0, zone_high=4379.0, grade=Grade.A, source_tf="D1>H4>H1",
           requires_sweep="BSL", invalidation="M15 acceptance", invalidation_level=4379.0, invalidation_tf="M15")
    return InstitutionalAnalysis(
        analysis_id=str(uuid.uuid4()), generated_at=now-timedelta(minutes=generated_offset_min),
        valid_until=now-timedelta(minutes=60), snapshot_id=str(uuid.uuid4()), session="LONDON",
        current_xau_price=4336, current_dxy_price=99.2, spread_points=16,
        dxy_d1_bias=Bias.BULLISH,dxy_h4_bias=Bias.BULLISH,dxy_h1_bias=Bias.BULLISH,
        xau_d1_bias=Bias.BEARISH,xau_h4_bias=Bias.BEARISH,xau_h1_bias=Bias.BEARISH,xau_m15_context=Bias.BEARISH,
        overall_bias=Bias.BEARISH,dxy_implication=DxyImplication.SUPPORTS,primary_liquidity="SSL",
        zones=[z],ea_mode=mode,approved=True,ai_used=ai_used,source_fingerprint="test"
    )


def test_active_plan_text_disables_fixed_ea_expiry_when_carry_forward_enabled():
    a=_analysis(datetime.now(timezone.utc))
    text=active_plan_text(a,carry_forward=True)
    assert "valid_until_epoch=0" in text
    assert "refresh_due=1" in text
    assert "carry_forward_until_replaced=1" in text
    assert "plan_lifecycle=CARRY_FORWARD" in text
    assert "view_zone_1_id=" in text


def test_latest_execution_analysis_ignores_newer_ai_unavailable_fallback_when_ai_required():
    if not SETTINGS.require_ai_for_execution:
        return
    now=datetime.now(timezone.utc)+timedelta(days=30)
    good=_analysis(now,ai_used=True,generated_offset_min=20)
    failed=_analysis(now,ai_used=False,mode=Direction.NO_TRADE,generated_offset_min=10)
    DB.save_analysis(good.model_dump(mode="json"))
    DB.save_analysis(failed.model_dump(mode="json"))
    active=load_active_execution_analysis()
    assert active is not None
    assert active.analysis_id == good.analysis_id


def test_successful_new_ai_analysis_replaces_carried_plan():
    if not SETTINGS.require_ai_for_execution:
        return
    now=datetime.now(timezone.utc)+timedelta(days=31)
    old=_analysis(now,ai_used=True,generated_offset_min=20)
    new=_analysis(now,ai_used=True,mode=Direction.NO_TRADE,generated_offset_min=5)
    DB.save_analysis(old.model_dump(mode="json"))
    DB.save_analysis(new.model_dump(mode="json"))
    active=load_active_execution_analysis()
    assert active is not None
    assert active.analysis_id == new.analysis_id

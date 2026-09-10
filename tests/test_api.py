import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import make_snapshot


RUN_ID = str(time.time_ns())

def headers(nonce):
    return {"X-API-Key":"change-me","X-Timestamp":str(int(time.time())),"X-Nonce":RUN_ID+"-"+nonce}


def test_authenticated_snapshot_and_plan_fetch():
    with TestClient(app) as c:
        snap=make_snapshot(datetime.now(timezone.utc))
        r=c.post('/market/snapshot',json=snap.model_dump(mode='json'),headers=headers('nonce-snapshot-001'))
        assert r.status_code==200
        # Analysis requires admin key.
        r=c.post('/analysis/run?reason=test',headers={"X-Admin-Key":"change-me-admin"})
        assert r.status_code==200
        r=c.get('/mt5/plan',headers=headers('nonce-plan-001'))
        assert r.status_code==200
        assert 'version=3' in r.text
        assert 'ea_mode=' in r.text


def test_nonce_replay_rejected():
    with TestClient(app) as c:
        h=headers('nonce-replay-unique')
        first=c.get('/mt5/plan',headers=h)
        second=c.get('/mt5/plan',headers=h)
        assert first.status_code==200
        assert second.status_code==409


def test_dashboard_state_contains_live_snapshot_and_scheduler():
    with TestClient(app) as c:
        snap=make_snapshot(datetime.now(timezone.utc))
        r=c.post('/market/snapshot',json=snap.model_dump(mode='json'),headers=headers('nonce-dashboard-live-001'))
        assert r.status_code==200
        r=c.get('/dashboard/state',headers={"X-Admin-Key":"change-me-admin"})
        assert r.status_code==200
        body=r.json()
        assert body.get('snapshot') is not None
        assert body.get('scheduler') is not None
        assert 'sessions' in body['scheduler']


def test_dashboard_session_bootstrap_sets_sse_cookie():
    with TestClient(app) as c:
        r=c.post('/dashboard/session',headers={"X-Admin-Key":"change-me-admin"})
        assert r.status_code==200
        assert r.json().get('transport')=='sse'
        assert 'smc_dashboard_session' in r.cookies


def test_mt5_plan_exports_visual_zone_count():
    from app.engine import active_plan_text, build_candidate_analysis
    snap=make_snapshot(datetime.now(timezone.utc))
    analysis=build_candidate_analysis(snap)
    analysis.approved=True
    text=active_plan_text(analysis)
    assert 'version=3' in text
    assert 'zone_count=' in text
    if analysis.zones:
        assert 'view_zone_1_id=' in text
        assert 'view_zone_1_low=' in text
        assert 'view_zone_1_high=' in text

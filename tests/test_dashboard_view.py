from app.dashboard_view import compact_dashboard_html


def test_execution_contract_panel_is_removed_but_policy_stays_available_read_only():
    html = (
        '<div class="grid" style="margin-top:12px">'
        '<div class="card"><h3>Institutional brief</h3><pre id="brief">Waiting for analysis…</pre></div>'
        '<div class="card"><h3>Execution contract</h3><pre id="policy">Waiting for analysis…</pre></div>'
        '</div>'
        '<h2>Live trading journal <span class="pill">auto-updates every 3s</span></h2>'
        "<script>if(a){$('brief').textContent=a.trader_brief||'—';"
        "$('policy').textContent=JSON.stringify(a.execution_policy||{},null,2);}</script>"
        "</body>"
    )
    cleaned = compact_dashboard_html(html)
    assert "Institutional brief" in cleaned
    assert 'id="brief"' in cleaned
    assert "Execution contract" not in cleaned
    assert 'id="policy"' not in cleaned
    assert "$('policy')" not in cleaned
    assert "window.tradeZoneExecutionPolicy=a.execution_policy||{};" in cleaned


def test_read_only_map_execution_context_is_injected_without_execution_calls():
    html = '<pre id="brief"></pre><tbody id="zones"></tbody><div id="jStatus"></div><div id="jIds"></div><h2>Live trading journal <span class="pill">auto-updates every 3s</span></h2></body>'
    cleaned = compact_dashboard_html(html)
    assert 'id="journalContext"' in cleaned
    assert 'id="ownershipState"' in cleaned
    assert "Map / thesis ownership &amp; M1 authority" in cleaned
    assert "READ ONLY" in cleaned
    assert 'id="journal-context-readonly-script"' in cleaned
    assert "THESIS OWNER • DIRECTION LOCK" in cleaned
    assert "WATCH ONLY • BLOCKED BY ACTIVE THESIS" in cleaned
    assert "No acquired thesis lock and no current M1-authorized zone" in cleaned
    assert "/mt5/plan" not in cleaned
    assert "WebRequest" not in cleaned
    assert "OrderSend" not in cleaned


def test_directional_mitigation_audit_is_visible_and_read_only():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert 'id="mitigationAudit"' in cleaned
    assert "Mitigation audit" in cleaned
    assert "OBSERVATION ONLY" in cleaned
    assert "SELL = below envelope" in cleaned
    assert "BUY = above envelope" in cleaned
    assert "Touch/mitigation count never changes zone grade, risk, ranking or execution eligibility" in cleaned
    assert "MITIGATION HISTORY INCOMPLETE" in cleaned
    assert "zone grade and execution authority are unchanged" in cleaned
    assert "refreshMitigationAudit" in cleaned
    assert "WRONG_APPROACH_SIDE" not in cleaned
    assert "OrderSend" not in cleaned


def test_readiness_is_split_into_htf_quality_and_m1_execution_state():
    html = '<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div><div class="muted">Process checklist — not a prediction.</div></div><div id="checks"></div><h2>Live trading journal</h2></body>'
    cleaned = compact_dashboard_html(html)
    for needle in [
        "HTF setup quality", 'id="htfScore"', "Selected map state", 'id="mapState"',
        "Structural map lifecycle only", "A valid SELL/BUY map is not execution readiness",
        "MAP VALID • NO ENTRY AUTHORITY", "Execution readiness", 'id="executionMeta"',
        "WAITING FOR M1 CONFIRMATION", "M1 HANDOFF ACTIVE",
        "THESIS OWNER ACTIVE • FRESH M1 REQUIRED", "THESIS OWNER • WAITING FOR FRESH M1 LOCATION",
        "M1 PRIMARY SEQUENCE FORMING", "WAITING FOR RETRACE", "Entry permission: NO",
        "Readiness checks ", "SAFETY BLOCKED", "SAFETY HOLD", "Macro authority ",
        "order permission is suspended", "This is not a location failure.",
        "HTF location/source quality only", "Do not chase the existing move",
        "there is no current M1 location handoff or new-entry authority",
        "Macro thesis / handoff authority ", "Fresh M1 entry location ",
        "Cloud execution authority ", "Sequence authority ", "matches the active thesis owner",
        "Model 1: M1 liquidity sweep", "M1 micro structure shift", "causal OB/FVG",
        "bounded retest", "CLOSED M1 directional confirmation",
        "Model 2: recent-zone CLOSED directional engulfing", "no separate M1 micro-structure shift",
        "Model 3: institutional boundary breakout", "displacement", "acceptance", "retest",
        "each sniper family uses its own confirmation contract",
        "ENTRY_CONFIRMATION", "FLIP_CONFIRMATION", "thesis origin/ownership anchor",
        "ownership anchor is not itself a fresh entry signal"
    ]:
        assert needle in cleaned
    assert "M1 HANDOFF READY" not in cleaned
    assert "Checklist " not in cleaned
    assert "/mt5/plan" not in cleaned
    assert "OrderSend" not in cleaned


def test_freshness_check_is_scoped_to_selected_zone():
    html = '<h2>Live trading journal</h2><script>function x(j){const z=j?.zone||{};const labels={fresh_zone:\'Fresh zone (0–1 touch)\'};}</script></body>'
    cleaned = compact_dashboard_html(html)
    assert "z.zone_id+' mitigation telemetry (no grade/risk authority)'" in cleaned
    assert "Selected-zone mitigation telemetry (no grade/risk authority)" in cleaned


def test_dashboard_transform_is_idempotent():
    html = '<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div><div class="muted">Process checklist — not a prediction.</div></div><h2>Live trading journal</h2></body>'
    once = compact_dashboard_html(html); twice = compact_dashboard_html(once)
    for needle in ['id="mitigationAudit"','id="journalContext"','id="ownershipState"','id="journal-context-readonly-script"','id="htfScore"','id="mapState"','id="executionMeta"']:
        assert twice.count(needle) == 1


def test_dashboard_payload_keeps_healthy_sections_when_one_aggregation_fails(monkeypatch):
    import json
    from app import main
    class Analysis:
        def model_dump(self): return {"analysis_id": "A1", "zones": []}
    def broken_journal(): raise RuntimeError("journal aggregation failed")
    monkeypatch.setattr(main, "latest_snapshot", lambda: None); monkeypatch.setattr(main, "active_analysis", lambda: Analysis()); monkeypatch.setattr(main, "_journal_snapshot", broken_journal); monkeypatch.setattr(main, "scheduler_status", lambda: {"running": True}); monkeypatch.setattr(main, "system_status", lambda: {"healthy": True, "cloud_version": "test"})
    payload = json.loads(main._dashboard_payload("tick"))
    assert payload["event"] == "tick" and payload["analysis"]["analysis_id"] == "A1" and payload["system"]["healthy"] is True
    assert payload["journal"] is None and payload["degraded"] is True and payload["errors"]["journal"].startswith("RuntimeError:")


def test_dashboard_client_renders_system_before_optional_sections():
    from pathlib import Path
    html = Path("static/index.html").read_text(encoding="utf-8"); handler = html.split("es.addEventListener('state'", 1)[1]
    assert handler.index("if(d.system)renderSystem(d.system)") < handler.index("const a=d.analysis")
    assert "try{if(d.journal)renderJournal(d.journal)}catch(err){}" in handler


def test_dashboard_recovery_uses_bounded_query_only_observability_path():
    cleaned = compact_dashboard_html("<body></body>")
    for needle in ["/dashboard/read-only-state","AbortController","timeoutMs=1800","getJson('/dashboard/read-only-state',1500)","getJson('/journal/current',1200)","one blocked endpoint cannot leave inFlight stuck forever"]: assert needle in cleaned


def test_dashboard_has_no_self_triggering_zone_mutation_observer():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><div id="checks"></div><h2>Live trading journal</h2></body>')
    assert ".observe(zones,{childList:true,subtree:true})" not in cleaned
    for needle in ["self-triggering mutation loop on mobile browsers","window.setInterval(function(){","refreshJournalContext();","refreshMitigationAudit();"]: assert needle in cleaned


def test_mitigation_audit_falls_back_to_raw_zone_ledger():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    for needle in ["window.tradeZoneAnalysisZones","const raw=analysisZones.find","const z=(mappedId||Object.keys(mapped).length)?mapped:raw","audit.qualified_mitigations??z.qualified_mitigations??z.touch_count??0"]: assert needle in cleaned


def test_recovery_zone_table_matches_current_twelve_column_contract():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "colspan=\"12\"" in cleaned and "publication_execution_status" in cleaned and "raw_core_contact_episodes_before_invalidation" in cleaned


def test_public_zone_map_preserves_noncanonical_audit_identity():
    from app import zone_runtime_policy
    from app.models import Analysis, Direction, Grade, Zone, ZoneState
    z = Zone(zone_id="PZ_H1_BUY_9",original_direction=Direction.BUY,flip_direction=Direction.SELL,setup_type="REVERSAL",source_tf="H1",grade=Grade.B_PLUS,state=ZoneState.ACTIVE,core_low=100.0,core_high=101.0,core_method="WATCH",location_score=5.0,zone_low=99.0,zone_high=102.0,mitigation_audit={"qualified_mitigations": 1, "events": []},invalidation_level=99.0,invalidation_rule="x")
    a = Analysis(analysis_id="A1",generated_at=1,snapshot_at=1,zones=[z],selected_zone_id="",execution_policy={"public_zone_map":{"buy":{"zone_id":"PZ_H1_BUY_9","mitigation_audit":z.mitigation_audit}}})
    class S: point = 0.01
    zone_runtime_policy.apply_pip_display_contract(a, S()); entry = a.execution_policy["public_zone_map"]["buy"]
    assert "zone_id" not in entry and entry["audit_zone_id"] == "PZ_H1_BUY_9" and entry["mitigation_audit"]["qualified_mitigations"] == 1


def test_mitigation_dashboard_accepts_audit_zone_id():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "mapped.audit_zone_id||mapped.zone_id" in cleaned and "const zoneId=mappedId||rawId" in cleaned


def test_dashboard_renders_raw_mitigation_contacts_separately_from_qualified_events():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "const rawContacts=Array.isArray(audit.raw_contacts)?audit.raw_contacts:[]" in cleaned and "RAW CORE CONTACT #" in cleaned and "OBSERVATION ONLY • " in cleaned
    assert "RECONTACT_WITHIN_OPEN_CAMPAIGN" not in cleaned


def test_dashboard_distinguishes_campaign_origin_from_immediate_raw_touch_side():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "Campaign '+auditText(r.campaign_approach_side||r.approach_side||'—')" in cleaned and "Immediate '+auditText(r.immediate_approach_side||'—')" in cleaned and "r.immediate_approach_ts" in cleaned


def test_dashboard_exposes_target_ladder_truth():
    from pathlib import Path
    html = Path("static/index.html").read_text(encoding="utf-8")
    for needle in ["Target lifecycle","Target ladder truth","Activation reference","Target ladder valid for current phase"]: assert needle in html


def test_dashboard_checklist_names_all_execution_grades():
    from pathlib import Path
    html = Path("static/index.html").read_text(encoding="utf-8")
    assert "grade_executable:'A+ / A / B+ execution grade'" in html


def test_dashboard_explains_finalized_cloud_plan_watch_only_hold():
    cleaned = compact_dashboard_html('<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div><div class="muted">Process checklist — not a prediction.</div></div><h2>Live trading journal</h2></body>')
    for needle in [
        "CLOUD PLAN WATCH ONLY",
        "cloud_ea_mode",
        "cloud_separation_guard",
        "cloud_usable_runway",
        "cloud_required_runway",
        "cloud_runway_target",
        "Sequence matches the finalized Cloud plan",
        "Finalized Cloud execution plan is intentionally non-executable",
    ]:
        assert needle in cleaned


def test_dashboard_surfaces_exact_finalized_history_gate_truth():
    cleaned = compact_dashboard_html('<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div><div class="muted">Process checklist — not a prediction.</div></div><h2>Live trading journal</h2></body>')
    for needle in [
        "cloud_history_failures",
        "cloud_history_warnings",
        "cloud_history_metrics",
        "Failed history:",
        "Snapshot depth:",
        "DXY extended-depth warning (non-blocking)",
    ]:
        assert needle in cleaned


def test_validation_ledger_copy_explains_canonical_sample_deduplication():
    cleaned = compact_dashboard_html('<h2>Live trading journal</h2></body>')
    assert "Canonical source/core samples" in cleaned
    assert "Reanalysis of the same institutional source/core remains one research sample" in cleaned
    assert "Reaction after live core contact" in cleaned
    assert "exact-geometry observations collapsed" in cleaned
    assert "other qualified-handoff reaction" in cleaned


def test_main_map_display_separates_sticky_owner_from_current_m1_handoff():
    from types import SimpleNamespace
    from app import main

    zone = SimpleNamespace(
        zone_id="BUY_OWNER",
        original_direction=SimpleNamespace(value="BUY"),
    )
    thesis = {
        "locked": True,
        "owner_zone_id": "BUY_OWNER",
        "fresh_m1_confirmation_required": True,
    }

    assert main._map_display_state(zone, "M1_READY", thesis) == "BUY THESIS OWNER ACTIVE • FRESH M1 REQUIRED"
    assert main._map_display_state(zone, "M1_READY", {"locked": False}) == "BUY MAP CONTACTED • M1 HANDOFF ACTIVE"


def test_static_checklist_separates_macro_authority_from_fresh_m1_location():
    from pathlib import Path
    html = Path("static/index.html").read_text(encoding="utf-8")
    assert "m1_handoff_ready:'Macro thesis / handoff authority active'" in html
    assert "fresh_m1_location_ready:'Fresh M1 entry location active'" in html
    assert "m1_handoff_ready:'M1 location handoff active'" not in html


def test_dashboard_sequence_363_truth_and_reconstruction_telemetry():
    from pathlib import Path
    html = Path("static/index.html").read_text(encoding="utf-8")
    for needle in [
        "Model-specific confirmation:",
        "only Model 1 requires a CLOSED M1 micro-structure shift",
        "Model 2 — Recent-zone engulfing",
        "No separate M1 micro-structure shift is required",
        "Model 3 — Institutional breakout",
        "Direct breakout-candle chasing remains disabled",
        "R1/R2 continuation",
    ]:
        assert needle in html
    assert "every entry family requires a CLOSED M1 micro structure shift" not in html
    cleaned = compact_dashboard_html('<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div><div class="muted">Process checklist — not a prediction.</div></div><h2>Live trading journal</h2></body>')
    for needle in [
        "trace_contact_ts",
        "trace_reconstructed_pre_handoff",
        "campaign_key",
        "Zone contact @ ",
        "reconstructed pre-handoff",
        "BREAKOUT SEQUENCE FORMING",
        "CONTINUATION RE-ENTRY FORMING",
        "Model 2 engulfing remains a parallel independent trigger",
        "No separate Model-1 micro-structure shift is required",
        "CONTINUATION_POST_RETEST_M1_SHIFT",
    ]:
        assert needle in cleaned
    assert "BREAKOUT_M1_MICRO_SHIFT" not in cleaned
    assert "Sequence 3.61 checks" not in cleaned

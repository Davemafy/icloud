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
    html = (
        '<pre id="brief"></pre>'
        '<tbody id="zones"></tbody>'
        '<div id="jStatus"></div><div id="jIds"></div>'
        '<h2>Live trading journal <span class="pill">auto-updates every 3s</span></h2>'
        '</body>'
    )

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
    # The dashboard recovery layer may use read-only REST fetches, but the
    # ownership panel itself must never call the executable MT5 plan/order path.
    assert "/mt5/plan" not in cleaned
    assert "WebRequest" not in cleaned
    assert "OrderSend" not in cleaned


def test_directional_mitigation_audit_is_visible_and_read_only():
    html = (
        '<tbody id="zones"></tbody>'
        '<h2>Live trading journal</h2>'
        '</body>'
    )

    cleaned = compact_dashboard_html(html)

    assert 'id="mitigationAudit"' in cleaned
    assert "Mitigation audit" in cleaned
    assert "GRADE AUTHORITY" in cleaned
    assert "SELL = below envelope" in cleaned
    assert "BUY = above envelope" in cleaned
    assert "Wrong-side contact never downgrades a zone" in cleaned
    assert "FRESHNESS HISTORY INCOMPLETE" in cleaned
    assert "New A/A+ execution authority is blocked" in cleaned
    assert "refreshMitigationAudit" in cleaned
    assert "WRONG_APPROACH_SIDE" not in cleaned  # reason is runtime data, not fabricated UI text
    assert "OrderSend" not in cleaned


def test_readiness_is_split_into_htf_quality_and_m1_execution_state():
    html = (
        '<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div>'
        '<div class="muted">Process checklist — not a prediction.</div></div>'
        '<div id="checks"></div>'
        '<h2>Live trading journal</h2>'
        '</body>'
    )

    cleaned = compact_dashboard_html(html)

    assert "HTF setup quality" in cleaned
    assert 'id="htfScore"' in cleaned
    assert "Execution readiness" in cleaned
    assert 'id="executionMeta"' in cleaned
    assert "WAITING FOR M1 CONFIRMATION" in cleaned
    assert "M1 HANDOFF ACTIVE" in cleaned
    assert "M1 HANDOFF READY" not in cleaned
    assert "WAITING FOR VALUE / RETRACE" in cleaned
    assert "Entry permission: NO" in cleaned
    assert "Macro checks " in cleaned
    assert "Checklist " not in cleaned
    assert "SAFETY BLOCKED" in cleaned
    assert "SAFETY HOLD" in cleaned
    assert "This is not a location failure." in cleaned
    assert "HTF location/source quality only" in cleaned
    assert "Do not chase the existing move" in cleaned
    assert "there is no current M1 location handoff or new-entry authority" in cleaned
    assert "Current M1 location handoff " in cleaned
    assert "Cloud execution authority " in cleaned
    assert "Sequence authority " in cleaned
    assert "matches the active thesis owner" in cleaned
    assert "This is not entry authorization" in cleaned
    assert "live Sequence EA must still complete sweep" in cleaned
    assert "CLOSED M1 same-direction rejection/micro-break" in cleaned
    assert "Every entry model must pass this final confirmation" in cleaned
    assert "ENTRY_CONFIRMATION" in cleaned
    assert "FLIP_CONFIRMATION" in cleaned
    assert "thesis origin/ownership anchor" in cleaned
    assert "/mt5/plan" not in cleaned
    assert "OrderSend" not in cleaned


def test_freshness_check_is_scoped_to_selected_zone():
    html = (
        '<h2>Live trading journal</h2>'
        "<script>function x(j){const z=j?.zone||{};const labels={fresh_zone:'Fresh zone (0–1 touch)'};}</script>"
        '</body>'
    )
    cleaned = compact_dashboard_html(html)
    assert "z.zone_id+' touch eligibility (A+ ≤1 • A ≤2 • B+ watch-only)'" in cleaned
    assert "Selected-zone touch eligibility (A+ ≤1 • A ≤2 • B+ watch-only)" in cleaned


def test_dashboard_transform_is_idempotent():
    html = (
        '<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div>'
        '<div class="muted">Process checklist — not a prediction.</div></div>'
        '<h2>Live trading journal</h2></body>'
    )
    once = compact_dashboard_html(html)
    twice = compact_dashboard_html(once)

    assert twice.count('id="mitigationAudit"') == 1
    assert twice.count('id="journalContext"') == 1
    assert twice.count('id="ownershipState"') == 1
    assert twice.count('id="journal-context-readonly-script"') == 1
    assert twice.count('id="htfScore"') == 1
    assert twice.count('id="executionMeta"') == 1


def test_dashboard_payload_keeps_healthy_sections_when_one_aggregation_fails(monkeypatch):
    import json
    from app import main

    class Analysis:
        def model_dump(self):
            return {"analysis_id": "A1", "zones": []}

    def broken_journal():
        raise RuntimeError("journal aggregation failed")

    monkeypatch.setattr(main, "latest_snapshot", lambda: None)
    monkeypatch.setattr(main, "active_analysis", lambda: Analysis())
    monkeypatch.setattr(main, "_journal_snapshot", broken_journal)
    monkeypatch.setattr(main, "scheduler_status", lambda: {"running": True})
    monkeypatch.setattr(main, "system_status", lambda: {"healthy": True, "cloud_version": "test"})

    payload = json.loads(main._dashboard_payload("tick"))

    assert payload["event"] == "tick"
    assert payload["analysis"]["analysis_id"] == "A1"
    assert payload["system"]["healthy"] is True
    assert payload["journal"] is None
    assert payload["degraded"] is True
    assert payload["errors"]["journal"].startswith("RuntimeError:")


def test_dashboard_client_renders_system_before_optional_sections():
    from pathlib import Path

    html = Path("static/index.html").read_text(encoding="utf-8")
    handler = html.split("es.addEventListener('state'", 1)[1]
    assert handler.index("if(d.system)renderSystem(d.system)") < handler.index("const a=d.analysis")
    assert "try{if(d.journal)renderJournal(d.journal)}catch(err){}" in handler


def test_dashboard_recovery_uses_bounded_query_only_observability_path():
    cleaned = compact_dashboard_html("<body></body>")

    assert "/dashboard/read-only-state" in cleaned
    assert "AbortController" in cleaned
    assert "timeoutMs=1800" in cleaned
    assert "getJson('/dashboard/read-only-state',1500)" in cleaned
    assert "getJson('/journal/current',1200)" in cleaned
    assert "one blocked endpoint cannot leave inFlight stuck forever" in cleaned


def test_read_only_dashboard_payload_bypasses_heavy_aggregators(monkeypatch):
    import json
    import sqlite3
    import time
    from app import main

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
        CREATE TABLE analyses(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
        CREATE TABLE heartbeat(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            ea TEXT,
            version TEXT,
            symbol TEXT,
            payload TEXT
        );
        """
    )
    now = int(time.time())
    conn.execute(
        "INSERT INTO snapshots(payload) VALUES(?)",
        (json.dumps({"sent_at": now, "spread_points": 16}),),
    )
    conn.execute(
        "INSERT INTO analyses(payload) VALUES(?)",
        (json.dumps({"analysis_id": "A1", "zones": [], "execution_policy": {}}),),
    )
    conn.execute(
        "INSERT INTO heartbeat(ts,ea,version,symbol,payload) VALUES(?,?,?,?,?)",
        (
            now,
            "InstitutionalSMC_DataBridge",
            "1.48",
            "XAUUSD",
            json.dumps({"details": {"installed_bridge_version": "1.48"}}),
        ),
    )
    conn.execute(
        "INSERT INTO heartbeat(ts,ea,version,symbol,payload) VALUES(?,?,?,?,?)",
        (
            now,
            "InstitutionalSMC_SequenceEA",
            "3.39",
            "XAUUSD",
            json.dumps({"details": {"installed_sequence_version": "3.39", "restart_safe": True}}),
        ),
    )
    conn.commit()

    monkeypatch.setattr(main, "_dashboard_ro_connect", lambda: conn)
    payload = main._dashboard_read_only_payload()

    assert payload["ok"] is True
    assert payload["analysis"]["analysis_id"] == "A1"
    assert payload["snapshot"]["spread_points"] == 16
    assert payload["source"] == "SQLITE_QUERY_ONLY_SHORT_TIMEOUT"
    assert payload["system"]["components"]["components"]["data_bridge"]["running"] == "1.48"
    assert payload["system"]["components"]["components"]["sequence_ea"]["running"] == "3.39"


def test_dashboard_has_no_self_triggering_zone_mutation_observer():
    html = (
        '<tbody id="zones"></tbody>'
        '<div id="checks"></div>'
        '<h2>Live trading journal</h2>'
        '</body>'
    )
    cleaned = compact_dashboard_html(html)

    assert ".observe(zones,{childList:true,subtree:true})" not in cleaned
    assert "self-triggering mutation loop on mobile browsers" in cleaned
    assert "window.setInterval(function(){" in cleaned
    assert "refreshJournalContext();" in cleaned
    assert "refreshMitigationAudit();" in cleaned


def test_mitigation_audit_falls_back_to_raw_zone_ledger():
    html = (
        '<tbody id="zones"></tbody>'
        '<h2>Live trading journal</h2>'
        '</body>'
    )
    cleaned = compact_dashboard_html(html)

    assert "window.tradeZoneAnalysisZones" in cleaned
    assert "const raw=analysisZones.find" in cleaned
    assert "const z=(mappedId||Object.keys(mapped).length)?mapped:raw" in cleaned
    assert "audit.qualified_mitigations??z.qualified_mitigations??z.touch_count??0" in cleaned


def test_recovery_zone_table_matches_current_twelve_column_contract():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "colspan=\"12\"" in cleaned
    assert "publication_execution_status" in cleaned
    assert "raw_core_contact_episodes_before_invalidation" in cleaned


def test_public_zone_map_preserves_noncanonical_audit_identity():
    from app import zone_runtime_policy
    from app.models import Analysis, Direction, Grade, Zone, ZoneState

    z = Zone(
        zone_id="PZ_H1_BUY_9",
        original_direction=Direction.BUY,
        flip_direction=Direction.SELL,
        setup_type="REVERSAL",
        source_tf="H1",
        grade=Grade.B_PLUS,
        state=ZoneState.ACTIVE,
        core_low=100.0,
        core_high=101.0,
        core_method="WATCH",
        location_score=5.0,
        zone_low=99.0,
        zone_high=102.0,
        mitigation_audit={"qualified_mitigations": 1, "events": []},
        invalidation_level=99.0,
        invalidation_rule="x",
    )
    a = Analysis(
        analysis_id="A1",
        generated_at=1,
        snapshot_at=1,
        zones=[z],
        selected_zone_id="",
        execution_policy={"public_zone_map":{"buy":{"zone_id":"PZ_H1_BUY_9","mitigation_audit":z.mitigation_audit}}},
    )

    class S:
        point = 0.01

    zone_runtime_policy.apply_pip_display_contract(a, S())
    entry = a.execution_policy["public_zone_map"]["buy"]
    assert "zone_id" not in entry
    assert entry["audit_zone_id"] == "PZ_H1_BUY_9"
    assert entry["mitigation_audit"]["qualified_mitigations"] == 1


def test_mitigation_dashboard_accepts_audit_zone_id():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "mapped.audit_zone_id||mapped.zone_id" in cleaned
    assert "const zoneId=mappedId||rawId" in cleaned


def test_dashboard_renders_raw_mitigation_contacts_separately_from_qualified_events():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "const rawContacts=Array.isArray(audit.raw_contacts)?audit.raw_contacts:[]" in cleaned
    assert "RAW CORE CONTACT #" in cleaned
    assert "OBSERVATION ONLY • " in cleaned
    assert "RECONTACT_WITHIN_OPEN_CAMPAIGN" not in cleaned  # runtime value, not hard-coded classification logic


def test_dashboard_distinguishes_campaign_origin_from_immediate_raw_touch_side():
    cleaned = compact_dashboard_html('<tbody id="zones"></tbody><h2>Live trading journal</h2></body>')
    assert "Campaign '+auditText(r.campaign_approach_side||r.approach_side||'—')" in cleaned
    assert "Immediate '+auditText(r.immediate_approach_side||'—')" in cleaned
    assert "r.immediate_approach_ts" in cleaned

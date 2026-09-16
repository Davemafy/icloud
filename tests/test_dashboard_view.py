from app.dashboard_view import compact_dashboard_html


def test_execution_contract_panel_is_removed_but_brief_stays():
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
    assert "Map / execution ownership" in cleaned
    assert "READ ONLY" in cleaned
    assert 'id="journal-context-readonly-script"' in cleaned
    assert "No M1-authorized zone is selected" in cleaned
    assert "/mt5/plan" not in cleaned
    assert "fetch(" not in cleaned
    assert "WebRequest" not in cleaned
    assert "OrderSend" not in cleaned


def test_dashboard_transform_is_idempotent():
    html = '<h2>Live trading journal</h2></body>'
    once = compact_dashboard_html(html)
    twice = compact_dashboard_html(once)

    assert twice.count('id="journalContext"') == 1
    assert twice.count('id="journal-context-readonly-script"') == 1

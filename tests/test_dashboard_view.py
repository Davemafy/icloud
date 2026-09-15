from app.dashboard_view import compact_dashboard_html


def test_execution_contract_panel_is_removed_but_brief_stays():
    html = (
        '<div class="grid" style="margin-top:12px">'
        '<div class="card"><h3>Institutional brief</h3><pre id="brief">Waiting for analysis…</pre></div>'
        '<div class="card"><h3>Execution contract</h3><pre id="policy">Waiting for analysis…</pre></div>'
        '</div>'
        "<script>if(a){$('brief').textContent=a.trader_brief||'—';"
        "$('policy').textContent=JSON.stringify(a.execution_policy||{},null,2);}</script>"
    )

    cleaned = compact_dashboard_html(html)

    assert "Institutional brief" in cleaned
    assert 'id="brief"' in cleaned
    assert "Execution contract" not in cleaned
    assert 'id="policy"' not in cleaned
    assert "$('policy')" not in cleaned

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mt5" / "stable" / "InstitutionalSMC_DataBridge_v1_49_PublicationFlipTruth.mq5"
RENDERER = ROOT / "mt5" / "stable" / "TradeZone_ZoneRenderer_v1_0.mqh"


def test_v149_tracks_sequence_340_and_publication_render_contract():
    text = SOURCE.read_text(encoding="utf-8")
    renderer = RENDERER.read_text(encoding="utf-8")

    assert '#property version "1.49"' in text
    assert '#define TZ_BRIDGE_VERSION "1.49"' in text
    assert '#define TZ_SEQUENCE_EXPECTED "3.40"' in text
    assert '#define TZ_ZONE_RENDER_CONTRACT "V660"' in text
    assert "TZ_SendHeartbeatV149" in text

    assert "datetime published_at;" in renderer
    assert 'p+"published_at"' in renderer
    assert "datetime left=z.published_at;" in renderer
    assert "Source time is" in renderer
    assert "publication time is when the trader/system could first know" in renderer

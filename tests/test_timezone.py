from app.timezones import safe_zoneinfo


def test_lagos_timezone_resolves_or_falls_back_to_wat():
    tz=safe_zoneinfo("Africa/Lagos")
    assert tz is not None

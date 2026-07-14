from market_lab.web_evidence import classify_url_safety, canonicalize_url_for_dedupe


def test_fetch_url_security_blocks_localhost_without_dns() -> None:
    ok, _, reason = classify_url_safety("http://127.0.0.1/admin", enforce_dns=False)

    assert not ok
    assert "private" in reason or "loopback" in reason


def test_canonicalize_url_drops_tracking_parameters() -> None:
    url = canonicalize_url_for_dedupe("https://Example.COM/path?b=2&utm_source=x&a=1#frag")

    assert url == "https://example.com/path?a=1&b=2"

from app.services.log_redact import scrub


def test_scrub_headers_and_bearer():
    s = ("Headers: {'X-PrivateKey': 'abc123', 'X-ClientPublicIP': '1.2.3.4', "
         "'Authorization': 'Bearer eyJhbGciOi.payload.sig'}")
    out = scrub(s)
    assert "abc123" not in out
    assert "1.2.3.4" not in out
    assert "eyJhbGciOi" not in out


def test_scrub_leaves_normal_text():
    assert scrub("Scanner pass complete: 7 combinations") == "Scanner pass complete: 7 combinations"

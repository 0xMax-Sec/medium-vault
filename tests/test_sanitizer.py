import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from medium_archiver import MAX_ASSET_BYTES, PathSanitizer, fix_mojibake


def test_max_asset_bytes_dos_cap_is_pinned():
    # Drift guard: the DoS cap is documented as 25 MB in CLAUDE.md/DOCUMENTATION.md.
    # If this value changes, those docs must change with it.
    assert MAX_ASSET_BYTES == 25 * 1024 * 1024


def test_slugify_basic():
    text = "Hello World - Bug Bounty 101!"
    slug = PathSanitizer.slugify(text)
    assert slug == "hello-world-bug-bounty-101"


def test_slugify_accents_and_special_chars():
    text = "¿Cómo encontrar vulnerabilidades en APIs REST & GraphQL?"
    slug = PathSanitizer.slugify(text)
    assert "como" in slug
    assert "vulnerabilidades" in slug
    assert "¿" not in slug
    assert "?" not in slug
    assert "&" not in slug


def test_slugify_max_length():
    long_text = "a" * 300
    slug = PathSanitizer.slugify(long_text, max_len=50)
    assert len(slug) <= 50


def test_sanitize_filename():
    unsafe_name = "My:Report/On*SSRF?<Test>|File.md"
    safe_name = PathSanitizer.sanitize_filename(unsafe_name)
    for forbidden in [":", "/", "*", "?", "<", ">", "|"]:
        assert forbidden not in safe_name


def test_fix_mojibake():
    # Common UTF-8 double encoding artifact
    mojibake_text = "GuÃ­a bÃ¡sica de seguridad"
    fixed, changed = fix_mojibake(mojibake_text)
    assert changed > 0
    assert "Guía básica de seguridad" in fixed

    # Plain text should not trigger change
    plain_text = "Guía correcta de seguridad"
    fixed_plain, changed_plain = fix_mojibake(plain_text)
    assert fixed_plain == plain_text
    assert changed_plain == 0


def test_is_safe_url():
    from medium_archiver import is_safe_url

    # Valid external URLs
    ok, _ = is_safe_url("https://medium.com/@user/writeup-123")
    assert ok is True

    # Blocked loopback & metadata
    ok, reason = is_safe_url("http://127.0.0.1:8080/")
    assert ok is False
    assert "bloqueado" in reason.lower() or "reservada" in reason.lower()

    ok, _ = is_safe_url("http://localhost:3000/")
    assert ok is False

    ok, _ = is_safe_url("http://169.254.169.254/latest/meta-data/")
    assert ok is False

    ok, _ = is_safe_url("http://0.0.0.0/")
    assert ok is False

    # Blocked private networks
    ok, _ = is_safe_url("http://10.0.0.5/api")
    assert ok is False
    ok, _ = is_safe_url("http://172.16.0.1/")
    assert ok is False
    ok, _ = is_safe_url("http://192.168.0.1/")
    assert ok is False

    # Blocked schemes
    ok, reason = is_safe_url("file:///etc/passwd")
    assert ok is False
    assert "esquema" in reason.lower()


def test_path_sanitizer_traversal():
    assert PathSanitizer.sanitize("../../evil/path") == "evilpath"
    assert PathSanitizer.sanitize("..\\..\\windows\\escape") == "windowsescape"


class _StubResponse:
    def __init__(self, is_redirect=False, headers=None, status_code=200):
        self.is_redirect = is_redirect
        self.headers = headers or {}
        self.status_code = status_code
        self.closed = False

    def close(self):
        self.closed = True


class _StubSession:
    """Records every URL requested via .get() (no real network)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requested_urls = []

    def get(self, url, **kwargs):
        self.requested_urls.append(url)
        return self.responses.pop(0)


def test_safe_get_blocks_redirect_to_internal_ip():
    from medium_archiver import UnsafeURLError, safe_get

    import pytest

    session = _StubSession([
        _StubResponse(is_redirect=True, headers={"Location": "http://169.254.169.254/"}, status_code=302),
    ])

    with pytest.raises(UnsafeURLError):
        safe_get(session, "https://medium.com/@user/article", timeout=5)

    # The internal URL must never have been fetched.
    assert "http://169.254.169.254/" not in session.requested_urls


def test_safe_get_follows_safe_redirect():
    from medium_archiver import safe_get

    session = _StubSession([
        _StubResponse(is_redirect=True, headers={"Location": "https://medium.com/@other/article"}, status_code=302),
        _StubResponse(is_redirect=False, headers={}, status_code=200),
    ])

    resp = safe_get(session, "https://medium.com/@user/article", timeout=5)

    assert resp.status_code == 200
    assert session.requested_urls == [
        "https://medium.com/@user/article",
        "https://medium.com/@other/article",
    ]


def test_safe_get_blocks_unsafe_initial_url():
    from medium_archiver import UnsafeURLError, safe_get

    import pytest

    session = _StubSession([])

    with pytest.raises(UnsafeURLError):
        safe_get(session, "http://169.254.169.254/latest/meta-data/", timeout=5)

    assert session.requested_urls == []

import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from medium_archiver import PathSanitizer, fix_mojibake


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

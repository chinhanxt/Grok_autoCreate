import re
from pathlib import Path

from config import generate_random_name
from web.server import SignupRequest


def _assert_shuffled_name(first_name, last_name, base):
    assert len(first_name) == len(base) + 4, first_name
    shuffled, suffix = first_name[:-4], first_name[-4:]
    assert sorted(shuffled) == sorted(base), f"{shuffled} is not a shuffle of {base}"
    match = re.match(r"^(\d{2})([A-Z]{2})$", suffix)
    assert match is not None, f"Suffix {suffix} is not 2 digits + 2 letters"
    assert last_name == match.group(2)


def test_generate_random_name_formula():
    for _ in range(50):
        first_name, last_name = generate_random_name()
        _assert_shuffled_name(first_name, last_name, "User_")


def test_generate_random_name_shuffles_base_and_appends_random_suffix():
    base = "TAIKHOAN"
    prefixes = []
    suffixes = []
    for _ in range(40):
        first_name, last_name = generate_random_name(prefix=base)
        _assert_shuffled_name(first_name, last_name, base)
        prefixes.append(first_name[:-4])
        suffixes.append(first_name[-4:])
    assert len(set(prefixes)) > 1
    assert any(p != base for p in prefixes)
    assert len(set(suffixes)) > 1


def test_generate_random_name_custom_prefix():
    first_name, last_name = generate_random_name(prefix="Grok_")
    _assert_shuffled_name(first_name, last_name, "Grok_")


def test_signup_request_accepts_name_prefix():
    req = SignupRequest(name_prefix="Acc_")
    assert req.name_prefix == "Acc_"
    assert SignupRequest().name_prefix == "User_"


def test_index_has_editable_random_name_prefix():
    html = Path("/home/chinhan/xai-grok-account-creator/web/static/index.html").read_text(encoding="utf-8")
    assert 'id="namePrefix"' in html
    assert 'id="namePreview"' in html
    assert 'id="randomNameRow"' in html

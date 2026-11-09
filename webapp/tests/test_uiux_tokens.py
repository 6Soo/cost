import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS_DIR = ROOT / "webapp" / "static" / "css"
TOKENS = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")

FONT_TOKENS = {
    "--t-caption",
    "--t-meta",
    "--t-body-sm",
    "--t-body",
    "--t-h3",
    "--t-h1",
    "--t-kpi",
}
FONT_VALUE_RE = re.compile(r"font-size\s*:\s*([^;\n}]+)")
BORDER_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;\n}]+)")
HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
CSS_CONTEXT_RE = re.compile(
    r"(?:color|background(?:-color)?|border(?:-[a-z]+)?|fill|stroke|outline|box-shadow)"
    r"\s*:\s*[^;\n{}]*#[0-9A-Fa-f]{3,8}\b"
)


def _legacy_nav_lines(path: Path, source: str) -> str:
    """Mask the ledger's explicitly protected legacy navigation blocks.

    PR-2 owns the content styles. Navigation blocks are deliberately held for
    the shell PR, so their old declarations must not make this PR's token
    checks report a false failure.
    """

    if path.name != "ledger_design.css":
        return source
    protected_ranges = ((111, 114), (241, 294), (573, 580), (588, 640), (924, 927))
    markers = (".nav", "#nav", ".nv", ".site-", ".brand", ".prev-q", ".arch-")
    lines = source.splitlines(keepends=True)
    masked: list[str] = []
    for number, line in enumerate(lines, 1):
        in_range = any(start <= number <= end for start, end in protected_ranges)
        if in_range or any(marker in line for marker in markers):
            masked.append("\n")
        else:
            masked.append(line)
    return "".join(masked)


def _css_files_without_tokens() -> list[Path]:
    return sorted(path for path in CSS_DIR.glob("*.css") if path.name != "tokens.css")


def _python_files() -> list[Path]:
    return sorted((ROOT / "webapp").glob("*.py"))


def _font_value_is_token(value: str) -> bool:
    value = value.strip()
    if value == "inherit":
        return True
    match = re.fullmatch(r"var\((--t-[\w-]+)\)", value)
    return bool(match and match.group(1) in FONT_TOKENS)


def _radius_value_is_tokenized(value: str) -> bool:
    value = value.strip()
    # Composite radii (for example a drawer's two rounded corners) are valid
    # when every component is one of the three radius tokens or an allowed
    # geometric value.
    parts = re.findall(r"var\(--r-(?:sm|md|lg|pill)\)|999px|50%|0", value)
    return "".join(parts) == re.sub(r"\s+", "", value)


def _block(source: str, marker: str) -> str:
    start = source.index(marker) + len(marker)
    depth = 0
    opened = False
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
            opened = True
        elif char == "}":
            depth -= 1
            if opened and depth == 0:
                return source[start:index]
    raise AssertionError(f"unclosed CSS block: {marker}")


def _decls(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+)", block))


def test_dark_role_tokens_match_manual_and_system_blocks():
    manual = _decls(_block(TOKENS, ":root[data-theme=dark]"))
    media = _decls(_block(TOKENS, ":root:not([data-theme=light])"))
    names = {name for name in manual if name.startswith("--c-")}
    assert names
    assert {name: manual[name] for name in names} == {name: media[name] for name in names}


def test_all_static_css_var_references_have_a_definition():
    source = "\n".join(path.read_text(encoding="utf-8") for path in CSS_DIR.glob("*.css"))
    refs = set(re.findall(r"var\(\s*(--[\w-]+)", source))
    definitions = set(re.findall(r"(--[\w-]+)\s*:", source))
    assert refs <= definitions


def test_uxa09_css_has_no_hex_literals_outside_tokens():
    failures: list[str] = []
    for path in _css_files_without_tokens():
        source = _legacy_nav_lines(path, path.read_text(encoding="utf-8"))
        for number, line in enumerate(source.splitlines(), 1):
            if HEX_RE.search(line):
                failures.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not failures, "UXA-09 CSS hex literals remain:\n" + "\n".join(failures)


def test_uxa09_python_css_context_has_no_hex_literals():
    failures: list[str] = []
    for path in _python_files():
        if path.name == "social_preview.py":
            continue
        source = path.read_text(encoding="utf-8")
        for match in CSS_CONTEXT_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            failures.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0).strip()}")
    assert not failures, "UXA-09 Python CSS hex literals remain:\n" + "\n".join(failures)


def test_uxa11_css_font_sizes_use_the_seven_type_tokens():
    failures: list[str] = []
    for path in _css_files_without_tokens():
        source = _legacy_nav_lines(path, path.read_text(encoding="utf-8"))
        for match in FONT_VALUE_RE.finditer(source):
            if not _font_value_is_token(match.group(1)):
                line = source.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {match.group(1).strip()}")
    assert not failures, "UXA-11 CSS font-size values remain:\n" + "\n".join(failures)


def test_uxa11_python_font_sizes_use_the_seven_type_tokens():
    failures: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for match in FONT_VALUE_RE.finditer(source):
            if not _font_value_is_token(match.group(1)):
                line = source.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {match.group(1).strip()}")
    assert not failures, "UXA-11 Python font-size values remain:\n" + "\n".join(failures)


def test_uxa12_css_border_radii_use_the_three_radius_tokens():
    failures: list[str] = []
    for path in _css_files_without_tokens():
        source = _legacy_nav_lines(path, path.read_text(encoding="utf-8"))
        for match in BORDER_RADIUS_RE.finditer(source):
            if not _radius_value_is_tokenized(match.group(1)):
                line = source.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {match.group(1).strip()}")
    assert not failures, "UXA-12 CSS border-radius values remain:\n" + "\n".join(failures)


def test_uxa12_python_border_radii_use_the_three_radius_tokens():
    failures: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for match in BORDER_RADIUS_RE.finditer(source):
            if not _radius_value_is_tokenized(match.group(1)):
                line = source.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {match.group(1).strip()}")
    assert not failures, "UXA-12 Python border-radius values remain:\n" + "\n".join(failures)

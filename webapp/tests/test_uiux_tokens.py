import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS_DIR = ROOT / "webapp" / "static" / "css"
TOKENS = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")


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

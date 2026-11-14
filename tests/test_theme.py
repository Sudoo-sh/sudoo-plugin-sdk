from __future__ import annotations

import re
from pathlib import Path

import pytest

from sudoo_plugin_sdk.theme import (
    FIXED_TOKENS,
    PANEL_TOKENS,
    THEMEABLE_TOKENS,
    check_email_accent,
    check_logo_svg,
    check_tokens_css,
    contrast,
    parse_colour,
)

PANEL_TOKENS_FILE = (
    Path(__file__).resolve().parents[2] / "odoo-instance-manager" / "web" / "src" / "styles" / "_tokens.scss"
)

DARK = """
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{ {dark} }}
}}
:root[data-theme="dark"] {{ {dark} }}
"""


def css(light: str = "--accent: #2f5d8a;", dark: str = "--accent: #8fb4dc; --on-accent: #0e1a26;") -> str:
    return f":root {{ {light} }}\n" + DARK.format(dark=dark)


def test_a_valid_theme() -> None:
    report = check_tokens_css(css())
    assert report.errors == []
    assert report.light == {"--accent": "#2f5d8a"}
    assert report.dark["--accent"] == "#8fb4dc"


def test_extra_media_and_comments_are_allowed() -> None:
    text = css() + "/* stronger lines */ @media (prefers-contrast: more) { :root { --hairline: rgb(0 0 0 / 0.4); } }"
    assert check_tokens_css(text).errors == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (css(light="--brand: red;"), "not one of the panel's tokens"),
        (css(light="--s4: 20px;"), "may not change"),
        (css(light="--ease: linear;"), "may not change"),
        (css(light="color: red;"), "only custom properties"),
        (css(light="--accent: url(https://evil.example/x.png);"), "not allowed"),
        (css(light="--font: expression(alert(1));"), "not allowed"),
        (css(light="--accent: var(--mine);"), "not a panel token"),
        ('@import "x.css";\n' + css(), "Unexpected text"),
        (":root { --accent: #2f5d8a; }", "dark values twice"),
        (':root { --accent: #2f5d8a; }\n:root[data-theme="dark"] { --accent: #8fb4dc; }', "dark values twice"),
        (
            ':root { --accent: #2f5d8a; }\n@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) '
            '{ --accent: #8fb4dc; } }\n:root[data-theme="dark"] { --accent: #111111; }',
            "same values",
        ),
        (css() + "body { --accent: red; }", "is not allowed"),
        (css() + "@font-face { font-family: x; }", "not allowed"),
        (css() + "@media print { :root { --accent: red; } }", "not allowed"),
        (css(light="--text: #cccccc;"), "contrast"),
        (css(dark="--accent: #8fb4dc; --on-accent: #ffffff;"), "contrast"),
        (":root { --accent: #fff; ", "not balanced"),
        (css(light="--accent: #2f5d8a; } :root { --text: red;"), "appears twice"),
        ("<style>" + css(), "may not contain"),
    ],
)
def test_bad_tokens_are_refused(text: str, message: str) -> None:
    report = check_tokens_css(text)
    assert report.errors, text
    assert any(message in error for error in report.errors), report.errors


def test_weak_secondary_text_is_a_warning() -> None:
    report = check_tokens_css(css(light="--text-3: #b0b0b0;"))
    assert report.errors == []
    assert any("--text-3" in w for w in report.warnings)


def test_colours_and_contrast() -> None:
    assert parse_colour("#fff") == (1.0, 1.0, 1.0)
    assert parse_colour("rgb(0 0 0 / 0.5)") == (0.0, 0.0, 0.0)
    assert parse_colour("var(--accent)") is None
    assert contrast((0, 0, 0), (1, 1, 1)) == pytest.approx(21.0)


def test_token_groups() -> None:
    assert not THEMEABLE_TOKENS & FIXED_TOKENS
    assert {"--accent", "--bg", "--font", "--radius-card", "--material"} <= THEMEABLE_TOKENS


@pytest.mark.skipif(not PANEL_TOKENS_FILE.is_file(), reason="no checkout of the panel next to this one")
def test_token_list_matches_the_panel() -> None:
    names = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", PANEL_TOKENS_FILE.read_text(), flags=re.MULTILINE))
    assert names == set(PANEL_TOKENS)


GOOD_LOGO = (
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
    b'<defs><linearGradient id="g"/><path id="p" d="M0 0h1"/></defs>'
    b'<rect width="10" height="10" fill="url(#g)"/><use href="#p"/><use xlink:href="#p"/></svg>'
)


def test_a_safe_logo() -> None:
    assert check_logo_svg(GOOD_LOGO) == []


@pytest.mark.parametrize(
    ("svg", "message"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script>alert(1)</script></svg>', "<script>"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" onload="x()"/>', "onload"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><use href="https://e.x/a.svg#i"/></svg>',
            "outside",
        ),
        (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="#x"/></svg>', "<image>"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><foreignObject/></svg>', "<foreignobject>"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><a href="#x"/></svg>', "<a>"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect fill="url(http://e.x/p)"/></svg>',
            "outside",
        ),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>@import url(x.css);</style></svg>',
            "<style>",
        ),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><set attributeName="href" to="#a"/></svg>',
            "<set>",
        ),
        (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x "y">]><svg/>', "DOCTYPE"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "viewBox"),
        (b"<html/>", "root element"),
        (b"<svg", "well-formed"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect fill="javascript:x"/></svg>', "javascript"),
    ],
)
def test_unsafe_logos_are_refused(svg: bytes, message: str) -> None:
    problems = check_logo_svg(svg)
    assert any(message in p for p in problems), problems


def test_email_accent() -> None:
    assert check_email_accent("#714B67") == ([], [])
    assert check_email_accent("714b67")[0]
    assert check_email_accent("#ffd43b")[1]  # too light behind white text

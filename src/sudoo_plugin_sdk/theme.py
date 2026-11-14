"""Theme plugins (sudoo.themes): the panel's colours, a logo and the e-mail accent, and nothing else.

A theme is data. It declares, on a `Theme` subclass:

    tokens         a CSS file of custom properties, in the panel's token names only, for light and dark
    logo           optional: an SVG mark shown next to the product name (no scripts, no external references)
    email_accent   optional: the accent of the panel's e-mails, as #RRGGBB (e-mail clients do not read CSS
                   custom properties, so it is given separately)

The tokens file may contain only these rules, in any order:

    :root { ... }                                              light (and the defaults of both)
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) { ... }                  dark, when the system asks for it
    }
    :root[data-theme="dark"] { ... }                           dark, when the person picks it in the panel
    @media (prefers-contrast: more) { :root { ... } }          optional
    @media (prefers-reduced-transparency: reduce) { :root { ... } }   optional

Both dark rules are required and must declare the same values (the panel's own _tokens.scss writes the dark
mixin twice the same way). Only colour, font, shape, shadow and material tokens may be changed: spacing, layout,
type sizes and motion stay the panel's, so a theme cannot break layouts or the reduced-motion behaviour.
"""

from __future__ import annotations

import inspect
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from sudoo_plugin_sdk.plugins.base import SudooPlugin

# --------------------------------------------------------------------------- the panel's tokens

# Every custom property of the panel's web/src/styles/_tokens.scss, by group. tests/test_theme.py compares this
# list with the panel's file when a checkout of the panel is next to this one.
COLOUR_TOKENS: tuple[str, ...] = (
    "--accent", "--accent-ink", "--on-accent", "--accent-soft", "--accent-ring",
    "--bg", "--surface", "--raised", "--hairline", "--hairline-strong", "--text", "--text-2", "--text-3", "--overlay",
    "--positive", "--negative", "--caution", "--working", "--idle",
    "--series-1", "--series-2", "--series-grid",
)  # fmt: skip
FONT_TOKENS: tuple[str, ...] = ("--font", "--mono")
SHAPE_TOKENS: tuple[str, ...] = (
    "--radius-tag", "--radius-control", "--radius-card", "--radius-panel", "--shadow-small", "--shadow-float",
)  # fmt: skip
MATERIAL_TOKENS: tuple[str, ...] = ("--material", "--material-blur")
TYPE_SIZE_TOKENS: tuple[str, ...] = (
    "--text-12", "--text-13", "--text-14", "--text-15", "--text-18", "--text-28", "--text-32",
)  # fmt: skip
SPACE_TOKENS: tuple[str, ...] = ("--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s8", "--s10", "--s12")
LAYOUT_TOKENS: tuple[str, ...] = ("--sidebar", "--topbar")
MOTION_TOKENS: tuple[str, ...] = (
    "--ease", "--ease-move", "--ease-drawer", "--press", "--quick", "--menu", "--enter", "--sheet",
)  # fmt: skip

THEMEABLE_TOKENS: frozenset[str] = frozenset(COLOUR_TOKENS + FONT_TOKENS + SHAPE_TOKENS + MATERIAL_TOKENS)
FIXED_TOKENS: frozenset[str] = frozenset(TYPE_SIZE_TOKENS + SPACE_TOKENS + LAYOUT_TOKENS + MOTION_TOKENS)
PANEL_TOKENS: frozenset[str] = THEMEABLE_TOKENS | FIXED_TOKENS

# The panel's own values of the colours checked for contrast, so a theme that changes only some is checked
# against the rest.
PANEL_LIGHT: dict[str, str] = {
    "--accent": "#714b67", "--accent-ink": "#5f3d56", "--on-accent": "#ffffff", "--bg": "#fafafa",
    "--surface": "#ffffff", "--raised": "#f4f4f5", "--text": "#171717", "--text-2": "#525252", "--text-3": "#737373",
}  # fmt: skip
PANEL_DARK: dict[str, str] = {
    "--accent": "#c79bbd", "--accent-ink": "#d9b6d0", "--on-accent": "#1b1219", "--bg": "#141415",
    "--surface": "#19191b", "--raised": "#232325", "--text": "#ededed", "--text-2": "#a1a1a6", "--text-3": "#85858b",
}  # fmt: skip

# (foreground, background, minimum ratio, refused when lower: True / warned: False)
CONTRAST_PAIRS: tuple[tuple[str, str, float, bool], ...] = (
    ("--text", "--bg", 4.5, True),
    ("--text", "--surface", 4.5, True),
    ("--on-accent", "--accent", 4.5, True),
    ("--text-2", "--surface", 4.5, False),
    ("--text-3", "--surface", 4.5, False),
    ("--accent-ink", "--surface", 4.5, False),
    ("--text", "--raised", 4.5, False),
)

MAX_TOKENS_BYTES = 32 * 1024
MAX_LOGO_BYTES = 64 * 1024
EMAIL_ACCENT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")  # the panel's BRAND_COLOR format
_VALUE_RE = re.compile(r"""^[A-Za-z0-9#%.,()/\s"'+\-_*]{1,300}$""")
_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9-]+)")


@dataclass
class ThemeReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- colours


def parse_colour(value: str) -> tuple[float, float, float] | None:
    """(r, g, b) in 0..1 of #rgb, #rrggbb, #rrggbbaa (alpha ignored), rgb() or rgba(); None for anything else
    (var(), color-mix(), names), which is then not checked for contrast."""
    text = value.strip().lower()
    match = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})", text)
    if match:
        digits = match[1]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    match = re.fullmatch(r"rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})(?:\s*[,/]\s*[\d.]+%?)?\s*\)", text)
    if match:
        parts = [min(int(match[i]), 255) / 255 for i in (1, 2, 3)]
        return (parts[0], parts[1], parts[2])
    return None


def luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG 2 relative luminance."""

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """WCAG 2 contrast ratio, 1 to 21."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --------------------------------------------------------------------------- tokens CSS

_DARK_MEDIA = "(prefers-color-scheme: dark)"
_EXTRA_MEDIA = ("(prefers-contrast: more)", "(prefers-reduced-transparency: reduce)")
_ROOT = ":root"
_DARK_SYSTEM = ':root:not([data-theme="light"])'
_DARK_TOGGLE = ':root[data-theme="dark"]'


def _normalise_selector(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("'", '"')).strip()


def _normalise_media(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().lower())
    return text.replace("( ", "(").replace(" )", ")").replace(" :", ":")


def _split_blocks(css: str, report: ThemeReport) -> list[tuple[str, str]] | None:
    """[(prelude, body)] at one level; None after an error (unbalanced braces)."""
    blocks: list[tuple[str, str]] = []
    position = 0
    while True:
        start = css.find("{", position)
        if start == -1:
            if css[position:].strip():
                report.errors.append(f"Unexpected text outside a rule: {css[position:].strip()[:60]!r}.")
                return None
            return blocks
        depth, end = 0, start
        for end in range(start, len(css)):
            if css[end] == "{":
                depth += 1
            elif css[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        if depth != 0:
            report.errors.append("The braces { } are not balanced.")
            return None
        blocks.append((css[position:start].strip(), css[start + 1 : end]))
        position = end + 1


def _declarations(body: str, where: str, report: ThemeReport) -> dict[str, str]:
    found: dict[str, str] = {}
    if "{" in body or "}" in body:
        report.errors.append(f"{where}: nested rules are not allowed.")
        return found
    for raw in body.split(";"):
        if not raw.strip():
            continue
        name, colon, value = raw.partition(":")
        name, value = name.strip(), value.strip()
        if not colon or not value:
            report.errors.append(f"{where}: {raw.strip()[:60]!r} is not a declaration (name: value).")
            continue
        if name == "color-scheme":
            if value not in ("light", "dark"):
                report.errors.append(f"{where}: color-scheme must be light or dark.")
            continue
        if not name.startswith("--"):
            report.errors.append(f"{where}: only custom properties are allowed, not {name!r}.")
            continue
        if name in FIXED_TOKENS:
            report.errors.append(
                f"{where}: {name} is a panel token that themes may not change (spacing, layout, type sizes and "
                "motion stay the panel's)."
            )
            continue
        if name not in THEMEABLE_TOKENS:
            report.errors.append(f"{where}: {name} is not one of the panel's tokens.")
            continue
        lowered = value.lower()
        if (
            not _VALUE_RE.match(value)
            or "url(" in lowered
            or "expression" in lowered
            or "javascript" in lowered
            or "image(" in lowered
            or "image-set" in lowered
        ):
            report.errors.append(f"{where}: the value of {name} is not allowed ({value[:60]!r}).")
            continue
        for referenced in _VAR_RE.findall(value):
            if referenced not in PANEL_TOKENS:
                report.errors.append(f"{where}: {name} refers to {referenced}, which is not a panel token.")
        if name in found:
            report.warnings.append(f"{where}: {name} is declared twice; the last one counts.")
        found[name] = value
    return found


def check_tokens_css(css: str) -> ThemeReport:
    """Check a theme's tokens file; the report has the light and dark values on success."""
    report = ThemeReport()
    if len(css.encode()) > MAX_TOKENS_BYTES:
        report.errors.append("The tokens file is larger than 32 KB.")
        return report
    if "\\" in css or "<" in css:
        report.errors.append("The tokens file may not contain backslashes or '<'.")
        return report
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    if "/*" in css:
        report.errors.append("A comment is not closed.")
        return report
    blocks = _split_blocks(css, report)
    if blocks is None:
        return report
    light: dict[str, str] | None = None
    dark_system: dict[str, str] | None = None
    dark_toggle: dict[str, str] | None = None
    seen: set[str] = set()
    for prelude, body in blocks:
        if ";" in prelude:
            report.errors.append(f"Unexpected text before a rule: {prelude[:60]!r}.")
            continue
        key = _normalise_media(prelude) if prelude.startswith("@") else _normalise_selector(prelude)
        if key in seen:
            report.errors.append(f"The rule {key[:60]} appears twice; write each rule once.")
            continue
        seen.add(key)
        if prelude.startswith("@"):
            if not prelude.lower().startswith("@media"):
                report.errors.append(f"{prelude.split()[0]} is not allowed; only @media rules for dark mode.")
                continue
            media = _normalise_media(prelude[len("@media") :])
            inner = _split_blocks(body, report)
            if inner is None:
                continue
            for selector, inner_body in inner:
                selector = _normalise_selector(selector)
                where = f"@media {media} {selector}"
                if media == _DARK_MEDIA and selector == _DARK_SYSTEM:
                    dark_system = _declarations(inner_body, where, report)
                elif media in _EXTRA_MEDIA and selector == _ROOT:
                    _declarations(inner_body, where, report)
                else:
                    report.errors.append(
                        f"{where}: not allowed. Use {_DARK_SYSTEM} inside {_DARK_MEDIA}, or :root inside "
                        "prefers-contrast / prefers-reduced-transparency."
                    )
            continue
        selector = _normalise_selector(prelude)
        if selector == _ROOT:
            light = _declarations(body, selector, report)
        elif selector == _DARK_TOGGLE:
            dark_toggle = _declarations(body, selector, report)
        else:
            report.errors.append(f"The selector {selector[:60]!r} is not allowed; use :root and the dark rules.")
    if light is None:
        report.errors.append("The tokens file has no :root rule (light values).")
    if dark_system is None or dark_toggle is None:
        report.errors.append(
            f"A theme needs dark values twice, as the panel does: {_DARK_SYSTEM} inside @media {_DARK_MEDIA}, and "
            f"{_DARK_TOGGLE}."
        )
    elif dark_system != dark_toggle:
        report.errors.append(f"The two dark rules ({_DARK_SYSTEM} and {_DARK_TOGGLE}) must declare the same values.")
    if report.errors:
        return report
    assert light is not None and dark_system is not None  # noqa: S101 - checked above
    report.light = light
    report.dark = {**light, **dark_system}
    _check_contrast(report, "light", {**PANEL_LIGHT, **light})
    _check_contrast(report, "dark", {**PANEL_DARK, **light, **dark_system})
    return report


def _resolve(values: dict[str, str], name: str, depth: int = 0) -> str | None:
    value = values.get(name)
    if value is None or depth > 5:
        return None
    match = re.fullmatch(r"var\(\s*(--[A-Za-z0-9-]+)\s*\)", value.strip())
    return _resolve(values, match[1], depth + 1) if match else value


def _check_contrast(report: ThemeReport, mode: str, values: dict[str, str]) -> None:
    for foreground, background, minimum, required in CONTRAST_PAIRS:
        fg_text, bg_text = _resolve(values, foreground), _resolve(values, background)
        fg = parse_colour(fg_text) if fg_text else None
        bg = parse_colour(bg_text) if bg_text else None
        if fg is None or bg is None:
            continue
        ratio = contrast(fg, bg)
        if ratio < minimum:
            message = (
                f"{mode}: {foreground} on {background} has a contrast of {ratio:.2f}:1, below {minimum}:1 "
                "(WCAG AA for text)."
            )
            (report.errors if required else report.warnings).append(message)


# --------------------------------------------------------------------------- logo SVG

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_FORBIDDEN_ELEMENTS = frozenset(
    {"script", "foreignobject", "iframe", "embed", "object", "image", "a", "animate", "set", "animatemotion",
     "animatetransform", "handler", "listener", "audio", "video", "canvas", "font", "font-face"}
)  # fmt: skip
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _external_url(text: str) -> bool:
    return any(not target.strip().startswith("#") for _, target in _URL_RE.findall(text))


def check_logo_svg(data: bytes) -> list[str]:
    """What is wrong with a logo SVG (an empty list when it is safe): no scripts, event handlers, links, embedded
    documents, animations or references outside the file. The SDK refuses rather than rewriting a file."""
    problems: list[str] = []
    if len(data) > MAX_LOGO_BYTES:
        return ["The logo is larger than 64 KB."]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["The logo is not UTF-8 text."]
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return ["The logo may not contain a DOCTYPE or entities."]
    if re.search(r"<\?(?!xml\s)", text):
        return ["The logo may not contain processing instructions."]
    if "javascript:" in lowered or "data:" in lowered:
        problems.append("The logo may not contain javascript: or data: addresses.")
    try:
        root = ET.fromstring(text)  # noqa: S314 - DOCTYPE and entities refused above
    except ET.ParseError as error:
        return [f"The logo is not well-formed XML ({error})."]
    if root.tag != f"{{{SVG_NS}}}svg":
        problems.append('The root element must be <svg xmlns="http://www.w3.org/2000/svg">.')
    if not root.get("viewBox"):
        problems.append("The logo needs a viewBox, so it scales to any size.")
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = _local(element.tag)
        if name in _FORBIDDEN_ELEMENTS:
            problems.append(f"<{name}> is not allowed in a logo.")
        if name == "style" and element.text and ("@import" in element.text.lower() or _external_url(element.text)):
            problems.append("<style> may not import or refer to other files.")
        for attribute, value in element.attrib.items():
            local = _local(attribute)
            if local.startswith("on"):
                problems.append(f"The event handler {local} is not allowed.")
            elif local == "href" and not value.strip().startswith("#"):
                problems.append(f"<{name} href={value[:40]!r}> refers outside the file; only #id is allowed.")
            elif _external_url(value):
                problems.append(f"{local}={value[:40]!r} refers outside the file; only url(#id) is allowed.")
    return sorted(set(problems))


def check_email_accent(value: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) of an e-mail accent: #RRGGBB, readable as a button with white text."""
    if not EMAIL_ACCENT_RE.match(value):
        return [f"email_accent {value!r} must be a colour as #RRGGBB."], []
    rgb = parse_colour(value)
    assert rgb is not None  # noqa: S101 - matched above
    ratio = contrast(rgb, (1.0, 1.0, 1.0))
    if ratio < 4.5:
        return [], [f"email_accent {value} has a contrast of {ratio:.2f}:1 with white button text (4.5:1 wanted)."]
    return [], []


# --------------------------------------------------------------------------- the plugin class


class Theme(SudooPlugin):
    """Subclass, set the class attributes, register under sudoo.themes. File paths are relative to the folder of
    the module that defines the subclass, and are shipped with it in src/.

        class Midnight(Theme):
            label = "Midnight"
            tokens = "tokens.css"
            logo = "logo.svg"
            email_accent = "#3b5bdb"
    """

    label: ClassVar[str] = "Theme"
    tokens: ClassVar[str] = "tokens.css"
    logo: ClassVar[str | None] = None
    email_accent: ClassVar[str | None] = None

    @classmethod
    def folder(cls) -> Path:
        return Path(inspect.getfile(cls)).resolve().parent

    @classmethod
    def _file(cls, relative: str) -> Path:
        folder = cls.folder()
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder):
            raise ValueError(f"{relative} is outside the theme's folder.")
        return path

    @classmethod
    def tokens_css(cls) -> str:
        return cls._file(cls.tokens).read_text(encoding="utf-8")

    @classmethod
    def logo_svg(cls) -> bytes | None:
        return None if cls.logo is None else cls._file(cls.logo).read_bytes()

    @classmethod
    def check(cls) -> ThemeReport:
        """Everything about the theme: the tokens file, the logo and the e-mail accent."""
        try:
            report = check_tokens_css(cls.tokens_css())
        except (OSError, ValueError) as error:
            report = ThemeReport(errors=[f"The tokens file {cls.tokens} cannot be read: {error}"])
        if cls.logo is not None:
            try:
                report.errors.extend(f"{cls.logo}: {problem}" for problem in check_logo_svg(cls.logo_svg() or b""))
            except (OSError, ValueError) as error:
                report.errors.append(f"The logo {cls.logo} cannot be read: {error}")
        if cls.email_accent is not None:
            errors, warnings = check_email_accent(cls.email_accent)
            report.errors.extend(errors)
            report.warnings.extend(warnings)
        if not cls.label.strip() or len(cls.label) > 40:
            report.errors.append("label must be 1 to 40 characters.")
        return report

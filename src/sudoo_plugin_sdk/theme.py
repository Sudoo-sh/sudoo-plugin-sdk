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
    """The result of checking a theme.

    Attributes:
        errors: Problems that make the theme invalid.
        warnings: Problems that are only reported.
        light: The values of the light mode.
        dark: The values of the dark mode.
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Tell whether there are no errors.

        Returns:
            True when `errors` is empty.
        """
        return not self.errors


# --------------------------------------------------------------------------- colours


def parse_colour(value: str) -> tuple[float, float, float] | None:
    """Read a colour value.

    Args:
        value: The colour text.

    Returns:
        Red, green and blue from 0 to 1, or None for anything that is not understood.
    """
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
    """Compute the WCAG 2 relative luminance of a colour.

    Args:
        rgb: Red, green and blue, each from 0 to 1.

    Returns:
        The relative luminance.
    """

    def channel(c: float) -> float:
        """Convert one colour channel to linear light.

        Args:
            c: The channel value from 0 to 1.

        Returns:
            The linear value.
        """
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Compute the WCAG contrast ratio of two colours.

    Args:
        a: The first colour as red, green and blue from 0 to 1.
        b: The second colour in the same form.

    Returns:
        The ratio, 1 or more.
    """
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --------------------------------------------------------------------------- tokens CSS

_DARK_MEDIA = "(prefers-color-scheme: dark)"
_EXTRA_MEDIA = ("(prefers-contrast: more)", "(prefers-reduced-transparency: reduce)")
_ROOT = ":root"
_DARK_SYSTEM = ':root:not([data-theme="light"])'
_DARK_TOGGLE = ':root[data-theme="dark"]'


def _normalise_selector(text: str) -> str:
    """Make selector text comparable: single quotes become double quotes and white space collapses.

    Args:
        text: The selector.

    Returns:
        The normalised selector.
    """
    return re.sub(r"\s+", " ", text.replace("'", '"')).strip()


def _normalise_media(text: str) -> str:
    """Make a media query comparable: lower case, white space collapsed and no space inside parentheses.

    Args:
        text: The media query.

    Returns:
        The normalised text.
    """
    text = re.sub(r"\s+", " ", text.strip().lower())
    return text.replace("( ", "(").replace(" )", ")").replace(" :", ":")


def _split_blocks(css: str, report: ThemeReport) -> list[tuple[str, str]] | None:
    """Split CSS into top-level rules.

    Args:
        css: The CSS text.
        report: The report that receives errors.

    Returns:
        The prelude and the body of each rule, or None after an error.
    """
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
    """Read the declarations of one rule.

    Args:
        body: The text between the braces.
        where: A name of the rule, for messages.
        report: The report that receives errors and warnings.

    Returns:
        The values by token name. Tokens that are not allowed are reported and left out.
    """
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
            not _VALUE_RE.fullmatch(value)
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


def _strip_comments(css: str, report: ThemeReport) -> str | None:
    """Remove the comments from CSS.

    Args:
        css: The CSS text.
        report: The report that receives errors.

    Returns:
        The CSS without comments, or None after an error.
    """
    out: list[str] = []
    position = 0
    while position < len(css):
        char = css[position]
        if char in "\"'":
            end = position + 1
            while end < len(css) and css[end] not in (char, "\n"):
                end += 1
            if end >= len(css) or css[end] != char:
                report.errors.append("A quoted string is not closed.")
                return None
            text = css[position : end + 1]
            if "/*" in text or "*/" in text:
                report.errors.append(f"A quoted value may not contain /* or */: {text[:60]!r}.")
                return None
            out.append(text)
            position = end + 1
        elif css.startswith("/*", position):
            end = css.find("*/", position + 2)
            if end == -1:
                report.errors.append("A comment is not closed.")
                return None
            position = end + 2
        else:
            out.append(char)
            position += 1
    return "".join(out)


def check_tokens_css(css: str) -> ThemeReport:
    """Check a tokens file.

    Args:
        css: The CSS text.

    Returns:
        The report, with the light and dark values when there are no errors.
    """
    report = ThemeReport()
    if len(css.encode()) > MAX_TOKENS_BYTES:
        report.errors.append("The tokens file is larger than 32 KB.")
        return report
    if "\\" in css or "<" in css:
        report.errors.append("The tokens file may not contain backslashes or '<'.")
        return report
    stripped = _strip_comments(css, report)
    if stripped is None:
        return report
    css = stripped
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
    """Find the value of a token, following `var(--other)` references.

    Args:
        values: The token values.
        name: The token to look up.
        depth: How many references were followed so far; after 5 the result is None.

    Returns:
        The value, or None when it is missing or the chain is too long.
    """
    value = values.get(name)
    if value is None or depth > 5:
        return None
    match = re.fullmatch(r"var\(\s*(--[A-Za-z0-9-]+)\s*\)", value.strip())
    return _resolve(values, match[1], depth + 1) if match else value


def _check_contrast(report: ThemeReport, mode: str, values: dict[str, str]) -> None:
    """Check the contrast of each pair in `CONTRAST_PAIRS`.

    Args:
        report: The report that receives errors and warnings.
        mode: "light" or "dark", for messages.
        values: The token values, panel defaults included.
    """
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
# Logos are checked against an allow-list: SVG shapes, text, gradients, clips, masks and simple filters, with
# presentation attributes only. Anything else (scripts, <style>, links, embedded documents, animations, elements
# outside the SVG namespace, style attributes) is refused.
_ALLOWED_ELEMENTS = frozenset(
    {"svg", "g", "defs", "title", "desc", "symbol", "use", "path", "rect", "circle", "ellipse", "line", "polyline",
     "polygon", "text", "tspan", "textpath", "lineargradient", "radialgradient", "stop", "pattern", "clippath",
     "mask", "marker", "filter", "feblend", "fecolormatrix", "fecomposite", "fedropshadow", "feflood",
     "fegaussianblur", "femerge", "femergenode", "femorphology", "feoffset"}
)  # fmt: skip
_ALLOWED_ATTRIBUTES = frozenset(
    {"id", "class", "version", "viewbox", "preserveaspectratio", "width", "height", "x", "y", "x1", "y1", "x2",
     "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr", "d", "points", "pathlength", "transform", "href",
     "role", "aria-label", "aria-hidden", "aria-labelledby", "aria-describedby", "focusable", "lang",
     "gradientunits", "gradienttransform", "spreadmethod", "offset", "stop-color", "stop-opacity",
     "patternunits", "patterncontentunits", "patterntransform", "clippathunits", "maskunits", "maskcontentunits",
     "markerunits", "markerwidth", "markerheight", "refx", "refy", "orient", "filterunits", "primitiveunits",
     "in", "in2", "result", "stddeviation", "dx", "dy", "mode", "type", "values", "operator", "k1", "k2", "k3",
     "k4", "radius", "edgemode", "flood-color", "flood-opacity", "lighting-color",
     "color-interpolation-filters", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
     "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset",
     "stroke-opacity", "opacity", "clip-path", "clip-rule", "mask", "filter", "marker-start", "marker-mid",
     "marker-end", "color", "display", "visibility", "overflow", "paint-order", "vector-effect",
     "shape-rendering", "text-rendering", "color-interpolation", "font-family", "font-size", "font-weight",
     "font-style", "font-variant", "font-stretch", "text-anchor", "dominant-baseline", "alignment-baseline",
     "baseline-shift", "letter-spacing", "word-spacing", "text-decoration", "rotate", "textlength",
     "lengthadjust", "startoffset", "method", "spacing", "side", "writing-mode", "direction", "unicode-bidi"}
)  # fmt: skip
_XML_NS = "http://www.w3.org/XML/1998/namespace"
_ALLOWED_NAMESPACED = frozenset({f"{{{XLINK_NS}}}href", f"{{{_XML_NS}}}space", f"{{{_XML_NS}}}lang"})
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_NON_LOCAL_URL_RE = re.compile(r"url\(\s*(?!['\"]?\s*#)", re.IGNORECASE)


def _local(tag: str) -> str:
    """Return the lower-case local name of an XML tag or attribute.

    Args:
        tag: The name, possibly with a namespace in braces.

    Returns:
        The name without the namespace.
    """
    return tag.rsplit("}", 1)[-1].lower()


def _external_url(text: str) -> bool:
    """Tell whether a text holds a url() that points outside the document.

    Args:
        text: The attribute value.

    Returns:
        True when a url() does not point to a "#" fragment.
    """
    return any(not target.strip().startswith("#") for _, target in _URL_RE.findall(text)) or bool(
        _NON_LOCAL_URL_RE.search(text)
    )


def _attribute_problem(element: str, attribute: str, value: str) -> str | None:
    """Check one attribute of a logo element.

    Args:
        element: The element's local name, for messages.
        attribute: The attribute's name.
        value: The attribute's value.

    Returns:
        A message, or None when the attribute is allowed.
    """
    local = _local(attribute)
    if local.startswith("on"):
        return f"The event handler {local} is not allowed."
    if local == "style":
        return f"<{element} style=...>: style attributes are not allowed; use presentation attributes (fill=...)."
    if attribute.startswith("{") and attribute not in _ALLOWED_NAMESPACED:
        return f"<{element}>: the attribute {attribute[:80]!r} is not allowed (editor data is not needed in a logo)."
    if not attribute.startswith("{") and local not in _ALLOWED_ATTRIBUTES:
        return f"<{element}>: the attribute {local[:40]!r} is not allowed in a logo."
    lowered = value.lower()
    if local == "href":
        if not value.strip().startswith("#"):
            return f"<{element} href={value[:40]!r}> refers outside the file; only #id is allowed."
        return None
    if _external_url(value):
        return f"{local}={value[:40]!r} refers outside the file; only url(#id) is allowed."
    if "\\" in value or "image-set" in lowered or "image(" in lowered or "expression(" in lowered:
        return f"{local}={value[:40]!r} is not allowed."
    return None


def check_logo_svg(data: bytes) -> list[str]:
    """Check a logo file.

    Args:
        data: The file's bytes.

    Returns:
        The sorted problems, empty when the logo is allowed.
    """
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
    if "<!--" in text or "<![cdata[" in lowered:
        # an HTML parser reads these differently from an XML parser when the SVG is placed inline in a page
        return ["The logo may not contain comments or CDATA sections."]
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
        if not element.tag.startswith(f"{{{SVG_NS}}}"):
            problems.append(f"<{name}> is not an SVG element; only SVG elements are allowed in a logo.")
        elif name not in _ALLOWED_ELEMENTS:
            problems.append(f"<{name}> is not allowed in a logo.")
        for attribute, value in element.attrib.items():
            problem = _attribute_problem(name, attribute, value)
            if problem:
                problems.append(problem)
    return sorted(set(problems))


def check_email_accent(value: str) -> tuple[list[str], list[str]]:
    """Check an e-mail accent colour.

    Args:
        value: The colour text.

    Returns:
        The errors and the warnings.
    """
    if not EMAIL_ACCENT_RE.fullmatch(value):
        return [f"email_accent {value!r} must be a colour as #RRGGBB."], []
    rgb = parse_colour(value)
    assert rgb is not None  # noqa: S101 - matched above
    ratio = contrast(rgb, (1.0, 1.0, 1.0))
    if ratio < 4.5:
        return [], [f"email_accent {value} has a contrast of {ratio:.2f}:1 with white button text (4.5:1 wanted)."]
    return [], []


# --------------------------------------------------------------------------- the plugin class


class Theme(SudooPlugin):
    """Base class of theme plugins.

    Subclass, set the class attributes, register under sudoo.themes. File paths are relative to the folder of
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
        """The folder of the module that defines the theme class.

        Returns:
            The folder.
        """
        return Path(inspect.getfile(cls)).resolve().parent

    @classmethod
    def _file(cls, relative: str) -> Path:
        """Resolve a file path relative to the theme's folder.

        Args:
            relative: The path.

        Returns:
            The absolute path.

        Raises:
            ValueError: When the path is outside the theme's folder.
        """
        folder = cls.folder()
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder):
            raise ValueError(f"{relative} is outside the theme's folder.")
        return path

    @classmethod
    def tokens_css(cls) -> str:
        """Read the tokens file.

        Returns:
            The CSS text.
        """
        return cls._file(cls.tokens).read_text(encoding="utf-8")

    @classmethod
    def logo_svg(cls) -> bytes | None:
        """Read the logo file.

        Returns:
            The bytes, or None when the theme has no logo.
        """
        return None if cls.logo is None else cls._file(cls.logo).read_bytes()

    @classmethod
    def check(cls) -> ThemeReport:
        """Check the tokens file, the logo and the e-mail accent.

        Returns:
            The report.
        """
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

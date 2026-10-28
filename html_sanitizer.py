"""Minimal allowlist sanitizer for generated legal-document HTML fragments.

Documents are previews, not arbitrary web pages. Keep only structural text
markup and a restricted set of inert inline styles; never keep links, images,
forms, scripts, event handlers, embedded content, or CSS URL-bearing values.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "article", "blockquote", "br", "code", "div", "em", "footer", "h1",
    "h2", "h3", "h4", "header", "hr", "i", "li", "ol", "p", "pre",
    "section", "small", "span", "strong", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "u", "ul",
}
VOID_TAGS = {"br", "hr"}
ALLOWED_CSS_PROPERTIES = {
    "align-items", "background", "background-color", "border", "border-bottom",
    "border-left", "border-right", "border-top", "box-sizing", "color", "direction",
    "display", "font-family", "font-size", "font-style", "font-weight", "height",
    "justify-content", "line-height", "margin", "margin-bottom", "margin-top",
    "min-height", "padding", "padding-bottom", "padding-right", "text-align",
    "text-decoration", "text-transform", "vertical-align", "white-space", "width",
}
_DANGEROUS_CSS = re.compile(
    r"(?:url\s*\(|expression\s*\(|javascript\s*:|vbscript\s*:|@import|"
    r"-moz-binding|behavior\s*:|data\s*:\s*text/html|[<>])",
    re.IGNORECASE,
)


def _sanitize_style(value: str) -> str:
    safe: list[str] = []
    for declaration in value.split(";"):
        if ":" not in declaration:
            continue
        property_name, property_value = declaration.split(":", 1)
        prop = property_name.strip().lower()
        val = property_value.strip()
        if not prop or prop not in ALLOWED_CSS_PROPERTIES or not val:
            continue
        if _DANGEROUS_CSS.search(val):
            continue
        if prop == "display" and val.lower() not in {"block", "inline", "inline-block", "flex", "table", "table-row", "table-cell"}:
            continue
        safe.append(f"{prop}: {val}")
    return "; ".join(safe)


class _DocumentSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            return
        clean_attrs: list[str] = []
        for key, value in attrs:
            # Inline style is the only accepted attribute. This removes onclick,
            # onerror, href, src, srcdoc, class/id hooks, and form attributes.
            if key.lower() == "style" and value:
                clean_style = _sanitize_style(value)
                if clean_style:
                    clean_attrs.append(f' style="{html.escape(clean_style, quote=True)}"')
        self.parts.append(f"<{tag}{''.join(clean_attrs)}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self.open_tags:
            return
        # Close nested tags consistently even for malformed input.
        while self.open_tags:
            current = self.open_tags.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:  # pragma: no cover - parser handles refs
        self.parts.append(f"&amp;{html.escape(name)};")

    def handle_charref(self, name: str) -> None:  # pragma: no cover - parser handles refs
        self.parts.append(f"&amp;#{html.escape(name)};")

    def close(self) -> None:
        super().close()
        while self.open_tags:
            self.parts.append(f"</{self.open_tags.pop()}>")


def sanitize_document_html(value: str) -> str:
    """Return a safe HTML fragment containing only approved passive markup."""
    parser = _DocumentSanitizer()
    parser.feed(value or "")
    parser.close()
    return "".join(parser.parts)

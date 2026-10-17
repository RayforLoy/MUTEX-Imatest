"""Read inert SVG artwork without resolving a DTD or external resources."""
from __future__ import annotations
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def read_svg(path):
    path = Path(path)
    if path.stat().st_size > 16*2**20:
        raise ValueError("SVG source limit is 16 MiB")
    text = path.read_text(encoding="utf-8-sig")
    # CorelDRAW/Illustrator commonly write this harmless standard declaration.
    # Drop it before parsing/rendering; never fetch the external DTD. Internal
    # subsets, custom declarations and entity definitions remain disallowed.
    if re.search(r"<!\s*ENTITY\b", text, re.I):
        raise ValueError("SVG entity declarations are disabled")
    declaration = re.compile(r'<!DOCTYPE\s+svg\s+PUBLIC\s+([\'"])-//W3C//DTD SVG 1\.[01]//EN\1\s+([\'"])https?://www\.w3\.org/(?:Graphics/SVG/1\.1/DTD/svg11\.dtd|TR/2001/REC-SVG-20010904/DTD/svg10\.dtd)\2\s*>', re.I)
    text = declaration.sub("", text)
    if re.search(r"<!\s*DOCTYPE\b", text, re.I):
        raise ValueError("SVG custom/external DTDs and internal entity subsets are disabled")
    if re.search(r"<\?\s*xml-stylesheet\b", text, re.I):
        raise ValueError("SVG external stylesheets are disabled")
    tree = ET.fromstring(text)
    if tree.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("Expected an SVG root element")
    def check_css(value):
        if re.search(r"@import\b", value, re.I):
            raise ValueError("SVG external CSS imports are disabled")
        for match in re.finditer(r"url\(\s*(.*?)\s*\)", value, re.I | re.S):
            target = match.group(1).strip().strip("\"'").strip()
            if not target.startswith("#") or "\\" in target:
                raise ValueError("SVG external references are disabled")
    for node in tree.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script", "foreignobject"}:
            raise ValueError("SVG scripts and foreign objects are disabled")
        if tag == "style":
            check_css("".join(node.itertext()))
        for key, value in node.attrib.items():
            local = key.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                raise ValueError("SVG event handlers are disabled")
            if local == "href" and not value.strip().startswith("#"):
                raise ValueError("SVG external references are disabled")
            check_css(value)
    return text, tree


def svg_dimensions(tree):
    """Return viewBox and the explicit physical document size in millimetres."""
    view = [float(v) for v in re.split(r"[\s,]+", tree.attrib.get("viewBox", "").strip()) if v]
    def length(value):
        match = re.fullmatch(r"\s*([\d.eE+-]+)\s*(mm|cm|in|pt|px)?\s*", value)
        if not match:
            return None
        number, unit = float(match[1]), match[2] or "px"
        return number*{"mm":1, "cm":10, "in":25.4, "pt":25.4/72, "px":25.4/96}[unit]
    size = [length(tree.attrib.get(k, "")) for k in ["width", "height"]]
    if len(view) != 4 or min(view[2:]) <= 0:
        raise ValueError("USAF vector detection requires a valid SVG viewBox")
    if any(v is None or v <= 0 for v in size):
        raise ValueError("USAF vector detection requires explicit SVG width and height")
    return view, tuple(size)

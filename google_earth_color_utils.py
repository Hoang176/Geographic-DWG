# -*- coding: utf-8 -*-
"""Color utilities for Google Earth KML/KMZ import.

Google Earth KML stores colors as AABBGGRR.
AutoCAD TrueColor uses RGB and the COM object is version dependent.
"""

from __future__ import annotations

from typing import Optional, Tuple

Color = Tuple[int, int, int]


def kml_color_to_rgb(value: Optional[str]) -> Optional[Color]:
    """Convert KML color AABBGGRR to RGB.

    Example:
        ff0000ff -> (255, 0, 0)
        ff00ff00 -> (0, 255, 0)
        ffff0000 -> (0, 0, 255)
    """
    if not value:
        return None
    s = value.strip().replace("#", "")
    try:
        if len(s) == 8:
            b = int(s[2:4], 16)
            g = int(s[4:6], 16)
            r = int(s[6:8], 16)
            return r, g, b
        if len(s) == 6:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None
    return None


def rgb_to_nearest_aci(rgb: Optional[Color]) -> int:
    """Nearest basic AutoCAD ACI fallback when TrueColor is unavailable."""
    if rgb is None:
        return 256
    r, g, b = rgb
    palette = {
        1: (255, 0, 0),
        2: (255, 255, 0),
        3: (0, 255, 0),
        4: (0, 255, 255),
        5: (0, 0, 255),
        6: (255, 0, 255),
        7: (255, 255, 255),
        8: (128, 128, 128),
        9: (192, 192, 192),
    }
    return min(palette, key=lambda i: (palette[i][0] - r) ** 2 + (palette[i][1] - g) ** 2 + (palette[i][2] - b) ** 2)


def make_truecolor(acad, doc, rgb: Optional[Color]):
    """Create an AutoCAD AcCmColor object robustly across AutoCAD versions."""
    if rgb is None:
        return None
    r, g, b = [int(max(0, min(255, c))) for c in rgb]
    app = getattr(doc, "Application", None) or acad
    candidates = []
    try:
        major = str(app.Version).split(".")[0]
        if major:
            candidates.append(f"AutoCAD.AcCmColor.{major}")
    except Exception:
        pass
    candidates += ["AutoCAD.AcCmColor", "AutoCAD.AcCmColor.25", "AutoCAD.AcCmColor.24", "AutoCAD.AcCmColor.23", "AutoCAD.AcCmColor.22"]
    for progid in candidates:
        try:
            color = app.GetInterfaceObject(progid)
            color.SetRGB(r, g, b)
            return color
        except Exception:
            continue
    return None


def apply_autocad_color(acad, doc, obj, rgb: Optional[Color]) -> bool:
    """Apply RGB to an AutoCAD entity or layer.

    Returns True when either TrueColor or ACI fallback was applied.
    """
    if rgb is None:
        return False
    tc = make_truecolor(acad, doc, rgb)
    if tc is not None:
        try:
            obj.TrueColor = tc
            return True
        except Exception:
            pass
    try:
        obj.Color = rgb_to_nearest_aci(rgb)
        return True
    except Exception:
        return False

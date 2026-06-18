# -*- coding: utf-8 -*-
"""Import Google Earth KML/KMZ into AutoCAD while preserving colors.

Main purpose for the Geographic app:
- Read KML/KMZ exported/copied from Google Earth Pro.
- Preserve Google Earth style color into AutoCAD TrueColor when possible.
- Preserve folder/name/style metadata as layer/object information.
- Support Point, LineString and Polygon placemarks.

KML color format is AABBGGRR. AutoCAD TrueColor expects RGB.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

Point3 = Tuple[float, float, float]
Color = Tuple[int, int, int]

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def kml_color_to_rgb(value: Optional[str]) -> Optional[Color]:
    """Convert KML AABBGGRR to RGB."""
    if not value:
        return None
    s = value.strip().replace("#", "")
    if len(s) == 8:
        # aa bb gg rr
        try:
            b = int(s[2:4], 16)
            g = int(s[4:6], 16)
            r = int(s[6:8], 16)
            return r, g, b
        except ValueError:
            return None
    if len(s) == 6:
        try:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        except ValueError:
            return None
    return None


def safe_layer_name(text: str) -> str:
    name = re.sub(r"[<>/\\\":;?*|=,`]+", "_", (text or "GoogleEarth").strip())
    return name[:240] or "GoogleEarth"


def parse_coord_text(text: str) -> List[Point3]:
    pts: List[Point3] = []
    for token in (text or "").replace("\n", " ").replace("\t", " ").split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                alt = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0
                pts.append((lon, lat, alt))
            except ValueError:
                pass
    return pts


@dataclass
class GEFeature:
    name: str
    folder: str
    geom_type: str
    coords: List[Point3]
    color: Optional[Color]
    style_url: str = ""
    description: str = ""


class GoogleEarthKmlReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.root = self._load_root()
        self.styles = self._read_styles()

    def _load_root(self):
        path = self.path
        if path.suffix.lower() == ".kmz":
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                kml_name = "doc.kml" if "doc.kml" in names else next(n for n in names if n.lower().endswith(".kml"))
                data = zf.read(kml_name)
            return ET.fromstring(data)
        return ET.parse(path).getroot()

    def _read_styles(self) -> Dict[str, Optional[Color]]:
        styles: Dict[str, Optional[Color]] = {}
        for style in self.root.iter():
            if strip_ns(style.tag) != "Style":
                continue
            sid = style.attrib.get("id")
            if not sid:
                continue
            color = None
            for node in style.iter():
                if strip_ns(node.tag) == "color" and node.text:
                    color = kml_color_to_rgb(node.text)
                    if color:
                        break
            styles["#" + sid] = color
        for style_map in self.root.iter():
            if strip_ns(style_map.tag) != "StyleMap":
                continue
            sid = style_map.attrib.get("id")
            if not sid:
                continue
            normal_url = None
            for pair in style_map:
                if strip_ns(pair.tag) != "Pair":
                    continue
                key = pair.find("./kml:key", KML_NS)
                url = pair.find("./kml:styleUrl", KML_NS)
                if key is not None and key.text == "normal" and url is not None:
                    normal_url = url.text
                    break
            if normal_url and normal_url in styles:
                styles["#" + sid] = styles[normal_url]
        return styles

    def features(self) -> List[GEFeature]:
        result: List[GEFeature] = []
        self._walk(self.root, "GoogleEarth", result)
        return result

    def _walk(self, node, folder: str, out: List[GEFeature]) -> None:
        tag = strip_ns(node.tag)
        if tag == "Folder":
            name_node = node.find("./kml:name", KML_NS)
            folder = name_node.text.strip() if name_node is not None and name_node.text else folder
        if tag == "Placemark":
            feature = self._placemark(node, folder)
            if feature:
                out.append(feature)
            return
        for child in node:
            self._walk(child, folder, out)

    def _placemark(self, pm, folder: str) -> Optional[GEFeature]:
        name_node = pm.find("./kml:name", KML_NS)
        desc_node = pm.find("./kml:description", KML_NS)
        style_node = pm.find("./kml:styleUrl", KML_NS)
        name = name_node.text.strip() if name_node is not None and name_node.text else "GoogleEarth_Object"
        desc = desc_node.text.strip() if desc_node is not None and desc_node.text else ""
        style_url = style_node.text.strip() if style_node is not None and style_node.text else ""
        color = self.styles.get(style_url)
        inline_style = pm.find("./kml:Style", KML_NS)
        if inline_style is not None:
            for n in inline_style.iter():
                if strip_ns(n.tag) == "color" and n.text:
                    color = kml_color_to_rgb(n.text) or color
                    break
        for geom in pm.iter():
            gtag = strip_ns(geom.tag)
            if gtag in ("Point", "LineString", "LinearRing"):
                coord = geom.find("./kml:coordinates", KML_NS)
                pts = parse_coord_text(coord.text if coord is not None else "")
                if pts:
                    geom_type = "Point" if gtag == "Point" else "LineString"
                    return GEFeature(name, folder, geom_type, pts, color, style_url, desc)
            if gtag == "Polygon":
                coord = geom.find(".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS)
                pts = parse_coord_text(coord.text if coord is not None else "")
                if pts:
                    return GEFeature(name, folder, "Polygon", pts, color, style_url, desc)
        return None


class AutoCADGoogleEarthImporter:
    def __init__(self, acad, doc, transformer=None, log=None):
        self.acad = acad
        self.doc = doc
        self.transformer = transformer
        self.log = log or (lambda text: None)

    def _to_dwg(self, pt: Point3) -> Point3:
        lon, lat, alt = pt
        if self.transformer is None:
            return lon, lat, alt
        x, y = self.transformer.transform(lon, lat)
        return float(x), float(y), alt

    def _truecolor(self, rgb: Optional[Color]):
        if rgb is None:
            return None
        try:
            color = self.acad.GetInterfaceObject("AutoCAD.AcCmColor")
            color.SetRGB(int(rgb[0]), int(rgb[1]), int(rgb[2]))
            return color
        except Exception:
            return None

    def _ensure_layer(self, name: str, rgb: Optional[Color]) -> str:
        lname = safe_layer_name(name)
        try:
            layer = self.doc.Layers.Item(lname)
        except Exception:
            layer = self.doc.Layers.Add(lname)
        tc = self._truecolor(rgb)
        if tc is not None:
            try:
                layer.TrueColor = tc
            except Exception:
                pass
        return lname

    def _apply_common(self, obj, feature: GEFeature, layer_name: str) -> None:
        try:
            obj.Layer = layer_name
        except Exception:
            pass
        tc = self._truecolor(feature.color)
        if tc is not None:
            try:
                obj.TrueColor = tc
            except Exception:
                pass
        try:
            obj.Hyperlinks.Add("Google Earth Style", feature.style_url)
        except Exception:
            pass

    def import_file(self, path: str | Path) -> Tuple[int, int]:
        reader = GoogleEarthKmlReader(path)
        ok = 0
        fail = 0
        for f in reader.features():
            try:
                self._create_feature(f)
                ok += 1
            except Exception as exc:
                fail += 1
                self.log(f"Lỗi nhập {f.name}: {exc}")
        try:
            self.doc.Regen(1)
        except Exception:
            pass
        return ok, fail

    def _create_feature(self, feature: GEFeature) -> None:
        layer_name = self._ensure_layer(feature.folder or "GoogleEarth", feature.color)
        pts = [self._to_dwg(p) for p in feature.coords]
        ms = self.doc.ModelSpace
        if feature.geom_type == "Point":
            obj = ms.AddPoint(pts[0])
            self._apply_common(obj, feature, layer_name)
            try:
                txt = ms.AddText(feature.name, pts[0], 2.5)
                self._apply_common(txt, feature, layer_name)
            except Exception:
                pass
            return
        flat = []
        for x, y, _z in pts:
            flat.extend([x, y])
        if feature.geom_type == "Polygon":
            if pts[0][:2] != pts[-1][:2]:
                x, y, _z = pts[0]
                flat.extend([x, y])
            obj = ms.AddLightWeightPolyline(tuple(flat))
            try:
                obj.Closed = True
            except Exception:
                pass
        else:
            obj = ms.AddLightWeightPolyline(tuple(flat))
        self._apply_common(obj, feature, layer_name)

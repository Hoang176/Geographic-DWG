# -*- coding: utf-8 -*-
"""Geographic.py - AutoCAD geographic tool prototype.

Current scope:
- Main floating UI at bottom-right of screen.
- Coordinate-system selector similar to the provided reference UI.
- Loads Google Earth WGS84 first.
- Reads VN2000.dty from the application folder.
- Supports the binary VN2000.dty structure found in the supplied file.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import struct
import sys
import time
import tkinter as tk
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

APP_NAME = "Geographic"
WINDOW_WIDTH = 640
WINDOW_HEIGHT = 300
WINDOW_MARGIN_X = 18
WINDOW_MARGIN_Y = 12
KML_NS = "http://www.opengis.net/kml/2.2"
DWG_CRS_KEY_PROP = "Geographic.CRSKey"
DWG_CRS_DATA_PROP = "Geographic.CRSData"


ACI_COLORS: Dict[int, Tuple[int, int, int]] = {
    0: (255, 255, 255),
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


def decdeg_to_dms(value: float, axis: str) -> str:
    if value is None or not math.isfinite(value):
        return ""
    hemi = "E" if axis == "lon" and value >= 0 else "W" if axis == "lon" else "N" if value >= 0 else "S"
    v = abs(float(value))
    deg = int(v)
    m_float = (v - deg) * 60.0
    minute = int(m_float)
    sec = (m_float - minute) * 60.0
    return f"{deg:02d}°{minute:02d}'{sec:07.4f}\"{hemi}"


def safe_key(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_") or "CRS"


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def angle_to_decimal(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("Â°", "°")
    hemi = text[-1:].upper() if text else ""
    values = re.findall(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not values:
        return default
    deg = parse_float(values[0], default)
    minute = parse_float(values[1], 0.0) if len(values) > 1 else 0.0
    second = parse_float(values[2], 0.0) if len(values) > 2 else 0.0
    sign = -1.0 if deg < 0 or hemi in ("W", "S") else 1.0
    return sign * (abs(deg) + minute / 60.0 + second / 3600.0)


def kml_tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def kml_color(rgb: Tuple[int, int, int], alpha: int = 255) -> str:
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    alpha = max(0, min(255, int(alpha)))
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def distance_2d(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def screen_work_area(root: tk.Tk) -> Tuple[int, int, int, int]:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            spi_get_work_area = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(spi_get_work_area, 0, ctypes.byref(rect), 0):
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except Exception:
            pass
    return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())


@dataclass
class CoordinateSystem:
    key: str
    name: str
    description: str = ""
    group: str = "VN2000"
    projection: str = "Transverse Mercator"
    source: str = "VN2000.dty"
    units: str = "Meter"
    central_meridian: str = ""
    origin_latitude: str = "00°00'00.0000\"N"
    scale_reduction: str = "0.9999"
    false_easting: str = "500000"
    false_northing: str = "0"
    quadrant: str = "Positive X and Y"
    minimum_longitude: str = ""
    maximum_longitude: str = ""
    minimum_latitude: str = ""
    maximum_latitude: str = ""
    datum_name: str = "VN2000"
    datum_description: str = "05_2007_QD-BTNMT"
    conversion_method: str = "Seven Parameter Transformation"
    delta_x: str = "-191.90441429"
    delta_y: str = "-39.30318279"
    delta_z: str = "-111.45032835"
    x_rotation: str = "-0.00928836"
    y_rotation: str = "0.01975479"
    z_rotation: str = "-0.00427372"
    scale: str = "1.0000002529062779"
    ellipsoid_name: str = "WGS84"
    ellipsoid_description: str = "World Geodetic System of 1984"
    equatorial_radius: str = "6378137"
    polar_radius: str = "6356752.3142"
    eccentricity: str = "0.081819190928906743"
    raw: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def google_earth() -> "CoordinateSystem":
        return CoordinateSystem(
            key="GOOGLE_EARTH_WGS84",
            name="Google Earth - WGS84",
            description="Google Earth default geographic coordinate system",
            group="Google Earth",
            projection="Geographic Latitude/Longitude",
            source="Built-in",
            units="Degree",
            central_meridian="00°00'00.0000\"E",
            scale_reduction="1.0",
            false_easting="0",
            false_northing="0",
            datum_name="WGS84",
            datum_description="World Geodetic System of 1984",
            conversion_method="None",
            delta_x="0", delta_y="0", delta_z="0",
            x_rotation="0", y_rotation="0", z_rotation="0", scale="1.0",
        )


class CoordinateTransformer:
    """Transforms drawing XY coordinates from the selected CRS to WGS84 lon/lat."""

    def __init__(self, cs: CoordinateSystem):
        self.cs = cs
        self.a = parse_float(cs.equatorial_radius, 6378137.0)
        self.b = parse_float(cs.polar_radius, 6356752.3142)
        self.e2 = max(0.0, 1.0 - (self.b * self.b) / (self.a * self.a))
        self.ep2 = (self.a * self.a - self.b * self.b) / (self.b * self.b)
        self.k0 = parse_float(cs.scale_reduction, 1.0) or 1.0
        self.false_easting = parse_float(cs.false_easting, 0.0)
        self.false_northing = parse_float(cs.false_northing, 0.0)
        cm_value = cs.raw.get("central_meridian_decimal") if cs.raw else ""
        self.lon0 = math.radians(angle_to_decimal(cm_value or cs.central_meridian, 0.0))
        self.lat0 = math.radians(angle_to_decimal(cs.origin_latitude, 0.0))
        self.m0 = self._meridional_arc(self.lat0)
        units = (cs.units or "").lower()
        projection = (cs.projection or "").lower()
        group = (cs.group or "").lower()
        self.is_geographic = units.startswith("degree") or "geographic" in projection or group == "google earth"

    def to_wgs84(self, point: Sequence[float]) -> Tuple[float, float, float]:
        x = float(point[0])
        y = float(point[1])
        z = float(point[2]) if len(point) > 2 else 0.0
        if self.is_geographic:
            return x, y, z
        lat, lon = self._inverse_transverse_mercator(x, y)
        if self._has_datum_shift():
            lat, lon, z = self._datum_to_wgs84(lat, lon, z)
        return math.degrees(lon), math.degrees(lat), z

    def from_wgs84(self, lon: float, lat: float, altitude: float = 0.0) -> Tuple[float, float, float]:
        if self.is_geographic:
            return float(lon), float(lat), float(altitude)
        lat_rad = math.radians(float(lat))
        lon_rad = math.radians(float(lon))
        z = float(altitude)
        if self._has_datum_shift():
            lat_rad, lon_rad, z = self._wgs84_to_datum(lat_rad, lon_rad, z)
        x, y = self._forward_transverse_mercator(lat_rad, lon_rad)
        return x, y, z

    def _forward_transverse_mercator(self, lat: float, lon: float) -> Tuple[float, float]:
        sin_lat = math.sin(lat)
        cos_lat = math.cos(lat)
        tan_lat = math.tan(lat)
        n = self.a / math.sqrt(1.0 - self.e2 * sin_lat * sin_lat)
        t = tan_lat * tan_lat
        c = self.ep2 * cos_lat * cos_lat
        a = (lon - self.lon0) * cos_lat
        m = self._meridional_arc(lat)
        x = self.false_easting + self.k0 * n * (
            a
            + (1.0 - t + c) * a ** 3 / 6.0
            + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * self.ep2) * a ** 5 / 120.0
        )
        y = self.false_northing + self.k0 * (
            m
            - self.m0
            + n * tan_lat * (
                a * a / 2.0
                + (5.0 - t + 9.0 * c + 4.0 * c * c) * a ** 4 / 24.0
                + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * self.ep2) * a ** 6 / 720.0
            )
        )
        return x, y

    def _inverse_transverse_mercator(self, easting: float, northing: float) -> Tuple[float, float]:
        e4 = self.e2 * self.e2
        e6 = e4 * self.e2
        m = self.m0 + (northing - self.false_northing) / self.k0
        mu = m / (self.a * (1.0 - self.e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0))
        e1 = (1.0 - math.sqrt(1.0 - self.e2)) / (1.0 + math.sqrt(1.0 - self.e2))
        phi1 = (
            mu
            + (3.0 * e1 / 2.0 - 27.0 * e1 ** 3 / 32.0) * math.sin(2.0 * mu)
            + (21.0 * e1 * e1 / 16.0 - 55.0 * e1 ** 4 / 32.0) * math.sin(4.0 * mu)
            + (151.0 * e1 ** 3 / 96.0) * math.sin(6.0 * mu)
            + (1097.0 * e1 ** 4 / 512.0) * math.sin(8.0 * mu)
        )
        sin_phi = math.sin(phi1)
        cos_phi = math.cos(phi1)
        tan_phi = math.tan(phi1)
        n1 = self.a / math.sqrt(1.0 - self.e2 * sin_phi * sin_phi)
        r1 = self.a * (1.0 - self.e2) / ((1.0 - self.e2 * sin_phi * sin_phi) ** 1.5)
        t1 = tan_phi * tan_phi
        c1 = self.ep2 * cos_phi * cos_phi
        d = (easting - self.false_easting) / (n1 * self.k0)

        lat = phi1 - (n1 * tan_phi / r1) * (
            d * d / 2.0
            - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 * c1 - 9.0 * self.ep2) * d ** 4 / 24.0
            + (
                61.0
                + 90.0 * t1
                + 298.0 * c1
                + 45.0 * t1 * t1
                - 252.0 * self.ep2
                - 3.0 * c1 * c1
            )
            * d ** 6
            / 720.0
        )
        lon = self.lon0 + (
            d
            - (1.0 + 2.0 * t1 + c1) * d ** 3 / 6.0
            + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 * c1 + 8.0 * self.ep2 + 24.0 * t1 * t1)
            * d ** 5
            / 120.0
        ) / max(1e-15, cos_phi)
        return lat, lon

    def _meridional_arc(self, lat: float) -> float:
        e4 = self.e2 * self.e2
        e6 = e4 * self.e2
        return self.a * (
            (1.0 - self.e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * lat
            - (3.0 * self.e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0) * math.sin(2.0 * lat)
            + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * math.sin(4.0 * lat)
            - (35.0 * e6 / 3072.0) * math.sin(6.0 * lat)
        )

    def _has_datum_shift(self) -> bool:
        values = (
            self.cs.delta_x,
            self.cs.delta_y,
            self.cs.delta_z,
            self.cs.x_rotation,
            self.cs.y_rotation,
            self.cs.z_rotation,
        )
        if any(abs(parse_float(value, 0.0)) > 1e-12 for value in values):
            return True
        return abs(self._helmert_scale_delta()) > 1e-12

    def _datum_to_wgs84(self, lat: float, lon: float, height: float) -> Tuple[float, float, float]:
        x, y, z = self._geodetic_to_ecef(lat, lon, height)
        dx = parse_float(self.cs.delta_x, 0.0)
        dy = parse_float(self.cs.delta_y, 0.0)
        dz = parse_float(self.cs.delta_z, 0.0)
        rx = math.radians(parse_float(self.cs.x_rotation, 0.0) / 3600.0)
        ry = math.radians(parse_float(self.cs.y_rotation, 0.0) / 3600.0)
        rz = math.radians(parse_float(self.cs.z_rotation, 0.0) / 3600.0)
        scale = 1.0 + self._helmert_scale_delta()
        x2 = dx + scale * x - rz * y + ry * z
        y2 = dy + rz * x + scale * y - rx * z
        z2 = dz - ry * x + rx * y + scale * z
        return self._ecef_to_geodetic(x2, y2, z2)

    def _wgs84_to_datum(self, lat: float, lon: float, height: float) -> Tuple[float, float, float]:
        x, y, z = self._geodetic_to_ecef(lat, lon, height)
        dx = parse_float(self.cs.delta_x, 0.0)
        dy = parse_float(self.cs.delta_y, 0.0)
        dz = parse_float(self.cs.delta_z, 0.0)
        rx = math.radians(parse_float(self.cs.x_rotation, 0.0) / 3600.0)
        ry = math.radians(parse_float(self.cs.y_rotation, 0.0) / 3600.0)
        rz = math.radians(parse_float(self.cs.z_rotation, 0.0) / 3600.0)
        scale = 1.0 + self._helmert_scale_delta()
        tx = x - dx
        ty = y - dy
        tz = z - dz
        x1 = (tx + rz * ty - ry * tz) / scale
        y1 = (-rz * tx + ty + rx * tz) / scale
        z1 = (ry * tx - rx * ty + tz) / scale
        return self._ecef_to_geodetic(x1, y1, z1)

    def _helmert_scale_delta(self) -> float:
        value = parse_float(self.cs.scale, 1.0)
        if 0.5 <= value <= 1.5:
            return value - 1.0
        return value * 1e-6

    def _geodetic_to_ecef(self, lat: float, lon: float, height: float) -> Tuple[float, float, float]:
        sin_lat = math.sin(lat)
        cos_lat = math.cos(lat)
        n = self.a / math.sqrt(1.0 - self.e2 * sin_lat * sin_lat)
        x = (n + height) * cos_lat * math.cos(lon)
        y = (n + height) * cos_lat * math.sin(lon)
        z = (n * (1.0 - self.e2) + height) * sin_lat
        return x, y, z

    def _ecef_to_geodetic(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        lon = math.atan2(y, x)
        p = math.hypot(x, y)
        lat = math.atan2(z, p * (1.0 - self.e2))
        height = 0.0
        for _ in range(8):
            sin_lat = math.sin(lat)
            n = self.a / math.sqrt(1.0 - self.e2 * sin_lat * sin_lat)
            height = p / max(1e-15, math.cos(lat)) - n
            lat = math.atan2(z, p * (1.0 - self.e2 * n / (n + height)))
        return lat, lon, height


class VN2000BinaryParser:
    """Reader for the supplied binary VN2000.dty.

    Observed structure:
    - uint32 at header offset 12 points to CRS text area, e.g. 0x16460.
    - The full record starts 0x50 bytes before that pointer.
    - Record size is 728 bytes.
    - The text area is encoded by differential XOR:
        plain[i] = encoded[i] XOR plain[i-1]
      with a per-record seed. The seed is inferred from the known fixed
      text 'VN2000' at offset 24 in the text area.
    - After decoding the text area, doubles are plain little-endian values.
    """

    RECORD_SIZE = 728
    TEXT_OFFSET = 0x50
    TEXT_VN2000_POS = 24

    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()

    def parse(self) -> List[CoordinateSystem]:
        start = self._record_start()
        if start is None:
            return []
        result: List[CoordinateSystem] = []
        count = max(0, (len(self.data) - start) // self.RECORD_SIZE)
        for index in range(count):
            rec_offset = start + index * self.RECORD_SIZE
            rec = self.data[rec_offset:rec_offset + self.RECORD_SIZE]
            cs = self._parse_record(rec, index, rec_offset)
            if cs:
                result.append(cs)
        return result

    def _record_start(self) -> Optional[int]:
        if len(self.data) < 16:
            return None
        crs_text_offset = struct.unpack_from("<I", self.data, 12)[0]
        start = crs_text_offset - self.TEXT_OFFSET
        if 0 <= start < len(self.data):
            return start
        return None

    def _seed_for_known_plain(self, enc: bytes, pos: int, plain_byte: int) -> int:
        acc = 0
        for i in range(pos + 1):
            acc ^= enc[i]
        return acc ^ plain_byte

    def _decode_delta_xor(self, enc: bytes, seed: int) -> bytes:
        out = bytearray()
        prev = seed
        for value in enc:
            char = value ^ prev
            out.append(char)
            prev = char
        return bytes(out)

    def _infer_seed(self, enc: bytes) -> Optional[int]:
        if len(enc) > self.TEXT_VN2000_POS + 5:
            seed = self._seed_for_known_plain(enc, self.TEXT_VN2000_POS, ord("V"))
            check = self._decode_delta_xor(enc[:80], seed)
            if b"VN2000" in check or b"WGS84" in check:
                return seed
        best_seed = None
        best_score = -999999
        for seed in range(256):
            txt = self._decode_delta_xor(enc[:140], seed)
            score = 0
            for token in (b"VN2000", b"WGS84", b"TM", b"ASIA"):
                if token in txt:
                    score += 50
            score += sum((65 <= c <= 90) or (97 <= c <= 122) or (48 <= c <= 57) or c in (0, 32, 45, 95) for c in txt)
            score -= sum((c < 32 and c != 0) or c > 126 for c in txt) * 5
            if score > best_score:
                best_score = score
                best_seed = seed
        return best_seed if best_score > 20 else None

    def _parts(self, plain: bytes) -> List[str]:
        parts = []
        for chunk in plain[:160].split(b"\x00"):
            if not chunk:
                continue
            text = chunk.decode("cp1258", errors="ignore").strip(" \x00\x01")
            if text:
                parts.append(text)
        return parts

    def _known_part(self, parts: List[str], names: List[str]) -> str:
        names_set = set(names)
        for part in parts:
            if part in names_set:
                return part
        return ""

    def _looks_like_vn2000_name(self, name: str) -> bool:
        if len(name) < 3 or len(name) > 40:
            return False
        if name.startswith("User-OSGB"):
            return False
        return bool(re.match(r"^[0-9A-Za-z_]+$", name))

    def _display_name(self, raw: str) -> str:
        return raw

    def _extract_zone(self, parts: List[str]) -> str:
        for part in parts:
            if "106" in part or "TM" in part or "NE" in part:
                return part
        return ""

    def _parse_record(self, rec: bytes, index: int, rec_offset: int) -> Optional[CoordinateSystem]:
        if len(rec) < self.RECORD_SIZE:
            return None
        enc = rec[self.TEXT_OFFSET:]
        seed = self._infer_seed(enc)
        if seed is None:
            return None
        plain = self._decode_delta_xor(enc, seed)
        parts = self._parts(plain)
        if not parts or not self._looks_like_vn2000_name(parts[0]):
            return None
        datum = self._known_part(parts, ["VN2000", "WGS84"]) or "VN2000"
        projection = self._known_part(parts, ["TM", "LL", "UTM"]) or "TM"
        try:
            cm = struct.unpack_from("<d", plain, 0x0D8)[0]
            false_e = struct.unpack_from("<d", plain, 0x1A8)[0]
            false_n = struct.unpack_from("<d", plain, 0x1B0)[0]
            scale_red = struct.unpack_from("<d", plain, 0x1B8)[0]
            min_lon = struct.unpack_from("<d", plain, 0x208)[0]
            min_lat = struct.unpack_from("<d", plain, 0x210)[0]
            max_lon = struct.unpack_from("<d", plain, 0x218)[0]
            max_lat = struct.unpack_from("<d", plain, 0x220)[0]
        except Exception:
            return None
        if not (90.0 <= cm <= 130.0 and 0.9 <= scale_red <= 1.1 and 1 <= false_e <= 10000000):
            return None
        display = self._display_name(parts[0])
        zone = self._extract_zone(parts)
        return CoordinateSystem(
            key=f"VN2000_{safe_key(display).upper()}_{index}",
            name=f"{display} - {display} (VN2000)",
            description=f"{display} (VN2000)" + (f" - {zone}" if zone else ""),
            group="VN2000",
            projection="Transverse Mercator" if projection == "TM" else projection,
            source=self.path.name,
            units="Meter",
            central_meridian=decdeg_to_dms(cm, "lon"),
            origin_latitude="00°00'00.0000\"N",
            scale_reduction=f"{scale_red:.10g}",
            false_easting=f"{false_e:.0f}",
            false_northing=f"{false_n:.0f}",
            minimum_longitude=decdeg_to_dms(min_lon, "lon"),
            maximum_longitude=decdeg_to_dms(max_lon, "lon"),
            minimum_latitude=decdeg_to_dms(min_lat, "lat"),
            maximum_latitude=decdeg_to_dms(max_lat, "lat"),
            datum_name=datum,
            datum_description="05_2007_QD-BTNMT" if datum == "VN2000" else "World Geodetic System of 1984",
            conversion_method="Seven Parameter Transformation" if datum == "VN2000" else "None",
            raw={
                "record_index": str(index),
                "record_offset": hex(rec_offset),
                "decode_seed": hex(seed),
                "raw_parts": repr(parts),
                "central_meridian_decimal": str(cm),
            },
        )


class CoordinateSystemLibrary:
    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.dty_path = app_dir / "VN2000.dty"
        self.favorite_path = app_dir / "favorites_crs.json"
        self.items: Dict[str, CoordinateSystem] = {}
        self.favorites: List[str] = []
        self.load()

    def load(self) -> None:
        self.items.clear()
        ge = CoordinateSystem.google_earth()
        self.items[ge.key] = ge
        if self.dty_path.exists():
            for item in self._load_vn2000_file(self.dty_path):
                self.items[item.key] = item
        else:
            for item in self._builtin_examples():
                self.items[item.key] = item
        self.favorites = self._load_favorites()

    def _load_vn2000_file(self, path: Path) -> List[CoordinateSystem]:
        data = path.read_bytes()
        if b"\x00" in data[:512]:
            items = VN2000BinaryParser(path).parse()
            if items:
                return items
        text = self._read_text_any_encoding(path)
        for loader in (self._parse_json, self._parse_csv, self._parse_key_value_blocks):
            try:
                items = loader(text)
                if items:
                    return items
            except Exception:
                pass
        return []

    def _load_favorites(self) -> List[str]:
        if not self.favorite_path.exists():
            return []
        try:
            data = json.loads(self.favorite_path.read_text(encoding="utf-8"))
            return [key for key in data if key in self.items]
        except Exception:
            return []

    def add_favorite(self, key: str) -> None:
        if key in self.items and key not in self.favorites:
            self.favorites.append(key)
            self.favorite_path.write_text(json.dumps(self.favorites, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_text_any_encoding(self, path: Path) -> str:
        data = path.read_bytes()
        for enc in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    def _parse_json(self, text: str) -> List[CoordinateSystem]:
        data = json.loads(text)
        rows = data.get("coordinate_systems") if isinstance(data, dict) else data
        return [self._row_to_cs(row) for row in rows if isinstance(row, dict)]

    def _parse_csv(self, text: str) -> List[CoordinateSystem]:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t|")
        return [self._row_to_cs(row) for row in csv.DictReader(io.StringIO(text), dialect=dialect) if row]

    def _parse_key_value_blocks(self, text: str) -> List[CoordinateSystem]:
        items = []
        for block in re.split(r"\n\s*\n|\n\s*-{3,}\s*\n", text):
            row = {}
            for line in block.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    row[k.strip()] = v.strip()
                elif ":" in line:
                    k, v = line.split(":", 1)
                    row[k.strip()] = v.strip()
            if row:
                items.append(self._row_to_cs(row))
        return items

    def _row_to_cs(self, row: Dict[str, object]) -> CoordinateSystem:
        def get(*names: str, default: str = "") -> str:
            lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
            for name in names:
                key = name.lower().replace(" ", "_")
                if key in lowered and lowered[key] is not None:
                    return str(lowered[key]).strip()
            return default
        name = get("Name", "Ten", default="VN2000")
        return CoordinateSystem(
            key=get("Key", "ID", default=safe_key(name)),
            name=name,
            description=get("Description", "Mo ta", default=name),
            group=get("Group", default="VN2000"),
            central_meridian=get("Central Meridian", "Kinh tuyen truc"),
        )

    def _builtin_examples(self) -> List[CoordinateSystem]:
        return [
            CoordinateSystem(key="VN2000_CAMAU", name="CaMau - Ca Mau (VN2000)", description="Ca Mau (VN2000)", central_meridian="104°30'00.0000\"E"),
            CoordinateSystem(key="VN2000_BACKAN", name="BacKan - Bac Kan (VN2000)", description="Bac Kan (VN2000)", central_meridian="106°30'00.0000\"E"),
        ]


@dataclass
class CadKmlFeature:
    name: str
    layer: str
    geometry_type: str
    coordinates: List[Tuple[float, float, float]]
    attributes: Dict[str, str]
    rgb: Tuple[int, int, int]
    line_width: float
    fill_alpha: int = 0
    icon_scale: float = 0.65
    inner_boundaries: List[List[Tuple[float, float, float]]] = field(default_factory=list)


@dataclass
class KmlExportResult:
    output_path: Path
    feature_count: int
    skipped_count: int
    layer_count: int
    skipped_by_type: Dict[str, int] = field(default_factory=dict)


@dataclass
class KmlImportResult:
    entity_count: int
    placemark_count: int
    skipped_count: int


def default_downloads_folder() -> Path:
    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            downloads_id = "{374DE290-123F-4565-9164-39C4925E467B}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, downloads_id)
            path = Path(os.path.expandvars(str(value)))
            if path.parent.exists():
                return path
        except Exception:
            pass
    return Path.home() / "Downloads"


def safe_filename_stem(name: str) -> str:
    stem = Path(name or "Drawing").stem or "Drawing"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" .") or "Drawing"


class AutoCADKmlExporter:
    def __init__(self, doc: Any, cs: CoordinateSystem, entities: Optional[Iterable[Any]] = None):
        self.doc = doc
        self.cs = cs
        self.transformer = CoordinateTransformer(cs)
        self.entities = list(entities) if entities is not None else None
        self.layer_cache: Dict[str, Any] = {}
        self.skipped_by_type: Dict[str, int] = {}
        self.skipped_count = 0

    def export_kmz(self, output_path: Path) -> KmlExportResult:
        features = self.collect_features()
        if not features:
            raise RuntimeError("Không có đối tượng hợp lệ để xuất sang KML/KMZ.")
        kml_bytes = self.build_kml(features)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as kmz:
            kmz.writestr("doc.kml", kml_bytes)
        return KmlExportResult(
            output_path=output_path,
            feature_count=len(features),
            skipped_count=self.skipped_count,
            layer_count=len({feature.layer for feature in features}),
            skipped_by_type=dict(self.skipped_by_type),
        )

    def collect_features(self) -> List[CadKmlFeature]:
        features: List[CadKmlFeature] = []
        source_entities = self.entities if self.entities is not None else self._iter_model_space()
        for entity in source_entities:
            object_name = self._str_prop(entity, "ObjectName", type(entity).__name__)
            try:
                entity_features = self._features_from_entity(entity)
                if entity_features:
                    features.extend(entity_features)
                else:
                    self._skip(object_name)
            except Exception:
                self._skip(object_name)
        return features

    def build_kml(self, features: List[CadKmlFeature]) -> bytes:
        ET.register_namespace("", KML_NS)
        root = ET.Element(kml_tag("kml"))
        doc_el = ET.SubElement(root, kml_tag("Document"))
        doc_name = self._str_prop(self.doc, "Name", "Drawing")
        ET.SubElement(doc_el, kml_tag("name")).text = Path(doc_name).stem
        ET.SubElement(doc_el, kml_tag("description")).text = (
            f"Exported from AutoCAD by {APP_NAME}. Source CRS: {self.cs.name}"
        )

        style_ids: Dict[Tuple[Tuple[int, int, int], float, int, str, float], str] = {}
        for feature in features:
            key = (
                feature.rgb,
                round(feature.line_width, 2),
                feature.fill_alpha,
                feature.geometry_type,
                round(feature.icon_scale, 2),
            )
            if key not in style_ids:
                style_ids[key] = f"cad_style_{len(style_ids) + 1}"
                self._add_style(doc_el, style_ids[key], feature.rgb, feature.line_width, feature.fill_alpha, feature.icon_scale)

        by_layer: Dict[str, List[CadKmlFeature]] = {}
        for feature in features:
            by_layer.setdefault(feature.layer or "0", []).append(feature)

        for layer in sorted(by_layer, key=lambda value: value.lower()):
            folder = ET.SubElement(doc_el, kml_tag("Folder"))
            ET.SubElement(folder, kml_tag("name")).text = layer
            for feature in by_layer[layer]:
                key = (
                    feature.rgb,
                    round(feature.line_width, 2),
                    feature.fill_alpha,
                    feature.geometry_type,
                    round(feature.icon_scale, 2),
                )
                self._add_placemark(folder, feature, style_ids[key])

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _iter_model_space(self) -> Iterable[Any]:
        model_space = self._prop(self.doc, "ModelSpace")
        if model_space is None:
            return []
        try:
            return iter(model_space)
        except Exception:
            pass

        def by_index() -> Iterable[Any]:
            count = int(self._prop(model_space, "Count", 0) or 0)
            for index in range(count):
                yield model_space.Item(index)

        return by_index()

    def _features_from_entity(self, entity: Any) -> List[CadKmlFeature]:
        object_name = self._str_prop(entity, "ObjectName", "").lower()
        if "hatch" in object_name:
            return self._hatch_features(entity)
        feature: Optional[CadKmlFeature] = None
        if "polyline" in object_name:
            feature = self._polyline_feature(entity)
        elif object_name.endswith("line"):
            feature = self._line_feature(entity)
        elif "circle" in object_name:
            feature = self._circle_feature(entity)
        elif "arc" in object_name:
            feature = self._arc_feature(entity)
        elif "ellipse" in object_name:
            feature = self._ellipse_feature(entity)
        elif "spline" in object_name:
            feature = self._spline_feature(entity)
        elif object_name.endswith("point"):
            feature = self._point_feature(entity)
        elif "text" in object_name:
            feature = self._text_feature(entity)
        elif "blockreference" in object_name:
            feature = self._block_feature(entity)
        elif "3dface" in object_name or object_name.endswith("solid") or "trace" in object_name:
            feature = self._coordinate_polygon_feature(entity)
        return [feature] if feature else []

    def _line_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        start = self._point_tuple(self._prop(entity, "StartPoint"))
        end = self._point_tuple(self._prop(entity, "EndPoint"))
        if not start or not end:
            return None
        coords = self._transform_points([start, end])
        if len(coords) < 2:
            return None
        return self._make_feature(entity, "LineString", coords, "Line")

    def _polyline_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        points = self._polyline_points(entity)
        if len(points) < 2:
            return None
        closed = bool(self._prop(entity, "Closed", False))
        coords = self._transform_points(points)
        if len(coords) < 2:
            return None
        if closed and len(coords) >= 3:
            coords = self._closed_ring(coords)
            return self._make_feature(entity, "Polygon", coords, "Polyline", fill_alpha=55)
        return self._make_feature(entity, "LineString", coords, "Polyline")

    def _circle_points(self, entity: Any) -> List[Tuple[float, float, float]]:
        center = self._point_tuple(self._prop(entity, "Center"))
        radius = parse_float(self._prop(entity, "Radius"), 0.0)
        if not center or radius <= 0:
            return []
        points = []
        segments = 96
        for index in range(segments + 1):
            angle = 2.0 * math.pi * index / segments
            points.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle), center[2]))
        return points

    def _circle_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        points = self._circle_points(entity)
        if not points:
            return None
        coords = self._transform_points(points)
        if len(coords) < 4:
            return None
        return self._make_feature(entity, "Polygon", self._closed_ring(coords), "Circle", fill_alpha=35)

    def _arc_points(self, entity: Any) -> List[Tuple[float, float, float]]:
        center = self._point_tuple(self._prop(entity, "Center"))
        radius = parse_float(self._prop(entity, "Radius"), 0.0)
        start = parse_float(self._prop(entity, "StartAngle"), 0.0)
        end = parse_float(self._prop(entity, "EndAngle"), 0.0)
        if not center or radius <= 0:
            return []
        while end <= start:
            end += 2.0 * math.pi
        sweep = end - start
        segments = max(8, min(96, int(abs(sweep) / (math.pi / 36.0)) + 1))
        points = []
        for index in range(segments + 1):
            angle = start + sweep * index / segments
            points.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle), center[2]))
        return points

    def _arc_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        points = self._arc_points(entity)
        if not points:
            return None
        coords = self._transform_points(points)
        if len(coords) < 2:
            return None
        return self._make_feature(entity, "LineString", coords, "Arc")

    def _ellipse_points(self, entity: Any) -> Tuple[List[Tuple[float, float, float]], bool]:
        center = self._point_tuple(self._prop(entity, "Center"))
        major = self._point_tuple(self._prop(entity, "MajorAxis"))
        ratio = parse_float(self._prop(entity, "RadiusRatio"), 0.0)
        if not center or not major or ratio <= 0:
            return [], False
        start = parse_float(self._prop(entity, "StartParameter"), 0.0)
        end = parse_float(self._prop(entity, "EndParameter"), 2.0 * math.pi)
        while end <= start:
            end += 2.0 * math.pi
        sweep = end - start
        major_len = math.hypot(major[0], major[1])
        if major_len <= 0:
            return [], False
        minor = (-major[1] * ratio, major[0] * ratio, 0.0)
        segments = max(24, min(144, int(abs(sweep) / (math.pi / 36.0)) + 1))
        points = []
        for index in range(segments + 1):
            angle = start + sweep * index / segments
            points.append((
                center[0] + major[0] * math.cos(angle) + minor[0] * math.sin(angle),
                center[1] + major[1] * math.cos(angle) + minor[1] * math.sin(angle),
                center[2] + major[2] * math.cos(angle),
            ))
        return points, abs(sweep - 2.0 * math.pi) < 1e-6

    def _ellipse_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        points, is_closed = self._ellipse_points(entity)
        if not points:
            return None
        coords = self._transform_points(points)
        if len(coords) < 2:
            return None
        if is_closed and len(coords) >= 4:
            return self._make_feature(entity, "Polygon", self._closed_ring(coords), "Ellipse", fill_alpha=35)
        return self._make_feature(entity, "LineString", coords, "Ellipse")

    def _spline_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        for prop_name in ("FitPoints", "ControlPoints", "Coordinates"):
            points = self._points_from_flat(self._prop(entity, prop_name), 3)
            if len(points) >= 2:
                coords = self._transform_points(points)
                if len(coords) >= 2:
                    return self._make_feature(entity, "LineString", coords, "Spline")
        return None

    def _point_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        point = self._point_tuple(self._prop(entity, "Coordinates")) or self._point_tuple(self._prop(entity, "Position"))
        if not point:
            return None
        coords = self._transform_points([point])
        if not coords:
            return None
        return self._make_feature(entity, "Point", coords, "Point")

    def _text_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        point = self._point_tuple(self._prop(entity, "InsertionPoint")) or self._point_tuple(self._prop(entity, "TextAlignmentPoint"))
        if not point:
            return None
        coords = self._transform_points([point])
        if not coords:
            return None
        text = self._str_prop(entity, "TextString", "") or self._str_prop(entity, "Contents", "")
        return self._make_feature(entity, "Point", coords, "Text", name=text[:80] if text else None, icon_scale=0.0)

    def _block_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        point = self._point_tuple(self._prop(entity, "InsertionPoint"))
        if not point:
            return None
        coords = self._transform_points([point])
        if not coords:
            return None
        block_name = self._str_prop(entity, "EffectiveName", "") or self._str_prop(entity, "Name", "")
        return self._make_feature(entity, "Point", coords, "Block", name=block_name or None)

    def _coordinate_polygon_feature(self, entity: Any) -> Optional[CadKmlFeature]:
        points = self._points_from_flat(self._prop(entity, "Coordinates"), 3)
        if len(points) < 3:
            points = self._points_from_flat(self._prop(entity, "Coordinates"), 2)
        if len(points) < 3:
            return None
        coords = self._transform_points(points)
        if len(coords) < 3:
            return None
        return self._make_feature(entity, "Polygon", self._closed_ring(coords), "Face", fill_alpha=55)

    def _hatch_features(self, entity: Any) -> List[CadKmlFeature]:
        ring = self._hatch_outer_ring(entity)
        if not ring:
            return []
        outer = self._transform_points(ring)
        if len(outer) < 4:
            return []
        feature = self._make_feature(
            entity,
            "Polygon",
            self._closed_ring(outer),
            "Hatch",
            fill_alpha=128,
        )
        return [feature]

    def _hatch_outer_ring(self, entity: Any) -> List[Tuple[float, float, float]]:
        loops = self._hatch_loop_rings(entity)
        if loops:
            return loops[0]
        return self._bounding_box_ring(entity)

    def _hatch_loop_rings(self, entity: Any) -> List[List[Tuple[float, float, float]]]:
        raw_count = self._prop(entity, "NumberOfLoops")
        try:
            count = int(raw_count() if callable(raw_count) else raw_count or 0)
        except Exception:
            count = 0
        rings: List[List[Tuple[float, float, float]]] = []
        for index in range(count):
            loop_objects = self._hatch_loop_objects(entity, index)
            ring = self._boundary_ring_points(loop_objects)
            if len(ring) >= 4:
                rings.append(ring)
        return rings

    def _hatch_loop_objects(self, entity: Any, index: int) -> List[Any]:
        try:
            result = entity.GetLoopAt(index)
            objects = self._loop_objects_from_result(result)
            if objects:
                return objects
        except Exception:
            pass
        try:
            import pythoncom
            import win32com.client

            loop_type = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            loop = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
            entity.GetLoopAt(index, loop_type, loop)
            return self._loop_objects_from_result(loop.value)
        except Exception:
            return []

    def _loop_objects_from_result(self, result: Any) -> List[Any]:
        if result is None:
            return []
        if isinstance(result, tuple) and len(result) >= 2:
            for item in result:
                objects = self._object_list(item)
                if objects and not all(isinstance(obj, (int, float, str, bytes)) for obj in objects):
                    return objects
        objects = self._object_list(result)
        if objects and not all(isinstance(obj, (int, float, str, bytes)) for obj in objects):
            return objects
        return []

    def _boundary_ring_points(self, objects: List[Any]) -> List[Tuple[float, float, float]]:
        ring: List[Tuple[float, float, float]] = []
        for obj in objects:
            segment = self._boundary_object_points(obj)
            if len(segment) < 2:
                continue
            if ring and distance_2d(ring[-1], segment[-1]) < distance_2d(ring[-1], segment[0]):
                segment = list(reversed(segment))
            if ring and distance_2d(ring[-1], segment[0]) < 1e-7:
                ring.extend(segment[1:])
            else:
                ring.extend(segment)
        return self._closed_ring(ring) if len(ring) >= 3 else []

    def _boundary_object_points(self, entity: Any) -> List[Tuple[float, float, float]]:
        object_name = self._str_prop(entity, "ObjectName", "").lower()
        if "polyline" in object_name:
            return self._polyline_points(entity)
        if object_name.endswith("line"):
            start = self._point_tuple(self._prop(entity, "StartPoint"))
            end = self._point_tuple(self._prop(entity, "EndPoint"))
            return [start, end] if start and end else []
        if "circle" in object_name:
            return self._circle_points(entity)
        if "arc" in object_name:
            return self._arc_points(entity)
        if "ellipse" in object_name:
            points, _is_closed = self._ellipse_points(entity)
            return points
        if "spline" in object_name:
            for prop_name in ("FitPoints", "ControlPoints", "Coordinates"):
                points = self._points_from_flat(self._prop(entity, prop_name), 3)
                if len(points) >= 2:
                    return points
        return []

    def _object_list(self, value: Any) -> List[Any]:
        if value is None:
            return []
        if hasattr(value, "value"):
            try:
                value = value.value
            except Exception:
                pass
        if isinstance(value, (list, tuple)):
            return list(value)
        try:
            return list(value)
        except Exception:
            return [value]

    def _bounding_box_ring(self, entity: Any) -> List[Tuple[float, float, float]]:
        try:
            result = entity.GetBoundingBox()
            if isinstance(result, tuple) and len(result) >= 2:
                min_point = self._point_tuple(result[0])
                max_point = self._point_tuple(result[1])
                ring = self._ring_from_bbox_points(min_point, max_point)
                if ring:
                    return ring
        except Exception:
            pass
        try:
            import pythoncom
            import win32com.client

            min_point_var = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
            max_point_var = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
            entity.GetBoundingBox(min_point_var, max_point_var)
            return self._ring_from_bbox_points(
                self._point_tuple(min_point_var.value),
                self._point_tuple(max_point_var.value),
            )
        except Exception:
            return []

    def _ring_from_bbox_points(
        self, min_point: Optional[Tuple[float, float, float]], max_point: Optional[Tuple[float, float, float]]
    ) -> List[Tuple[float, float, float]]:
        if not min_point or not max_point:
            return []
        min_x, min_y, min_z = min_point
        max_x, max_y, max_z = max_point
        if abs(max_x - min_x) < 1e-9 or abs(max_y - min_y) < 1e-9:
            return []
        z = min_z if math.isfinite(min_z) else max_z
        return [
            (min_x, min_y, z),
            (max_x, min_y, z),
            (max_x, max_y, z),
            (min_x, max_y, z),
            (min_x, min_y, z),
        ]

    def _make_feature(
        self,
        entity: Any,
        geometry_type: str,
        coordinates: List[Tuple[float, float, float]],
        prefix: str,
        name: Optional[str] = None,
        fill_alpha: int = 0,
        icon_scale: float = 0.65,
        inner_boundaries: Optional[List[List[Tuple[float, float, float]]]] = None,
    ) -> CadKmlFeature:
        attributes = self._attributes(entity)
        layer = attributes.get("Layer", "0") or "0"
        rgb = self._resolved_rgb(entity, layer)
        attributes["ResolvedRGB"] = f"{rgb[0]},{rgb[1]},{rgb[2]}"
        attributes["SourceCRS"] = self.cs.name
        attributes["KmlGeometry"] = geometry_type
        return CadKmlFeature(
            name=name or self._feature_name(entity, prefix),
            layer=layer,
            geometry_type=geometry_type,
            coordinates=coordinates,
            attributes=attributes,
            rgb=rgb,
            line_width=self._line_width(entity),
            fill_alpha=fill_alpha,
            icon_scale=icon_scale,
            inner_boundaries=inner_boundaries or [],
        )

    def _attributes(self, entity: Any) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        for prop_name in (
            "ObjectName",
            "Handle",
            "Layer",
            "Color",
            "Lineweight",
            "Material",
            "Transparency",
            "Thickness",
            "Elevation",
            "Closed",
            "Length",
            "Area",
            "Radius",
            "TextString",
            "EffectiveName",
            "Name",
        ):
            value = self._prop(entity, prop_name)
            if value is not None and value != "":
                attrs[prop_name] = self._stringify(value)
        attrs.update(self._block_attributes(entity))
        return attrs

    def _block_attributes(self, entity: Any) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if not bool(self._prop(entity, "HasAttributes", False)):
            return result
        try:
            for attribute in entity.GetAttributes():
                tag = self._str_prop(attribute, "TagString", "Attribute")
                value = self._str_prop(attribute, "TextString", "")
                result[f"BlockAttribute_{safe_key(tag)}"] = value
        except Exception:
            pass
        return result

    def _polyline_points(self, entity: Any) -> List[Tuple[float, float, float]]:
        flat = list(self._prop(entity, "Coordinates") or [])
        if not flat:
            return []
        object_name = self._str_prop(entity, "ObjectName", "").lower()
        dim = 3 if "3d" in object_name else 2
        if dim == 2 and len(flat) % 2 != 0 and len(flat) % 3 == 0:
            dim = 3
        elevation = parse_float(self._prop(entity, "Elevation"), 0.0)
        points: List[Tuple[float, float, float]] = []
        if dim == 3:
            for index in range(0, len(flat) - 2, 3):
                points.append((float(flat[index]), float(flat[index + 1]), float(flat[index + 2])))
        else:
            for index in range(0, len(flat) - 1, 2):
                points.append((float(flat[index]), float(flat[index + 1]), elevation))
        closed = bool(self._prop(entity, "Closed", False))
        if dim == 2:
            points = self._expand_polyline_bulges(entity, points, closed)
        if closed and points and distance_2d(points[0], points[-1]) > 1e-9:
            points.append(points[0])
        return points

    def _expand_polyline_bulges(
        self, entity: Any, points: List[Tuple[float, float, float]], closed: bool
    ) -> List[Tuple[float, float, float]]:
        if len(points) < 2:
            return points
        segment_count = len(points) if closed else len(points) - 1
        expanded: List[Tuple[float, float, float]] = []
        has_bulge = False
        for index in range(segment_count):
            start = points[index]
            end = points[(index + 1) % len(points)]
            try:
                bulge = float(entity.GetBulge(index))
            except Exception:
                bulge = 0.0
            segment = self._bulge_segment_points(start, end, bulge)
            if abs(bulge) > 1e-12:
                has_bulge = True
            if expanded:
                expanded.extend(segment[1:])
            else:
                expanded.extend(segment)
        return expanded if has_bulge else points

    def _bulge_segment_points(
        self, start: Tuple[float, float, float], end: Tuple[float, float, float], bulge: float
    ) -> List[Tuple[float, float, float]]:
        if abs(bulge) < 1e-12:
            return [start, end]
        chord = distance_2d(start, end)
        if chord <= 1e-12:
            return [start, end]
        theta = 4.0 * math.atan(bulge)
        radius = chord * (1.0 + bulge * bulge) / (4.0 * bulge)
        base_angle = math.atan2(end[1] - start[1], end[0] - start[0])
        center_angle = base_angle + math.pi / 2.0 - 2.0 * math.atan(bulge)
        center_x = start[0] + math.cos(center_angle) * radius
        center_y = start[1] + math.sin(center_angle) * radius
        start_angle = math.atan2(start[1] - center_y, start[0] - center_x)
        segments = max(4, min(72, int(abs(theta) / (math.pi / 36.0)) + 1))
        points = []
        for index in range(segments + 1):
            fraction = index / segments
            angle = start_angle + theta * fraction
            z = start[2] + (end[2] - start[2]) * fraction
            points.append((center_x + abs(radius) * math.cos(angle), center_y + abs(radius) * math.sin(angle), z))
        return points

    def _points_from_flat(self, value: Any, dim: int) -> List[Tuple[float, float, float]]:
        try:
            flat = list(value or [])
        except TypeError:
            return []
        if not flat:
            return []
        points = []
        if dim == 3 and len(flat) >= 3:
            for index in range(0, len(flat) - 2, 3):
                points.append((float(flat[index]), float(flat[index + 1]), float(flat[index + 2])))
        elif dim == 2 and len(flat) >= 2:
            for index in range(0, len(flat) - 1, 2):
                points.append((float(flat[index]), float(flat[index + 1]), 0.0))
        return points

    def _transform_points(self, points: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
        coords: List[Tuple[float, float, float]] = []
        for point in points:
            lon, lat, altitude = self.transformer.to_wgs84(point)
            if not (math.isfinite(lon) and math.isfinite(lat) and -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                return []
            coords.append((lon, lat, altitude if math.isfinite(altitude) else 0.0))
        return coords

    def _closed_ring(self, coords: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
        if coords and (
            abs(coords[0][0] - coords[-1][0]) > 1e-12
            or abs(coords[0][1] - coords[-1][1]) > 1e-12
            or abs(coords[0][2] - coords[-1][2]) > 1e-6
        ):
            return coords + [coords[0]]
        return coords

    def _add_style(
        self,
        doc_el: ET.Element,
        style_id: str,
        rgb: Tuple[int, int, int],
        line_width: float,
        fill_alpha: int,
        icon_scale: float,
    ) -> None:
        style = ET.SubElement(doc_el, kml_tag("Style"), {"id": style_id})
        line = ET.SubElement(style, kml_tag("LineStyle"))
        ET.SubElement(line, kml_tag("color")).text = kml_color(rgb, 255)
        ET.SubElement(line, kml_tag("width")).text = f"{line_width:.2f}"
        poly = ET.SubElement(style, kml_tag("PolyStyle"))
        ET.SubElement(poly, kml_tag("color")).text = kml_color(rgb, fill_alpha)
        ET.SubElement(poly, kml_tag("fill")).text = "1" if fill_alpha > 0 else "0"
        ET.SubElement(poly, kml_tag("outline")).text = "1"
        icon = ET.SubElement(style, kml_tag("IconStyle"))
        ET.SubElement(icon, kml_tag("color")).text = kml_color(rgb, 255)
        ET.SubElement(icon, kml_tag("scale")).text = f"{max(0.0, icon_scale):.2f}"
        label = ET.SubElement(style, kml_tag("LabelStyle"))
        ET.SubElement(label, kml_tag("color")).text = kml_color(rgb, 255)
        ET.SubElement(label, kml_tag("scale")).text = "1.00"

    def _add_placemark(self, folder: ET.Element, feature: CadKmlFeature, style_id: str) -> None:
        placemark = ET.SubElement(folder, kml_tag("Placemark"))
        ET.SubElement(placemark, kml_tag("name")).text = feature.name
        ET.SubElement(placemark, kml_tag("styleUrl")).text = f"#{style_id}"
        self._add_geometry(placemark, feature)

    def _add_geometry(self, placemark: ET.Element, feature: CadKmlFeature) -> None:
        altitude_mode = "clampToGround"
        if feature.geometry_type == "Point":
            geom = ET.SubElement(placemark, kml_tag("Point"))
            ET.SubElement(geom, kml_tag("altitudeMode")).text = altitude_mode
            ET.SubElement(geom, kml_tag("coordinates")).text = self._coord_text(feature.coordinates)
        elif feature.geometry_type == "LineString":
            geom = ET.SubElement(placemark, kml_tag("LineString"))
            ET.SubElement(geom, kml_tag("tessellate")).text = "1"
            ET.SubElement(geom, kml_tag("altitudeMode")).text = altitude_mode
            ET.SubElement(geom, kml_tag("coordinates")).text = self._coord_text(feature.coordinates)
        else:
            geom = ET.SubElement(placemark, kml_tag("Polygon"))
            ET.SubElement(geom, kml_tag("tessellate")).text = "1"
            ET.SubElement(geom, kml_tag("altitudeMode")).text = altitude_mode
            outer = ET.SubElement(geom, kml_tag("outerBoundaryIs"))
            ring = ET.SubElement(outer, kml_tag("LinearRing"))
            ET.SubElement(ring, kml_tag("coordinates")).text = self._coord_text(self._closed_ring(feature.coordinates))
            for boundary in feature.inner_boundaries:
                inner = ET.SubElement(geom, kml_tag("innerBoundaryIs"))
                inner_ring = ET.SubElement(inner, kml_tag("LinearRing"))
                ET.SubElement(inner_ring, kml_tag("coordinates")).text = self._coord_text(self._closed_ring(boundary))

    def _coord_text(self, coords: List[Tuple[float, float, float]]) -> str:
        return " ".join(f"{lon:.9f},{lat:.9f},{alt:.3f}" for lon, lat, alt in coords)

    def _resolved_rgb(self, entity: Any, layer_name: str) -> Tuple[int, int, int]:
        color_index = int(parse_float(self._prop(entity, "Color"), 256.0))
        if color_index not in (0, 256, 257):
            rgb = self._true_color_rgb(entity)
            if rgb:
                return rgb
            return ACI_COLORS.get(color_index, ACI_COLORS.get(color_index % 10, (255, 255, 255)))
        layer = self._layer(layer_name)
        if layer is not None:
            rgb = self._true_color_rgb(layer)
            if rgb:
                return rgb
            layer_color = int(parse_float(self._prop(layer, "Color"), 7.0))
            return ACI_COLORS.get(layer_color, ACI_COLORS.get(layer_color % 10, (255, 255, 255)))
        return ACI_COLORS.get(color_index, (255, 255, 255))

    def _true_color_rgb(self, source: Any) -> Optional[Tuple[int, int, int]]:
        try:
            color = source.TrueColor
            rgb = (int(color.Red), int(color.Green), int(color.Blue))
            if all(0 <= value <= 255 for value in rgb):
                return rgb
        except Exception:
            return None
        return None

    def _line_width(self, entity: Any) -> float:
        raw = parse_float(self._prop(entity, "Lineweight"), -1.0)
        if raw <= 0:
            return 1.4
        return max(1.0, min(8.0, 1.0 + raw / 25.0))

    def _layer(self, layer_name: str) -> Any:
        layer_name = layer_name or "0"
        if layer_name not in self.layer_cache:
            try:
                self.layer_cache[layer_name] = self.doc.Layers.Item(layer_name)
            except Exception:
                self.layer_cache[layer_name] = None
        return self.layer_cache[layer_name]

    def _feature_name(self, entity: Any, prefix: str) -> str:
        text = self._str_prop(entity, "TextString", "")
        if text:
            return text[:80]
        block = self._str_prop(entity, "EffectiveName", "") or self._str_prop(entity, "Name", "")
        if block:
            return block[:80]
        handle = self._str_prop(entity, "Handle", "")
        return f"{prefix} {handle}".strip()

    def _point_tuple(self, value: Any) -> Optional[Tuple[float, float, float]]:
        try:
            items = list(value)
        except TypeError:
            return None
        if len(items) < 2:
            return None
        return (float(items[0]), float(items[1]), float(items[2]) if len(items) > 2 else 0.0)

    def _prop(self, source: Any, name: str, default: Any = None) -> Any:
        try:
            return getattr(source, name)
        except Exception:
            return default

    def _str_prop(self, source: Any, name: str, default: str = "") -> str:
        value = self._prop(source, name, default)
        return self._stringify(value) if value is not None else default

    def _stringify(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.12g}"
        if isinstance(value, (list, tuple)):
            return ", ".join(self._stringify(item) for item in value)
        return str(value)

    def _skip(self, object_name: str) -> None:
        self.skipped_count += 1
        self.skipped_by_type[object_name or "Unknown"] = self.skipped_by_type.get(object_name or "Unknown", 0) + 1


class KmlAutoCADImporter:
    def __init__(self, doc: Any, cs: CoordinateSystem, kml_text: str):
        self.doc = doc
        self.cs = cs
        self.transformer = CoordinateTransformer(cs)
        self.kml_text = kml_text
        self.entity_count = 0
        self.placemark_count = 0
        self.skipped_count = 0

    def import_to_model_space(self) -> KmlImportResult:
        root = ET.fromstring(self.kml_text.encode("utf-8"))
        for placemark in self._iter_elements(root, "Placemark"):
            self.placemark_count += 1
            before = self.entity_count
            name = self._child_text(placemark, "name")
            for child in list(placemark):
                if self._local_name(child.tag) in ("Point", "LineString", "Polygon", "MultiGeometry", "LinearRing"):
                    self._import_geometry(child, name)
            if self.entity_count == before:
                self.skipped_count += 1
        return KmlImportResult(self.entity_count, self.placemark_count, self.skipped_count)

    def _import_geometry(self, element: ET.Element, name: str = "") -> None:
        kind = self._local_name(element.tag)
        if kind == "MultiGeometry":
            for child in list(element):
                self._import_geometry(child, name)
        elif kind == "Point":
            coords = self._coords_from_element(element)
            if coords:
                self._add_point(coords[0])
        elif kind == "LineString":
            coords = self._coords_from_element(element)
            self._add_polyline(coords, closed=False)
        elif kind == "LinearRing":
            coords = self._coords_from_element(element)
            self._add_polyline(coords, closed=True)
        elif kind == "Polygon":
            outer = self._first_descendant(element, "outerBoundaryIs")
            ring = self._first_descendant(outer, "LinearRing") if outer is not None else None
            coords = self._coords_from_element(ring) if ring is not None else []
            self._add_polyline(coords, closed=True)

    def _add_point(self, coord: Tuple[float, float, float]) -> None:
        model_space = getattr(self.doc, "ModelSpace")
        point = self._drawing_point(coord)
        entity = model_space.AddPoint(self._com_array(point))
        self._set_layer_zero(entity)
        self.entity_count += 1

    def _add_polyline(self, coords: List[Tuple[float, float, float]], closed: bool) -> None:
        if len(coords) < 2:
            return
        model_space = getattr(self.doc, "ModelSpace")
        points = [self._drawing_point(coord) for coord in coords]
        if closed and points and distance_2d(points[0], points[-1]) < 1e-7:
            points = points[:-1]
        if len(points) < 2:
            return
        try:
            flat_2d: List[float] = []
            for x, y, _z in points:
                flat_2d.extend([x, y])
            entity = model_space.AddLightWeightPolyline(self._com_array(flat_2d))
            try:
                entity.Closed = bool(closed)
            except Exception:
                pass
        except Exception:
            if len(points) == 2 and not closed:
                entity = model_space.AddLine(self._com_array(points[0]), self._com_array(points[1]))
            else:
                flat_3d: List[float] = []
                ring_points = points + [points[0]] if closed else points
                for x, y, z in ring_points:
                    flat_3d.extend([x, y, z])
                entity = model_space.AddPolyline(self._com_array(flat_3d))
                try:
                    entity.Closed = bool(closed)
                except Exception:
                    pass
        self._set_layer_zero(entity)
        self.entity_count += 1

    def _drawing_point(self, coord: Tuple[float, float, float]) -> Tuple[float, float, float]:
        lon, lat, _altitude = coord
        return self.transformer.from_wgs84(lon, lat, 0.0)

    def _coords_from_element(self, element: Optional[ET.Element]) -> List[Tuple[float, float, float]]:
        if element is None:
            return []
        coord_el = self._first_descendant(element, "coordinates")
        if coord_el is None or not coord_el.text:
            return []
        coords: List[Tuple[float, float, float]] = []
        for token in coord_el.text.replace("\n", " ").replace("\t", " ").split():
            parts = token.split(",")
            if len(parts) < 2:
                continue
            lon = parse_float(parts[0], math.nan)
            lat = parse_float(parts[1], math.nan)
            alt = parse_float(parts[2], 0.0) if len(parts) > 2 else 0.0
            if math.isfinite(lon) and math.isfinite(lat):
                coords.append((lon, lat, alt))
        return coords

    def _set_layer_zero(self, entity: Any) -> None:
        try:
            entity.Layer = "0"
        except Exception:
            pass

    def _com_array(self, values: Sequence[float]) -> Any:
        flat = tuple(float(value) for value in values)
        try:
            import pythoncom
            import win32com.client

            return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)
        except Exception:
            return flat

    def _iter_elements(self, root: ET.Element, local_name: str) -> Iterable[ET.Element]:
        for element in root.iter():
            if self._local_name(element.tag) == local_name:
                yield element

    def _first_descendant(self, root: Optional[ET.Element], local_name: str) -> Optional[ET.Element]:
        if root is None:
            return None
        for element in root.iter():
            if self._local_name(element.tag) == local_name:
                return element
        return None

    def _child_text(self, root: ET.Element, local_name: str) -> str:
        for child in list(root):
            if self._local_name(child.tag) == local_name:
                return (child.text or "").strip()
        return ""

    def _local_name(self, tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag


class CoordinateSystemDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, library: CoordinateSystemLibrary, on_select):
        super().__init__(master)
        self.title("Select Geographic Coordinate System")
        self.geometry("1120x720")
        self.minsize(940, 620)
        self.library = library
        self.on_select = on_select
        self.selected_key: Optional[str] = None
        self.item_key_by_tree_id: Dict[str, str] = {}
        self._search_keys: List[str] = []
        self._build_ui()
        self._populate_tree()
        self.transient(master)
        self.grab_set()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=4)
        root.pack(fill="both", expand=True)
        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True)
        library_tab = ttk.Frame(tabs)
        search_tab = ttk.Frame(tabs)
        tabs.add(library_tab, text="Library")
        tabs.add(search_tab, text="Search")

        paned = ttk.PanedWindow(library_tab, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, width=360)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=3)

        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(side="left", fill="both", expand=True)
        ys = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        ys.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda _event: self._ok())

        self.detail_canvas = tk.Canvas(right, highlightthickness=0)
        ds = ttk.Scrollbar(right, orient="vertical", command=self.detail_canvas.yview)
        self.detail_canvas.configure(yscrollcommand=ds.set)
        ds.pack(side="right", fill="y")
        self.detail_canvas.pack(side="left", fill="both", expand=True)
        self.detail_frame = ttk.Frame(self.detail_canvas, padding=(8, 4))
        self.detail_window = self.detail_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        self.detail_frame.bind("<Configure>", lambda _e: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")))
        self.detail_canvas.bind("<Configure>", lambda e: self.detail_canvas.itemconfigure(self.detail_window, width=e.width))

        search_bar = ttk.Frame(search_tab, padding=8)
        search_bar.pack(fill="x")
        ttk.Label(search_bar, text="Tìm hệ tọa độ:").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(search_bar, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(search_bar, text="Tìm", command=self._search).pack(side="left")
        self.search_result = tk.Listbox(search_tab)
        self.search_result.pack(fill="both", expand=True, padx=8, pady=8)
        self.search_result.bind("<<ListboxSelect>>", self._on_search_select)

        footer = ttk.Frame(root, padding=(0, 8, 0, 0))
        footer.pack(fill="x")
        ttk.Button(footer, text="Ok", width=14, command=self._ok).pack(side="left", padx=(24, 8))
        ttk.Button(footer, text="Cancel", width=14, command=self.destroy).pack(side="left")
        ttk.Button(footer, text="Thêm Hay sử dụng", command=self._add_favorite).pack(side="right", padx=8)

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.item_key_by_tree_id.clear()
        fav_root = self.tree.insert("", "end", text="Hay sử dụng", open=True)
        ge_root = self.tree.insert("", "end", text="Google Earth", open=True)
        vn_root = self.tree.insert("", "end", text="VN2000", open=True)

        ge = self.library.items.get("GOOGLE_EARTH_WGS84")
        if ge:
            node = self.tree.insert(ge_root, "end", text=ge.name)
            self.item_key_by_tree_id[node] = ge.key
        for key in self.library.favorites:
            item = self.library.items.get(key)
            if item:
                node = self.tree.insert(fav_root, "end", text=item.name)
                self.item_key_by_tree_id[node] = key
        for item in sorted(self.library.items.values(), key=lambda x: x.name):
            if item.group == "Google Earth":
                continue
            node = self.tree.insert(vn_root, "end", text=item.name)
            self.item_key_by_tree_id[node] = item.key
        children = self.tree.get_children(ge_root)
        if children:
            self.tree.selection_set(children[0])
            self._on_tree_select(None)

    def _on_tree_select(self, _event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        key = self.item_key_by_tree_id.get(selected[0])
        if key:
            self.selected_key = key
            self._show_details(self.library.items[key])

    def _show_details(self, cs: CoordinateSystem) -> None:
        for child in self.detail_frame.winfo_children():
            child.destroy()
        self._section("Coordinate System", [
            ("Name", cs.name), ("Description", cs.description), ("Projection", cs.projection),
            ("Source", cs.source), ("Units", cs.units), ("Central Meridian", cs.central_meridian),
            ("Origin Latitude", cs.origin_latitude), ("Scale Reduction", cs.scale_reduction),
            ("False Easting", cs.false_easting), ("False Northing", cs.false_northing),
            ("Quadrant", cs.quadrant), ("Minimum Longitude", cs.minimum_longitude),
            ("Maximum Longitude", cs.maximum_longitude), ("Minimum Latitude", cs.minimum_latitude),
            ("Maximum Latitude", cs.maximum_latitude),
        ])
        self._section("Datum", [
            ("Name", cs.datum_name), ("Description", cs.datum_description), ("Source", cs.source),
            ("Conversion Method", cs.conversion_method), ("Delta X", cs.delta_x), ("Delta Y", cs.delta_y),
            ("Delta Z", cs.delta_z), ("X Rotation", cs.x_rotation), ("Y Rotation", cs.y_rotation),
            ("Z Rotation", cs.z_rotation), ("Scale", cs.scale),
        ])
        self._section("Ellipsoid", [
            ("Name", cs.ellipsoid_name), ("Description", cs.ellipsoid_description),
            ("Equatorial Radius", cs.equatorial_radius), ("Polar Radius", cs.polar_radius),
            ("Eccentricity", cs.eccentricity),
        ])
        if cs.raw:
            self._section("Raw / Debug", list(cs.raw.items()))

    def _section(self, title: str, rows: List[tuple]) -> None:
        box = ttk.LabelFrame(self.detail_frame, text=title, padding=8)
        box.pack(fill="x", expand=True, pady=5)
        for r, (key, value) in enumerate(rows):
            ttk.Label(box, text=key, width=28).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Label(box, text=str(value), font=("Segoe UI", 9, "bold"), wraplength=560).grid(row=r, column=1, sticky="w", pady=2)
        box.columnconfigure(1, weight=1)

    def _search(self) -> None:
        q = self.search_var.get().lower().strip()
        self.search_result.delete(0, "end")
        self._search_keys = []
        for item in sorted(self.library.items.values(), key=lambda x: x.name):
            haystack = f"{item.name} {item.description} {item.central_meridian}".lower()
            if not q or q in haystack:
                self._search_keys.append(item.key)
                self.search_result.insert("end", item.name)

    def _on_search_select(self, _event) -> None:
        selected = self.search_result.curselection()
        if not selected:
            return
        key = self._search_keys[selected[0]]
        self.selected_key = key
        self._show_details(self.library.items[key])

    def _add_favorite(self) -> None:
        if self.selected_key:
            self.library.add_favorite(self.selected_key)
            self._populate_tree()

    def _ok(self) -> None:
        if not self.selected_key:
            messagebox.showwarning(APP_NAME, "Chưa chọn hệ tọa độ.")
            return
        self.on_select(self.library.items[self.selected_key])
        self.destroy()


class GeographicApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.app_dir = self._get_app_dir()
        self.crs_library = CoordinateSystemLibrary(self.app_dir)
        self.current_crs: Optional[CoordinateSystem] = None
        self.acad = None
        self.doc = None
        self._place_bottom_right()
        self._build_ui()
        self._log("Khởi động Geographic.")
        self._log(f"Thư mục ứng dụng: {self.app_dir}")
        self._log(f"Đã nạp {len(self.crs_library.items)} hệ tọa độ.")
        if self.crs_library.dty_path.exists():
            self._log(f"Đã đọc VN2000.dty: {self.crs_library.dty_path.name}")
        else:
            self._log("Chưa thấy VN2000.dty, đang dùng dữ liệu mẫu tích hợp.")
        self._connect_autocad_startup()

    def _get_app_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _place_bottom_right(self) -> None:
        self.root.update_idletasks()
        left, top, right, bottom = screen_work_area(self.root)
        x = max(left, right - WINDOW_WIDTH - WINDOW_MARGIN_X)
        y = max(top, bottom - WINDOW_HEIGHT - WINDOW_MARGIN_Y)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)
        button_frame = ttk.Frame(main)
        button_frame.pack(fill="x")
        buttons = [
            ("Hệ tọa độ", self.on_coordinate_system),
            ("Xuất KML/KMZ", self.on_export_kml_kmz),
            ("Nhập KML/KMZ", self.on_import_kml_kmz),
            ("Lấy từ GG Earth", self.on_get_from_google_earth),
            ("Lựa chọn", self.on_selection),
        ]
        for i, (text, command) in enumerate(buttons):
            ttk.Button(button_frame, text=text, command=command).grid(row=0, column=i, padx=3, pady=3, sticky="nsew")
            button_frame.columnconfigure(i, weight=1)
        ttk.Label(main, text="Thông báo").pack(anchor="w", pady=(8, 2))
        msg_frame = ttk.Frame(main)
        msg_frame.pack(fill="both", expand=True)
        self.message = tk.Text(msg_frame, height=10, wrap="word", state="disabled", font=("Consolas", 10))
        self.message.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(msg_frame, command=self.message.yview)
        scrollbar.pack(side="right", fill="y")
        self.message.configure(yscrollcommand=scrollbar.set)

    def _log(self, text: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.message.configure(state="normal")
        self.message.insert("end", f"[{now}] {text}\n")
        self.message.see("end")
        self.message.configure(state="disabled")

    def _connect_autocad_startup(self) -> None:
        try:
            import win32com.client
            self.acad = win32com.client.GetActiveObject("AutoCAD.Application")
            self.doc = self.acad.ActiveDocument
            doc_name = self.doc.Name if self.doc else "(không có bản vẽ active)"
            cs = self._load_document_crs()
            if cs:
                self.current_crs = cs
            else:
                self.current_crs = None
            self._log(f"Đã kết nối AutoCAD đang chạy: {doc_name}")
            if self.current_crs:
                self._log(f"Hệ tọa độ đã lưu trong DWG: {self.current_crs.name}")
            else:
                self._log("Bản vẽ chưa lưu hệ tọa độ.")
        except ImportError:
            self._log("Chưa có pywin32. Cài bằng lệnh: pip install pywin32")
        except Exception as exc:
            self._log(f"Chưa kết nối được AutoCAD đang chạy: {exc}")

    def ensure_autocad(self) -> bool:
        if self.acad is not None and self.doc is not None:
            return True
        self._log("Đang thử kết nối lại AutoCAD...")
        self._connect_autocad_startup()
        return self.acad is not None and self.doc is not None

    def _refresh_active_document(self) -> None:
        if self.acad is None:
            return
        try:
            self.doc = self.acad.ActiveDocument
        except Exception:
            pass

    def _coordinate_system_payload(self, cs: CoordinateSystem) -> str:
        data = {name: getattr(cs, name) for name in CoordinateSystem.__dataclass_fields__}
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def _coordinate_system_from_payload(self, payload: str) -> Optional[CoordinateSystem]:
        try:
            data = json.loads(payload)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        key = str(data.get("key", "")).strip()
        if key in self.crs_library.items:
            return self.crs_library.items[key]
        allowed = set(CoordinateSystem.__dataclass_fields__)
        values = {name: data[name] for name in allowed if name in data}
        if not values.get("key") or not values.get("name"):
            return None
        try:
            return CoordinateSystem(**values)
        except Exception:
            return None

    def _load_document_crs(self) -> Optional[CoordinateSystem]:
        if self.doc is None:
            return None
        key = self._get_dwg_custom_info(DWG_CRS_KEY_PROP)
        if key and key in self.crs_library.items:
            return self.crs_library.items[key]
        payload = self._get_dwg_custom_info(DWG_CRS_DATA_PROP)
        if payload:
            return self._coordinate_system_from_payload(payload)
        return None

    def _save_document_crs(self, cs: CoordinateSystem) -> bool:
        if self.doc is None:
            return False
        saved_key = self._set_dwg_custom_info(DWG_CRS_KEY_PROP, cs.key)
        self._set_dwg_custom_info(DWG_CRS_DATA_PROP, self._coordinate_system_payload(cs))
        try:
            self.doc.SetVariable("USERS5", f"{APP_NAME}:{cs.key}")
        except Exception:
            pass
        return saved_key

    def _require_document_crs(self) -> Optional[CoordinateSystem]:
        self._refresh_active_document()
        cs = self._load_document_crs()
        if cs:
            self.current_crs = cs
            return cs
        self.current_crs = None
        self._log("Bản vẽ chưa lưu hệ tọa độ. Vui lòng chọn hệ tọa độ trước khi xuất KML/KMZ.")
        messagebox.showinfo(APP_NAME, "Bản vẽ chưa lưu hệ tọa độ.\nVui lòng chọn/gán hệ tọa độ trước khi xuất KML/KMZ.")
        self.on_coordinate_system()
        return None

    def _summary_info(self) -> Any:
        if self.doc is None:
            return None
        try:
            return self.doc.SummaryInfo
        except Exception:
            return None

    def _get_dwg_custom_info(self, key: str) -> Optional[str]:
        summary = self._summary_info()
        if summary is None:
            return None
        try:
            value = summary.GetCustomByKey(key)
            if isinstance(value, tuple):
                value = value[-1] if value else None
            if value not in (None, ""):
                return str(value)
        except Exception:
            pass
        try:
            import pythoncom
            import win32com.client

            value = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
            summary.GetCustomByKey(key, value)
            if value.value:
                return str(value.value)
        except Exception:
            pass
        try:
            raw_count = getattr(summary, "NumCustomInfo", 0)
            count = int(raw_count() if callable(raw_count) else raw_count or 0)
        except Exception:
            count = 0
        for index in range(count):
            try:
                item = summary.GetCustomByIndex(index)
                if isinstance(item, tuple) and len(item) >= 2 and str(item[0]) == key:
                    return str(item[1])
            except Exception:
                pass
        return None

    def _set_dwg_custom_info(self, key: str, value: str) -> bool:
        summary = self._summary_info()
        if summary is None:
            return False
        text = str(value)
        for method_name in ("SetCustomByKey", "AddCustomInfo"):
            try:
                getattr(summary, method_name)(key, text)
                return True
            except Exception:
                pass
        try:
            summary.RemoveCustomByKey(key)
            summary.AddCustomInfo(key, text)
            return True
        except Exception:
            return False

    def _highlighted_entities(self) -> List[Any]:
        if self.doc is None:
            return []
        for prop_name in ("PickfirstSelectionSet", "ActiveSelectionSet"):
            try:
                selection = getattr(self.doc, prop_name)
            except Exception:
                continue
            entities = self._collection_items(selection)
            if entities:
                return entities
        return []

    def _collection_items(self, collection: Any) -> List[Any]:
        if collection is None:
            return []
        try:
            return list(collection)
        except Exception:
            pass
        items: List[Any] = []
        try:
            count = int(getattr(collection, "Count", 0) or 0)
        except Exception:
            count = 0
        for index in range(count):
            try:
                items.append(collection.Item(index))
            except Exception:
                pass
        return items

    def on_coordinate_system(self) -> None:
        CoordinateSystemDialog(self.root, self.crs_library, self._set_coordinate_system)

    def _set_coordinate_system(self, cs: CoordinateSystem) -> None:
        self.current_crs = cs
        self._log(f"Đã chọn hệ tọa độ: {cs.name}")
        self._log(f"Phép chiếu: {cs.projection}; Đơn vị: {cs.units}; Kinh tuyến trục: {cs.central_meridian}")
        if self.acad is not None and self.doc is not None:
            self._refresh_active_document()
            if self._save_document_crs(cs):
                self._log(f"Đã lưu hệ tọa độ vào DWG: {cs.name}")
            else:
                self._log("Chưa lưu được hệ tọa độ vào DWG.")
                messagebox.showwarning(APP_NAME, "Chưa lưu được hệ tọa độ vào DWG.")

    def on_export_kml_kmz(self) -> None:
        if not self.ensure_autocad():
            self._log("Xuất KML/KMZ: chưa có kết nối AutoCAD.")
            messagebox.showwarning(APP_NAME, "Chưa kết nối được AutoCAD đang chạy.")
            return
        try:
            self.doc = self.acad.ActiveDocument
        except Exception:
            pass
        if self.doc is None:
            self._log("Xuất KML/KMZ: không có bản vẽ active.")
            messagebox.showwarning(APP_NAME, "Không có bản vẽ active trong AutoCAD.")
            return

        cs = self._require_document_crs()
        if cs is None:
            return
        selected_entities = self._highlighted_entities()
        drawing_name = self._active_drawing_name()
        output_path = default_downloads_folder() / f"{safe_filename_stem(drawing_name)}.kmz"
        self._log(f"Đang xuất KML/KMZ: {drawing_name}")
        self._log(f"Hệ tọa độ nguồn: {cs.name}")
        if selected_entities:
            self._log(f"Phạm vi xuất: {len(selected_entities)} đối tượng đang được chọn.")
        else:
            self._log("Phạm vi xuất: toàn bộ đối tượng trong ModelSpace.")
        self._log(f"File đích: {output_path}")
        try:
            exporter = AutoCADKmlExporter(self.doc, cs, selected_entities or None)
            result = exporter.export_kmz(output_path)
        except Exception as exc:
            self._log(f"Xuất KML/KMZ thất bại: {exc}")
            messagebox.showerror(APP_NAME, f"Xuất KML/KMZ thất bại:\n{exc}")
            return

        self._log(f"Đã xuất {result.feature_count} đối tượng trên {result.layer_count} lớp -> {result.output_path.name}")
        if result.skipped_count:
            skipped_preview = ", ".join(f"{key}: {value}" for key, value in list(result.skipped_by_type.items())[:6])
            self._log(f"Bỏ qua {result.skipped_count} đối tượng chưa hỗ trợ/không hợp lệ: {skipped_preview}")
        self._open_result_file(result.output_path)

    def _active_drawing_name(self) -> str:
        if self.doc is None:
            return "Drawing.dwg"
        for prop_name in ("FullName", "Name"):
            try:
                value = getattr(self.doc, prop_name)
                if value:
                    return Path(str(value)).name
            except Exception:
                pass
        return "Drawing.dwg"

    def _open_result_file(self, path: Path) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))
            else:
                raise RuntimeError("Không hỗ trợ mở file tự động trên hệ điều hành này")
            self._log(f"Đã mở kết quả: {path}")
        except Exception as exc:
            self._log(f"Đã tạo file nhưng chưa mở được: {exc}")

    def on_import_kml_kmz(self) -> None:
        self._log("Chức năng Nhập KML/KMZ: chờ mô tả chi tiết.")

    def on_get_from_google_earth(self) -> None:
        if not self.ensure_autocad():
            self._log("Lấy từ GG Earth: chưa có kết nối AutoCAD.")
            messagebox.showwarning(APP_NAME, "Chưa kết nối được AutoCAD đang chạy.")
            return
        self._refresh_active_document()
        if self.doc is None:
            self._log("Lấy từ GG Earth: không có bản vẽ active.")
            messagebox.showwarning(APP_NAME, "Không có bản vẽ active trong AutoCAD.")
            return
        cs = self._require_document_crs()
        if cs is None:
            return
        kml_text = self._get_google_earth_selection_kml()
        if not kml_text:
            self._log("Không lấy được KML từ Google Earth.")
            messagebox.showinfo(
                APP_NAME,
                "Chưa lấy được dữ liệu từ Google Earth.\n"
                "Hãy chọn nhánh trong khung Địa điểm của Google Earth, nhấn Ctrl+C, rồi bấm lại Lấy từ GG Earth.",
            )
            return
        try:
            importer = KmlAutoCADImporter(self.doc, cs, kml_text)
            result = importer.import_to_model_space()
        except Exception as exc:
            self._log(f"Nhập dữ liệu từ Google Earth thất bại: {exc}")
            messagebox.showerror(APP_NAME, f"Nhập dữ liệu từ Google Earth thất bại:\n{exc}")
            return
        self._log(
            f"Đã lấy {result.entity_count} đối tượng từ Google Earth vào ModelSpace lớp 0 "
            f"({result.placemark_count} placemark, bỏ qua {result.skipped_count})."
        )

    def _get_google_earth_selection_kml(self) -> str:
        before = self._clipboard_text()
        copied = self._copy_google_earth_selection_to_clipboard()
        if copied:
            time.sleep(0.7)
            text = self._clipboard_text()
            if self._looks_like_kml(text):
                return text
        if self._looks_like_kml(before):
            return before
        text = self._clipboard_text()
        return text if self._looks_like_kml(text) else ""

    def _copy_google_earth_selection_to_clipboard(self) -> bool:
        try:
            import win32com.client
            import win32con
            import win32gui

            windows: List[Tuple[int, str]] = []

            def enum_window(hwnd, _extra):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if "Google Earth" in title:
                    windows.append((hwnd, title))

            win32gui.EnumWindows(enum_window, None)
            if not windows:
                return False
            hwnd, title = windows[0]
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.AppActivate(title)
            time.sleep(0.2)
            shell.SendKeys("^c")
            try:
                self.root.lift()
                self.root.attributes("-topmost", True)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _clipboard_text(self) -> str:
        try:
            return self.root.clipboard_get()
        except Exception:
            return ""

    def _looks_like_kml(self, text: str) -> bool:
        if not text:
            return False
        sample = text.lstrip()[:500].lower()
        return "<kml" in sample or "<placemark" in sample or "<document" in sample

    def on_selection(self) -> None:
        if self.ensure_autocad():
            self._log("Chức năng Lựa chọn: đã sẵn sàng thao tác với bản vẽ AutoCAD.")
        else:
            self._log("Chức năng Lựa chọn: chưa có kết nối AutoCAD.")


def main() -> None:
    root = tk.Tk()
    GeographicApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

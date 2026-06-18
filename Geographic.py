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
import re
import struct
import sys
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

APP_NAME = "Geographic"
WINDOW_WIDTH = 640
WINDOW_HEIGHT = 300
WINDOW_MARGIN_X = 18
WINDOW_MARGIN_Y = 48


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
        x = self.root.winfo_screenwidth() - WINDOW_WIDTH - WINDOW_MARGIN_X
        y = self.root.winfo_screenheight() - WINDOW_HEIGHT - WINDOW_MARGIN_Y
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
        ttk.Label(main, text="Message").pack(anchor="w", pady=(8, 2))
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
            self._log(f"Đã kết nối AutoCAD đang chạy: {doc_name}")
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

    def on_coordinate_system(self) -> None:
        CoordinateSystemDialog(self.root, self.crs_library, self._set_coordinate_system)

    def _set_coordinate_system(self, cs: CoordinateSystem) -> None:
        self.current_crs = cs
        self._log(f"Đã chọn hệ tọa độ: {cs.name}")
        self._log(f"Projection: {cs.projection}; Units: {cs.units}; Central Meridian: {cs.central_meridian}")

    def on_export_kml_kmz(self) -> None:
        self._log("Chức năng Xuất KML/KMZ: chờ mô tả chi tiết.")

    def on_import_kml_kmz(self) -> None:
        self._log("Chức năng Nhập KML/KMZ: chờ mô tả chi tiết.")

    def on_get_from_google_earth(self) -> None:
        self._log("Chức năng Lấy từ GG Earth: chờ mô tả chi tiết.")

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

# -*- coding: utf-8 -*-
"""
Geographic.py
Ứng dụng Geographic DWG - giao diện khởi tạo và hộp chọn hệ tọa độ.

Chức năng hiện có:
- Cửa sổ chính nằm góc dưới phải màn hình.
- Các nút chức năng chính.
- Hộp thoại "Hệ tọa độ" dạng cây thư mục.
- Tự tìm file VN2000.dty trong thư mục ứng dụng.
- Nạp mặc định Google Earth / WGS84.
- Nạp thư mục VN2000 từ file VN2000.dty.
- Có cây "Hay sử dụng" lưu trong favorites_crs.json.
- Hiển thị thông tin hệ tọa độ đang chọn.
"""

from __future__ import annotations

import configparser
import csv
import io
import json
import os
import re
import sys
import tkinter as tk
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional


APP_NAME = "Geographic"
WINDOW_WIDTH = 640
WINDOW_HEIGHT = 300
WINDOW_MARGIN_X = 18
WINDOW_MARGIN_Y = 48


@dataclass
class CoordinateSystem:
    key: str
    name: str
    description: str = ""
    group: str = "VN2000"
    projection: str = "Transverse Mercator"
    source: str = ""
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
            units="Degree",
            central_meridian="Greenwich / 0°",
            origin_latitude="Equator / 0°",
            scale_reduction="1.0",
            false_easting="0",
            false_northing="0",
            datum_name="WGS84",
            datum_description="World Geodetic System of 1984",
            conversion_method="None",
            delta_x="0",
            delta_y="0",
            delta_z="0",
            x_rotation="0",
            y_rotation="0",
            z_rotation="0",
            scale="1.0",
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
            loaded = self._load_vn2000_file(self.dty_path)
            for item in loaded:
                self.items[item.key] = item
        else:
            for item in self._builtin_vn2000_examples():
                self.items[item.key] = item

        self.favorites = self._load_favorites()

    def _load_favorites(self) -> List[str]:
        if not self.favorite_path.exists():
            return []
        try:
            data = json.loads(self.favorite_path.read_text(encoding="utf-8"))
            return [x for x in data if x in self.items]
        except Exception:
            return []

    def save_favorites(self) -> None:
        self.favorite_path.write_text(json.dumps(self.favorites, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_favorite(self, key: str) -> None:
        if key in self.items and key not in self.favorites:
            self.favorites.append(key)
            self.save_favorites()

    def _load_vn2000_file(self, path: Path) -> List[CoordinateSystem]:
        text = self._read_text_any_encoding(path)
        if not text.strip():
            return []

        for loader in (self._parse_json, self._parse_ini, self._parse_csv, self._parse_loose_blocks):
            try:
                items = loader(text)
                if items:
                    return items
            except Exception:
                pass
        return []

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
        if isinstance(data, dict):
            rows = data.get("coordinate_systems") or data.get("items") or []
        else:
            rows = data
        return [self._row_to_cs(row) for row in rows if isinstance(row, dict)]

    def _parse_ini(self, text: str) -> List[CoordinateSystem]:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read_string(text)
        items = []
        for section in parser.sections():
            row = dict(parser[section])
            row.setdefault("Name", section)
            items.append(self._row_to_cs(row))
        return items

    def _parse_csv(self, text: str) -> List[CoordinateSystem]:
        sample = text[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        return [self._row_to_cs(row) for row in reader if row]

    def _parse_loose_blocks(self, text: str) -> List[CoordinateSystem]:
        blocks = re.split(r"\n\s*\n|\n\s*-{3,}\s*\n", text)
        items = []
        for block in blocks:
            row = {}
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                elif ":" in line:
                    k, v = line.split(":", 1)
                else:
                    continue
                row[k.strip()] = v.strip()
            if row:
                items.append(self._row_to_cs(row))
        return items

    def _row_to_cs(self, row: Dict[str, object]) -> CoordinateSystem:
        def get(*names: str, default: str = "") -> str:
            lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
            for name in names:
                key = name.strip().lower().replace(" ", "_")
                if key in lowered and lowered[key] is not None:
                    return str(lowered[key]).strip()
            return default

        name = get("Name", "name", "Ten", "Tỉnh", "Tinh", default="VN2000")
        desc = get("Description", "description", "Mo ta", default=name)
        key = get("Key", "ID", default=self._safe_key(name))
        return CoordinateSystem(
            key=key,
            name=name,
            description=desc,
            group=get("Group", "Folder", default="VN2000"),
            projection=get("Projection", default="Transverse Mercator"),
            source=get("Source"),
            units=get("Units", default="Meter"),
            central_meridian=get("Central Meridian", "Central_Meridian", "Kinh tuyến trục", "Kinh tuyen truc"),
            origin_latitude=get("Origin Latitude", "Origin_Latitude", default="00°00'00.0000\"N"),
            scale_reduction=get("Scale Reduction", "Scale_Reduction", "Scale", "Scale factor", default="0.9999"),
            false_easting=get("False Easting", "False_Easting", default="500000"),
            false_northing=get("False Northing", "False_Northing", default="0"),
            quadrant=get("Quadrant", default="Positive X and Y"),
            minimum_longitude=get("Minimum Longitude", "Minimum_Longitude"),
            maximum_longitude=get("Maximum Longitude", "Maximum_Longitude"),
            minimum_latitude=get("Minimum Latitude", "Minimum_Latitude"),
            maximum_latitude=get("Maximum Latitude", "Maximum_Latitude"),
            datum_name=get("Datum Name", "Datum", default="VN2000"),
            datum_description=get("Datum Description", "Datum_Description", default="05_2007_QD-BTNMT"),
            conversion_method=get("Conversion Method", "Conversion_Method", default="Seven Parameter Transformation"),
            delta_x=get("Delta X", "Delta_X", default="-191.90441429"),
            delta_y=get("Delta Y", "Delta_Y", default="-39.30318279"),
            delta_z=get("Delta Z", "Delta_Z", default="-111.45032835"),
            x_rotation=get("X Rotation", "X_Rotation", default="-0.00928836"),
            y_rotation=get("Y Rotation", "Y_Rotation", default="0.01975479"),
            z_rotation=get("Z Rotation", "Z_Rotation", default="-0.00427372"),
            scale=get("Datum Scale", "Datum_Scale", "Transformation Scale", default="1.0000002529062779"),
            ellipsoid_name=get("Ellipsoid Name", "Ellipsoid", default="WGS84"),
            ellipsoid_description=get("Ellipsoid Description", "Ellipsoid_Description", default="World Geodetic System of 1984"),
            equatorial_radius=get("Equatorial Radius", "Equatorial_Radius", default="6378137"),
            polar_radius=get("Polar Radius", "Polar_Radius", default="6356752.3142"),
            eccentricity=get("Eccentricity", default="0.081819190928906743"),
            raw={str(k): str(v) for k, v in row.items()},
        )

    def _safe_key(self, name: str) -> str:
        base = re.sub(r"[^0-9A-Za-z_]+", "_", name.strip()) or "VN2000"
        key = base
        i = 2
        while key in self.items:
            key = f"{base}_{i}"
            i += 1
        return key

    def _builtin_vn2000_examples(self) -> List[CoordinateSystem]:
        return [
            CoordinateSystem(
                key="VN2000_CAMAU",
                name="CaMau - Ca Mau (VN2000)",
                description="Ca Mau (VN2000)",
                central_meridian="104°30'00.0000\"E",
            ),
            CoordinateSystem(
                key="VN2000_BAC_KAN",
                name="BacKan - Bac Kan (VN2000)",
                description="Bac Kan (VN2000)",
                central_meridian="106°30'00.0000\"E",
                minimum_longitude="102°08'00.0000\"E",
                maximum_longitude="109°30'00.0000\"E",
                minimum_latitude="07°19'48.0000\"N",
                maximum_latitude="23°45'00.0000\"N",
            ),
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
        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        yscroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda event: self._ok())

        self.detail_canvas = tk.Canvas(right, highlightthickness=0)
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.detail_canvas.yview)
        self.detail_canvas.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right", fill="y")
        self.detail_canvas.pack(side="left", fill="both", expand=True)

        self.detail_frame = ttk.Frame(self.detail_canvas, padding=(8, 4))
        self.detail_window = self.detail_canvas.create_window((0, 0), window=self.detail_frame, anchor="nw")
        self.detail_frame.bind("<Configure>", self._on_detail_configure)
        self.detail_canvas.bind("<Configure>", self._on_canvas_configure)

        search_bar = ttk.Frame(search_tab, padding=8)
        search_bar.pack(fill="x")
        ttk.Label(search_bar, text="Tìm hệ tọa độ:").pack(side="left")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(search_bar, textvariable=self.search_var)
        ent.pack(side="left", fill="x", expand=True, padx=6)
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

        self.tree.selection_set(self.tree.get_children(ge_root)[0])
        self._on_tree_select(None)

    def _on_detail_configure(self, _event) -> None:
        self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.detail_canvas.itemconfigure(self.detail_window, width=event.width)

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
            ("Name", cs.name),
            ("Description", cs.description),
            ("Projection", cs.projection),
            ("Source", cs.source),
            ("Units", cs.units),
            ("Central Meridian", cs.central_meridian),
            ("Origin Latitude", cs.origin_latitude),
            ("Scale Reduction", cs.scale_reduction),
            ("False Easting", cs.false_easting),
            ("False Northing", cs.false_northing),
            ("Quadrant", cs.quadrant),
            ("Minimum Longitude", cs.minimum_longitude),
            ("Maximum Longitude", cs.maximum_longitude),
            ("Minimum Latitude", cs.minimum_latitude),
            ("Maximum Latitude", cs.maximum_latitude),
        ])
        self._section("Datum", [
            ("Name", cs.datum_name),
            ("Description", cs.datum_description),
            ("Source", cs.source),
            ("Conversion Method", cs.conversion_method),
            ("Delta X", cs.delta_x),
            ("Delta Y", cs.delta_y),
            ("Delta Z", cs.delta_z),
            ("X Rotation", cs.x_rotation),
            ("Y Rotation", cs.y_rotation),
            ("Z Rotation", cs.z_rotation),
            ("Scale", cs.scale),
        ])
        self._section("Ellipsoid", [
            ("Name", cs.ellipsoid_name),
            ("Description", cs.ellipsoid_description),
            ("Equatorial Radius", cs.equatorial_radius),
            ("Polar Radius", cs.polar_radius),
            ("Eccentricity", cs.eccentricity),
        ])

    def _section(self, title: str, rows: List[tuple]) -> None:
        outer = ttk.LabelFrame(self.detail_frame, text=title, padding=8)
        outer.pack(fill="x", expand=True, pady=5)
        for r, (k, v) in enumerate(rows):
            ttk.Label(outer, text=k, width=28).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Label(outer, text=v, font=("Segoe UI", 9, "bold")).grid(row=r, column=1, sticky="w", pady=2)
        outer.columnconfigure(1, weight=1)

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
        idx = self.search_result.curselection()
        if not idx:
            return
        key = self._search_keys[idx[0]]
        self.selected_key = key
        self._show_details(self.library.items[key])

    def _add_favorite(self) -> None:
        if not self.selected_key:
            return
        self.library.add_favorite(self.selected_key)
        self._populate_tree()

    def _ok(self) -> None:
        if not self.selected_key:
            messagebox.showwarning(APP_NAME, "Chưa chọn hệ tọa độ.")
            return
        cs = self.library.items[self.selected_key]
        self.on_select(cs)
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
        if self.crs_library.dty_path.exists():
            self._log(f"Đã tìm thấy VN2000.dty: {self.crs_library.dty_path.name}")
        else:
            self._log("Chưa thấy VN2000.dty, đang dùng dữ liệu mẫu tích hợp.")
        self._connect_autocad_startup()

    def _get_app_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _place_bottom_right(self) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - WINDOW_WIDTH - WINDOW_MARGIN_X
        y = screen_h - WINDOW_HEIGHT - WINDOW_MARGIN_Y
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
            btn = ttk.Button(button_frame, text=text, command=command)
            btn.grid(row=0, column=i, padx=3, pady=3, sticky="nsew")
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
        # Bước tiếp theo sẽ lưu thông tin này vào DWG bằng NOD/XData theo mô tả chức năng sau.

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

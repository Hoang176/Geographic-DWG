# -*- coding: utf-8 -*-
"""Launcher for Geographic.py with Google Earth image tile insertion enabled.

This file keeps the existing Geographic.py intact and monkey-patches its UI at
runtime to add the command:

    Ảnh Google Earth

Default behavior:
- zoom = 18,
- no options dialog,
- no settings prompt,
- select two ModelSpace points,
- download Google satellite tiles,
- save under <DWG folder>/GE_images,
- attach raster with relative path where AutoCAD accepts it.

Run this instead of Geographic.py:

    python Geographic_with_google_image.py
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import Geographic as base
from google_earth_tiles import DEFAULT_GOOGLE_ZOOM, insert_google_earth_image


_ORIGINAL_BUILD_UI = base.GeographicApp._build_ui


def _patched_build_ui(self):
    """Use two button rows so no command is hidden on small screens."""
    try:
        self.root.geometry("820x360")
        self.root.resizable(False, False)
    except Exception:
        pass

    main = ttk.Frame(self.root, padding=8)
    main.pack(fill="both", expand=True)

    button_frame = ttk.Frame(main)
    button_frame.pack(fill="x")

    row1 = [
        ("Hệ tọa độ", self.on_coordinate_system),
        ("Xuất KML/KMZ", self.on_export_kml_kmz),
        ("Nhập KML/KMZ", self.on_import_kml_kmz),
    ]
    row2 = [
        ("Lấy từ GG Earth", self.on_get_from_google_earth),
        ("Ảnh Google Earth", self.on_google_earth_image),
        ("Lựa chọn", self.on_selection),
    ]

    for row_index, row_buttons in enumerate((row1, row2)):
        for col_index, (text, command) in enumerate(row_buttons):
            ttk.Button(button_frame, text=text, command=command).grid(
                row=row_index,
                column=col_index,
                padx=3,
                pady=3,
                sticky="nsew",
            )
            button_frame.columnconfigure(col_index, weight=1, uniform="button_col")

    ttk.Label(main, text="Thông báo").pack(anchor="w", pady=(8, 2))
    msg_frame = ttk.Frame(main)
    msg_frame.pack(fill="both", expand=True)
    self.message = tk.Text(msg_frame, height=11, wrap="word", state="disabled", font=("Consolas", 10))
    self.message.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(msg_frame, command=self.message.yview)
    scrollbar.pack(side="right", fill="y")
    self.message.configure(yscrollcommand=scrollbar.set)


def _on_google_earth_image(self):
    """Download and insert Google Earth satellite image for 2 picked points."""
    if not self.ensure_autocad():
        self._log("Ảnh Google Earth: chưa có kết nối AutoCAD.")
        messagebox.showwarning(base.APP_NAME, "Chưa kết nối được AutoCAD đang chạy.")
        return
    self._refresh_active_document()
    if self.doc is None:
        self._log("Ảnh Google Earth: không có bản vẽ active.")
        messagebox.showwarning(base.APP_NAME, "Không có bản vẽ active trong AutoCAD.")
        return
    cs = self._require_document_crs()
    if cs is None:
        return
    try:
        transformer = base.CoordinateTransformer(cs)
        self._log(f"Ảnh Google Earth: dùng zoom mặc định {DEFAULT_GOOGLE_ZOOM}.")
        result = insert_google_earth_image(
            self.acad,
            self.doc,
            transformer,
            zoom=DEFAULT_GOOGLE_ZOOM,
            log=self._log,
        )
    except Exception as exc:
        self._log(f"Lấy ảnh Google Earth thất bại: {exc}")
        messagebox.showerror(base.APP_NAME, f"Lấy ảnh Google Earth thất bại:\n{exc}")
        return

    self._log(
        "Đã chèn ảnh Google Earth: "
        f"{result.image_path.name}; zoom={result.zoom}; "
        f"{result.tile_count} tile; {result.pixel_width}x{result.pixel_height}px; "
        f"path tương đối: {result.relative_path}"
    )


def install_patch():
    base.GeographicApp._build_ui = _patched_build_ui
    base.GeographicApp.on_google_earth_image = _on_google_earth_image


def main():
    install_patch()
    root = tk.Tk()
    base.GeographicApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

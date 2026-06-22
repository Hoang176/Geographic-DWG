# -*- coding: utf-8 -*-
"""Geographic main launcher with Google Earth image integration.

Run:
    python Geographic.py

This launcher loads the preserved Geographic implementation and patches only
its main button layout/command list:
- two rows of buttons,
- no change to the existing window size,
- adds "Ảnh Google Earth" with default zoom 18,
- no settings dialog and no extra choices.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from geographic_base_loader import load_base_module
from google_earth_tiles import DEFAULT_GOOGLE_ZOOM, insert_google_earth_image


base = load_base_module()

# Re-export common names for code that imports Geographic.py.
APP_NAME = base.APP_NAME
CoordinateSystem = base.CoordinateSystem
CoordinateTransformer = base.CoordinateTransformer
CoordinateSystemLibrary = base.CoordinateSystemLibrary
CoordinateSystemDialog = base.CoordinateSystemDialog
GeographicApp = base.GeographicApp


def _patched_build_ui(self) -> None:
    """Build the original UI, but split commands into two button rows."""
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

    for row_index, buttons in enumerate((row1, row2)):
        for col_index, (text, command) in enumerate(buttons):
            ttk.Button(button_frame, text=text, command=command).grid(
                row=row_index,
                column=col_index,
                padx=3,
                pady=3,
                sticky="nsew",
            )
            button_frame.columnconfigure(col_index, weight=1, uniform="geo_buttons")

    ttk.Label(main, text="Thông báo").pack(anchor="w", pady=(8, 2))
    msg_frame = ttk.Frame(main)
    msg_frame.pack(fill="both", expand=True)

    self.message = tk.Text(
        msg_frame,
        height=10,
        wrap="word",
        state="disabled",
        font=("Consolas", 10),
    )
    self.message.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(msg_frame, command=self.message.yview)
    scrollbar.pack(side="right", fill="y")
    self.message.configure(yscrollcommand=scrollbar.set)


def _on_google_earth_image(self) -> None:
    """Download and insert a Google satellite image with default settings."""
    if not self.ensure_autocad():
        self._log("Ảnh Google Earth: chưa có kết nối AutoCAD.")
        messagebox.showwarning(APP_NAME, "Chưa kết nối được AutoCAD đang chạy.")
        return

    self._refresh_active_document()
    if self.doc is None:
        self._log("Ảnh Google Earth: không có bản vẽ active.")
        messagebox.showwarning(APP_NAME, "Không có bản vẽ active trong AutoCAD.")
        return

    cs = self._require_document_crs()
    if cs is None:
        return

    try:
        transformer = base.CoordinateTransformer(cs)
        self._log(f"Ảnh Google Earth: zoom mặc định {DEFAULT_GOOGLE_ZOOM}; không hỏi thêm cài đặt.")
        result = insert_google_earth_image(
            self.acad,
            self.doc,
            transformer,
            zoom=DEFAULT_GOOGLE_ZOOM,
            log=self._log,
        )
    except Exception as exc:
        self._log(f"Lấy ảnh Google Earth thất bại: {exc}")
        messagebox.showerror(APP_NAME, f"Lấy ảnh Google Earth thất bại:\n{exc}")
        return

    self._log(
        "Đã chèn ảnh Google Earth: "
        f"{result.image_path.name}; zoom={result.zoom}; "
        f"{result.tile_count} tile; {result.pixel_width}x{result.pixel_height}px; "
        f"path tương đối: {result.relative_path}"
    )


def _install_google_earth_image_patch() -> None:
    GeographicApp._build_ui = _patched_build_ui
    GeographicApp.on_google_earth_image = _on_google_earth_image


def main() -> None:
    _install_google_earth_image_patch()
    root = tk.Tk()
    GeographicApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

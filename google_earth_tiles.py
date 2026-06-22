# -*- coding: utf-8 -*-
"""Download Google satellite tiles and insert the stitched image into AutoCAD.

Default behavior for Geographic DWG:
- no settings dialog,
- zoom = 18,
- choose 2 points in AutoCAD ModelSpace,
- transform DWG CRS to WGS84,
- download/stitch Google satellite tiles,
- save image under the DWG folder,
- attach raster using a relative image path.

Requirements on the user's machine:
    pip install pillow

Internet access is required when running the command.
"""

from __future__ import annotations

import io
import math
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

try:
    from PIL import Image
except Exception:  # pragma: no cover - handled at runtime
    Image = None

Point3 = Tuple[float, float, float]
LogFn = Callable[[str], None]

DEFAULT_GOOGLE_ZOOM = 18
GOOGLE_TILE_URL = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
TILE_SIZE = 256


@dataclass
class GoogleImageResult:
    image_path: Path
    relative_path: str
    zoom: int
    tile_count: int
    pixel_width: int
    pixel_height: int
    insertion_point: Point3
    scale_factor: float


def _as_point3(value: Sequence[float]) -> Point3:
    vals = list(value)
    while len(vals) < 3:
        vals.append(0.0)
    return float(vals[0]), float(vals[1]), float(vals[2])


def _clip_lat(lat: float) -> float:
    return max(-85.05112878, min(85.05112878, float(lat)))


def lonlat_to_global_pixel(lon: float, lat: float, zoom: int) -> Tuple[float, float]:
    lat = _clip_lat(lat)
    sin_lat = math.sin(math.radians(lat))
    scale = TILE_SIZE * (2 ** zoom)
    x = (float(lon) + 180.0) / 360.0 * scale
    y = (0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)) * scale
    return x, y


def global_pixel_to_tile(px: float, py: float) -> Tuple[int, int]:
    return int(math.floor(px / TILE_SIZE)), int(math.floor(py / TILE_SIZE))


def download_tile(x: int, y: int, z: int, timeout: int = 20):
    if Image is None:
        raise RuntimeError("Thiếu Pillow. Cài bằng lệnh: pip install pillow")
    url = GOOGLE_TILE_URL.format(x=x, y=y, z=z)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Geographic-DWG"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def stitch_google_satellite(lon_min: float, lat_min: float, lon_max: float, lat_max: float, zoom: int, log: Optional[LogFn] = None):
    if Image is None:
        raise RuntimeError("Thiếu Pillow. Cài bằng lệnh: pip install pillow")
    west, east = sorted([float(lon_min), float(lon_max)])
    south, north = sorted([float(lat_min), float(lat_max)])
    px_w, py_n = lonlat_to_global_pixel(west, north, zoom)
    px_e, py_s = lonlat_to_global_pixel(east, south, zoom)
    tx_min, ty_min = global_pixel_to_tile(px_w, py_n)
    tx_max, ty_max = global_pixel_to_tile(px_e, py_s)
    cols = tx_max - tx_min + 1
    rows = ty_max - ty_min + 1
    if cols <= 0 or rows <= 0:
        raise RuntimeError("Vùng chọn không hợp lệ để tải ảnh Google Earth.")
    if cols * rows > 400:
        raise RuntimeError(f"Vùng chọn quá lớn ở zoom {zoom}: {cols * rows} tiles. Hãy chọn vùng nhỏ hơn.")
    mosaic = Image.new("RGB", (cols * TILE_SIZE, rows * TILE_SIZE), (255, 255, 255))
    count = 0
    for ty in range(ty_min, ty_max + 1):
        for tx in range(tx_min, tx_max + 1):
            tile = download_tile(tx, ty, zoom)
            mosaic.paste(tile, ((tx - tx_min) * TILE_SIZE, (ty - ty_min) * TILE_SIZE))
            count += 1
            if log:
                log(f"Đã tải tile Google Earth {count}/{cols * rows}: z={zoom}, x={tx}, y={ty}")
    left = int(round(px_w - tx_min * TILE_SIZE))
    top = int(round(py_n - ty_min * TILE_SIZE))
    right = int(round(px_e - tx_min * TILE_SIZE))
    bottom = int(round(py_s - ty_min * TILE_SIZE))
    left = max(0, min(mosaic.width - 1, left))
    top = max(0, min(mosaic.height - 1, top))
    right = max(left + 1, min(mosaic.width, right))
    bottom = max(top + 1, min(mosaic.height, bottom))
    cropped = mosaic.crop((left, top, right, bottom))
    return cropped, count


def _dwg_folder(doc) -> Path:
    try:
        fullname = Path(str(doc.FullName))
        if fullname.parent.exists():
            return fullname.parent
    except Exception:
        pass
    return Path.cwd()


def _relative_to_dwg(path: Path, doc) -> str:
    folder = _dwg_folder(doc)
    try:
        return os.path.relpath(str(path), str(folder))
    except Exception:
        return str(path)


def _com_point(point: Point3):
    try:
        import pythoncom
        import win32com.client
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in point))
    except Exception:
        return tuple(float(v) for v in point)


def select_two_modelspace_points(doc, log: Optional[LogFn] = None) -> Tuple[Point3, Point3]:
    util = doc.Utility
    if log:
        log("Chọn điểm góc thứ nhất trên ModelSpace để lấy ảnh Google Earth.")
    p1 = _as_point3(util.GetPoint(None, "\nChọn điểm góc thứ nhất vùng ảnh Google Earth: "))
    if log:
        log("Chọn điểm góc đối diện trên ModelSpace.")
    p2 = _as_point3(util.GetPoint(_com_point(p1), "\nChọn điểm góc đối diện vùng ảnh Google Earth: "))
    return p1, p2


def insert_google_earth_image(acad, doc, coordinate_transformer, zoom: int = DEFAULT_GOOGLE_ZOOM, log: Optional[LogFn] = None) -> GoogleImageResult:
    """Main command used by GeographicApp.

    coordinate_transformer must expose to_wgs84(point) -> (lon, lat, z).
    """
    if Image is None:
        raise RuntimeError("Thiếu Pillow. Cài bằng lệnh: pip install pillow")
    log = log or (lambda text: None)
    p1, p2 = select_two_modelspace_points(doc, log)
    ll1 = coordinate_transformer.to_wgs84(p1)
    ll2 = coordinate_transformer.to_wgs84(p2)
    lon_min, lon_max = sorted([ll1[0], ll2[0]])
    lat_min, lat_max = sorted([ll1[1], ll2[1]])
    log(f"Vùng WGS84: Lon {lon_min:.8f} -> {lon_max:.8f}; Lat {lat_min:.8f} -> {lat_max:.8f}; zoom={zoom}")
    image, tile_count = stitch_google_satellite(lon_min, lat_min, lon_max, lat_max, zoom, log)
    folder = _dwg_folder(doc) / "GE_images"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    try:
        stem = Path(str(doc.Name)).stem
    except Exception:
        stem = "Drawing"
    image_path = folder / f"{stem}_GoogleEarth_z{zoom}_{stamp}.jpg"
    image.save(image_path, quality=95)
    rel_path = _relative_to_dwg(image_path, doc)
    x_min, x_max = sorted([p1[0], p2[0]])
    y_min, y_max = sorted([p1[1], p2[1]])
    width_dwg = max(1e-9, x_max - x_min)
    scale = width_dwg / max(1, image.width)
    insertion = (x_min, y_min, min(p1[2], p2[2]))
    try:
        raster = doc.ModelSpace.AddRaster(rel_path, _com_point(insertion), scale, 0.0)
    except Exception:
        raster = doc.ModelSpace.AddRaster(str(image_path), _com_point(insertion), scale, 0.0)
    try:
        raster.Name = f"GoogleEarth_z{zoom}"
    except Exception:
        pass
    try:
        doc.Regen(1)
    except Exception:
        pass
    return GoogleImageResult(image_path, rel_path, zoom, tile_count, image.width, image.height, insertion, scale)

# -*- coding: utf-8 -*-
"""Load the preserved full Geographic.py implementation.

This loader lets the main Geographic.py act as the integrated launcher while
keeping the previous large implementation available from the repository blob.
A local cache is written beside the app after the first successful load.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from types import ModuleType

REPO_FULL_NAME = "Hoang176/Geographic-DWG"
BASE_BLOB_SHA = "5b28f03a993b6a6f0d22196828d04408d35e2c20"
CACHE_FILE = "Geographic_base_cached.py"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _download_base_source() -> str:
    url = f"https://api.github.com/repos/{REPO_FULL_NAME}/git/blobs/{BASE_BLOB_SHA}"
    request = urllib.request.Request(url, headers={"User-Agent": "Geographic-DWG"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload.get("content", "")
    encoding = payload.get("encoding", "base64")
    if encoding != "base64" or not content:
        raise RuntimeError("Không tải được mã nguồn Geographic gốc từ GitHub blob.")
    return base64.b64decode(content).decode("utf-8")


def _ensure_cache() -> Path:
    cache_path = _app_dir() / CACHE_FILE
    if cache_path.exists() and cache_path.stat().st_size > 10000:
        return cache_path
    source = _download_base_source()
    cache_path.write_text(source, encoding="utf-8")
    return cache_path


def load_base_module() -> ModuleType:
    cache_path = _ensure_cache()
    module_name = "geographic_base_cached"
    spec = importlib.util.spec_from_file_location(module_name, cache_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Không nạp được module nền từ {cache_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

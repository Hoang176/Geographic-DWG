# -*- coding: utf-8 -*-
"""Geographic main launcher restored to the previous application behavior.

This restores Geographic.py so running:

    python Geographic.py

loads and runs the preserved pre-Google-image implementation. The newer helper
files remain in the repository, but the main app no longer patches in the
Google Earth image button.
"""

from __future__ import annotations

import tkinter as tk

from geographic_base_loader import load_base_module


base = load_base_module()

# Re-export common names for code that imports Geographic.py.
APP_NAME = base.APP_NAME
CoordinateSystem = base.CoordinateSystem
CoordinateTransformer = base.CoordinateTransformer
CoordinateSystemLibrary = base.CoordinateSystemLibrary
CoordinateSystemDialog = base.CoordinateSystemDialog
GeographicApp = base.GeographicApp


def main() -> None:
    root = tk.Tk()
    GeographicApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""
__main__.py — Entry point ModbusScan Pro.

Cara menjalankan (semua valid, nama folder bebas):
  python NutShaker/
  python NutShaker/ --cli
  python -m NutShaker
  python NutShaker/__main__.py
"""

import os
import sys

# Tambahkan folder ini ke sys.path agar semua modul sibling
# bisa di-import secara absolut tanpa perlu package name.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def main() -> None:
    force_cli = "--cli" in sys.argv

    if not force_cli:
        try:
            import tkinter as _tk
            from gui import ModbusScanGUI   # absolut, bukan .gui

            root = _tk.Tk()
            ModbusScanGUI(root)
            root.mainloop()
            return
        except ImportError as e:
            if "tkinter" in str(e).lower():
                print("[ModbusScan Pro] tkinter tidak tersedia — beralih ke mode CLI.\n")
            else:
                raise

    from cli import run_cli     # absolut, bukan .cli
    run_cli()


if __name__ == "__main__":
    main()

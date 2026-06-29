"""
PyInstaller 런타임 훅 — _internal/ 경로를 sys.path에 추가해
번들된 paddle/paddleocr 패키지를 import 가능하게 만든다.
"""
import sys
import os
from pathlib import Path

if getattr(sys, 'frozen', False):
    internal = Path(sys._MEIPASS)
    # _internal 자체가 sys.path에 없으면 추가
    s = str(internal)
    if s not in sys.path:
        sys.path.insert(0, s)

    # paddle DLL 검색 경로 등록
    dll_dir = internal / 'paddle' / 'libs'
    if dll_dir.exists() and hasattr(os, 'add_dll_directory'):
        try:
            os.add_dll_directory(str(dll_dir))
        except OSError:
            pass

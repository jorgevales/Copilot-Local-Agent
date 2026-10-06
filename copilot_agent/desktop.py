"""Approved Windows display capture and independent viewer verification helpers."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Physical display capture and window inspection require a visible Windows desktop")


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def enumerate_displays() -> list[dict]:
    """Return physical monitor bounds ordered by the Windows DISPLAY number."""
    _require_windows()
    user32 = ctypes.windll.user32
    monitors = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def collect(handle, _dc, _rect, _data):
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return True
        match = re.search(r"DISPLAY(\d+)$", info.szDevice, re.IGNORECASE)
        number = int(match.group(1)) if match else len(monitors) + 1
        monitors.append({"display_index": number, "device": info.szDevice,
                         "bounds": {"left": info.rcMonitor.left, "top": info.rcMonitor.top,
                                    "right": info.rcMonitor.right, "bottom": info.rcMonitor.bottom},
                         "work_area": {"left": info.rcWork.left, "top": info.rcWork.top,
                                       "right": info.rcWork.right, "bottom": info.rcWork.bottom},
                         "primary": bool(info.dwFlags & 1)})
        return True

    callback = callback_type(collect)
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise ctypes.WinError()
    return sorted(monitors, key=lambda item: item["display_index"])


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def capture_display(display_index: int, output_path: str | os.PathLike) -> dict:
    """Capture one complete physical display to a new PNG using Windows GDI."""
    _require_windows()
    display = next((item for item in enumerate_displays() if item["display_index"] == display_index), None)
    if display is None:
        raise RuntimeError("Requested physical display is not available: " + str(display_index))
    bounds = display["bounds"]
    width, height = bounds["right"] - bounds["left"], bounds["bottom"] - bounds["top"]
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    previous = gdi32.SelectObject(memory, bitmap)

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]

    try:
        if not gdi32.BitBlt(memory, 0, 0, width, height, screen, bounds["left"], bounds["top"], 0x40CC0020):
            raise ctypes.WinError()
        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), 0) != height:
            raise ctypes.WinError()
        raw = memoryview(pixels.raw)
        rows = bytearray()
        stride = width * 4
        for row_index in range(height):
            row = raw[row_index * stride:(row_index + 1) * stride]
            rows.append(0)
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
            rows.extend(rgb)
        png = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
               + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + _png_chunk(b"IEND", b""))
        target = Path(output_path)
        with target.open("xb") as stream:
            stream.write(png)
        return {"display_index": display_index, "device": display["device"], "path": str(target.resolve()),
                "width": width, "height": height, "size": len(png)}
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)


def _tile_bounds(display: dict, count: int) -> list[dict]:
    area = display["work_area"]
    columns = min(count, max(1, math.ceil(math.sqrt(count))))
    rows = math.ceil(count / columns)
    width = max(240, (area["right"] - area["left"]) // columns)
    height = max(180, (area["bottom"] - area["top"]) // rows)
    result = []
    for index in range(count):
        column, row = index % columns, index // columns
        left, top = area["left"] + column * width, area["top"] + row * height
        right = area["right"] if column == columns - 1 else min(area["right"], left + width)
        bottom = area["bottom"] if row == rows - 1 else min(area["bottom"], top + height)
        result.append({"left": left, "top": top, "right": right, "bottom": bottom})
    return result


def launch_viewers(viewers: list[dict], interpreter: str) -> list[dict]:
    """Launch approved persistent viewers in a tiled layout on their displays."""
    _require_windows()
    displays = {item["display_index"]: item for item in enumerate_displays()}
    module = Path(__file__).with_name("image_viewer.py").resolve()
    launched = []
    try:
        for display_index in sorted({item["display_index"] for item in viewers}):
            selected = [item for item in viewers if item["display_index"] == display_index]
            if display_index not in displays:
                raise RuntimeError("Approved target display is unavailable: " + str(display_index))
            for item, bounds in zip(selected, _tile_bounds(displays[display_index], len(selected))):
                command = [interpreter, "-I", str(module), item["image_path"], item["title"],
                           str(bounds["left"]), str(bounds["top"]), str(bounds["right"] - bounds["left"]),
                           str(bounds["bottom"] - bounds["top"])]
                creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, close_fds=True, creationflags=creation_flags)
                launched.append({"pid": process.pid, "title": item["title"], "display_index": display_index,
                                 "image_path": item["image_path"], "persistent": True, "process": process,
                                 "requested_bounds": bounds})
    except Exception:
        for item in launched:
            try:
                item["process"].terminate()
            except OSError:
                pass
        raise
    return launched


def inspect_windows(expected: list[dict], wait_seconds: float = 8.0) -> dict:
    """Independently inspect exact visible titles and final bounds."""
    _require_windows()
    user32 = ctypes.windll.user32
    displays = {item["display_index"]: item for item in enumerate_displays()}
    wanted = {item["title"]: item for item in expected}

    def snapshot():
        found = {}
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def collect(handle, _data):
            if not user32.IsWindowVisible(handle):
                return True
            length = user32.GetWindowTextLengthW(handle)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            if buffer.value not in wanted:
                return True
            rect = wintypes.RECT()
            if user32.GetWindowRect(handle, ctypes.byref(rect)):
                found[buffer.value] = {"title": buffer.value, "visible": True,
                                       "bounds": {"left": rect.left, "top": rect.top,
                                                  "right": rect.right, "bottom": rect.bottom},
                                       "hwnd": int(handle)}
            return True

        callback = callback_type(collect)
        user32.EnumWindows(callback, 0)
        return found

    deadline = time.monotonic() + wait_seconds
    found = {}
    while time.monotonic() < deadline:
        found = snapshot()
        if set(found) == set(wanted):
            break
        time.sleep(0.1)
    windows = []
    for title, item in wanted.items():
        observed = found.get(title, {"title": title, "visible": False, "bounds": None, "hwnd": None})
        display = displays.get(item["display_index"])
        bounds = observed["bounds"]
        target = display["bounds"] if display else None
        contained = bool(bounds and target and bounds["left"] >= target["left"] and bounds["top"] >= target["top"]
                         and bounds["right"] <= target["right"] and bounds["bottom"] <= target["bottom"])
        windows.append({**observed, "display_index": item["display_index"], "contained_on_display": contained,
                        "image_path": item["image_path"]})
    return {"ok": len(windows) == len(expected) and all(item["visible"] and item["contained_on_display"] for item in windows),
            "display_count": len(displays), "displays": list(displays.values()), "windows": windows}

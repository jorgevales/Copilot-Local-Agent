"""Minimal persistent image viewer launched only by an approved Code Runner plan."""
from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 7:
        return 2
    image, title = Path(sys.argv[1]).resolve(), sys.argv[2]
    left, top, width, height = map(int, sys.argv[3:])
    if not image.is_file() or image.suffix.casefold() != ".png" or not title or any(ord(char) < 32 for char in title):
        return 2
    import tkinter as tk
    root = tk.Tk()
    root.title(title)
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.minsize(240, 180)
    canvas = tk.Canvas(root, highlightthickness=0, background="#111827")
    canvas.pack(fill="both", expand=True)
    photo = tk.PhotoImage(file=str(image))

    def render(_event=None):
        canvas.delete("image")
        available_width, available_height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        factor = max(1, (photo.width() + available_width - 1) // available_width,
                     (photo.height() + available_height - 1) // available_height)
        shown = photo.subsample(factor, factor) if factor > 1 else photo
        canvas._shown_image = shown
        canvas.create_image(available_width // 2, available_height // 2, image=shown, anchor="center", tags="image")

    canvas.bind("<Configure>", render)
    root.after(0, render)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

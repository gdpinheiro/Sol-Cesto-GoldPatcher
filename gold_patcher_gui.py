#!/usr/bin/env python3
"""
gold_patcher_gui.py — GUI front-end for gold_patcher.py (SolCesto save editor).
Requires: pip install customtkinter pillow
"""

import io
import shutil
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from gold_patcher import GOLD_PREFIX, encode_gold_varint, find_save_dir, patch_file

# ── Palette (pulled from the logo: dark parchment bg, maroon, gold) ──
BG        = "#1a1008"   # near-black warm brown — window background
CARD      = "#251608"   # slightly lighter card background
ENTRY_BG  = "#0f0b04"   # very dark for input fields
BORDER    = "#5c3410"   # warm brown border
GOLD      = "#c9921a"   # primary gold accent (button, highlights)
GOLD_HOV  = "#e0a820"   # hover gold
MAROON    = "#6b1a1a"   # deep maroon (browse button)
MAROON_H  = "#8a2222"
TEXT      = "#f0deb0"   # warm parchment white
MUTED     = "#8a7050"   # muted gold-brown for labels / hints
LOG_BG    = "#0d0904"   # darkest — log area

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SolCesto Gold Patcher")
        self.geometry("500x530")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        _HERE = Path(__file__).parent

        # ── Logo (centered) ───────────────────────────────────────
        logo_img = ctk.CTkImage(
            light_image=Image.open(_HERE / "logo.png"),
            dark_image=Image.open(_HERE / "logo.png"),
            size=(220, 110),
        )
        ctk.CTkLabel(self, image=logo_img, text="", fg_color="transparent").pack(
            pady=(24, 0)
        )

        # Character (optional, bottom-right corner overlay via place)
        char_path = _HERE / "character.png"
        if char_path.exists():
            char_img = ctk.CTkImage(
                light_image=Image.open(char_path),
                dark_image=Image.open(char_path),
                size=(64, 72),
            )
            ctk.CTkLabel(self, image=char_img, text="", fg_color="transparent").place(
                relx=1.0, rely=1.0, x=-12, y=-12, anchor="se"
            )

        # Subtitle
        ctk.CTkLabel(
            self,
            text="save editor  •  originals backed up to ./backup/",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            fg_color="transparent",
        ).pack(pady=(4, 16))

        # ── Input card ────────────────────────────────────────────
        card = ctk.CTkFrame(
            self, corner_radius=12,
            fg_color=CARD,
            border_width=1,
            border_color=BORDER,
        )
        card.pack(padx=32, fill="x")

        LABEL_W = 100

        def card_row(label_text, widget_factory, pady=(8, 0)):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=pady)
            ctk.CTkLabel(
                row, text=label_text, width=LABEL_W, anchor="w",
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
                fg_color="transparent",
            ).pack(side="left")
            widget_factory(row)

        def make_entry(parent, placeholder):
            e = ctk.CTkEntry(
                parent,
                placeholder_text=placeholder,
                height=34,
                fg_color=ENTRY_BG,
                border_color=BORDER,
                border_width=1,
                text_color=TEXT,
                placeholder_text_color="#5a4030",
            )
            e.pack(side="left", fill="x", expand=True)
            return e

        self.entry_current = None
        self.entry_target  = None
        self.entry_dir     = None

        def build_current(row):
            self.entry_current = make_entry(row, "e.g. 100")

        def build_target(row):
            self.entry_target = make_entry(row, "e.g. 8190")

        def build_dir(row):
            self.entry_dir = make_entry(row, "auto-detect")
            ctk.CTkButton(
                row, text="…", width=34, height=34,
                fg_color=MAROON, hover_color=MAROON_H,
                text_color=TEXT, corner_radius=8,
                command=self._browse,
            ).pack(side="left", padx=(6, 0))

        card_row("Current gold", build_current, pady=(12, 0))
        card_row("Target gold",  build_target,  pady=(8, 0))
        card_row("Save folder",  build_dir,     pady=(8, 12))

        # ── Hint ──────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="Target must end in 0  •  range 1–63 → max 60  •  range 64–8191 → max 8190",
            font=ctk.CTkFont(size=10),
            text_color="#5a4030",
            fg_color="transparent",
        ).pack(pady=(10, 0))

        # ── Patch button ──────────────────────────────────────────
        self.btn = ctk.CTkButton(
            self, text="Patch Gold", height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=GOLD, hover_color=GOLD_HOV,
            text_color="#1a0c00",
            corner_radius=10,
            command=self._start,
        )
        self.btn.pack(padx=32, pady=12, fill="x")

        # ── Log ───────────────────────────────────────────────────
        self.log = ctk.CTkTextbox(
            self, height=136,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=LOG_BG,
            text_color="#b8a070",
            border_width=1,
            border_color=BORDER,
            corner_radius=8,
            state="disabled",
        )
        self.log.pack(padx=32, pady=(0, 24), fill="x")

        self._write("Ready — enter values above and click Patch Gold.\n")

    # ── helpers ───────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askdirectory(title="Select .indexeddb.leveldb folder")
        if path:
            self.entry_dir.delete(0, "end")
            self.entry_dir.insert(0, path)

    def _write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _busy(self, is_busy: bool):
        s = "disabled" if is_busy else "normal"
        self.btn.configure(state=s)
        self.entry_current.configure(state=s)
        self.entry_target.configure(state=s)

    # ── validation ────────────────────────────────────────────────

    def _validate(self):
        raw_cur = self.entry_current.get().strip()
        raw_tgt = self.entry_target.get().strip()

        if not raw_cur or not raw_tgt:
            self._write("[error] Both fields are required.")
            return None

        try:
            cur = int(raw_cur)
            tgt = int(raw_tgt)
        except ValueError:
            self._write("[error] Gold values must be whole numbers.")
            return None

        if cur <= 0 or tgt <= 0:
            self._write("[error] Gold values must be positive.")
            return None

        if tgt % 10 != 0:
            suggest = max((tgt // 10) * 10, 10)
            self._write(f"[error] Target must end in 0. Did you mean {suggest}?")
            return None

        try:
            cv = encode_gold_varint(cur)
            tv = encode_gold_varint(tgt)
        except ValueError as e:
            self._write(f"[error] {e}")
            return None

        if len(cv) != len(tv):
            rng = "1–63 (max target: 60)" if len(cv) == 1 else "64–8191 (max target: 8190)"
            self._write(
                f"[error] Byte-length mismatch.\n"
                f"        Current gold {cur} is in range {rng}.\n"
                f"        Target must be in the same range."
            )
            return None

        raw_dir = self.entry_dir.get().strip()
        return cur, tgt, Path(raw_dir) if raw_dir else None

    # ── patch flow ────────────────────────────────────────────────

    def _start(self):
        self._clear()
        args = self._validate()
        if args is None:
            return
        self._busy(True)
        threading.Thread(target=self._run, args=args, daemon=True).start()

    def _run(self, cur: int, tgt: int, save_dir):
        try:
            self._patch(cur, tgt, save_dir)
        finally:
            self.after(0, lambda: self._busy(False))

    def _patch(self, cur: int, tgt: int, save_dir):
        log = lambda msg: self.after(0, lambda m=msg: self._write(m))

        if save_dir is None:
            save_dir = find_save_dir()
            if save_dir is None:
                log(
                    "[error] Could not auto-detect save directory.\n"
                    "        Paste the path into the Save folder field.\n"
                    "        Expected:\n"
                    "        %LOCALAPPDATA%\\SolCesto\\User Data\\Default\\IndexedDB\\"
                    "<chrome-extension_...>.indexeddb.leveldb"
                )
                return
            log(f"[info]  Save directory: {save_dir}\n")
        elif not save_dir.exists():
            log(f"[error] Folder not found:\n        {save_dir}")
            return

        all_files = [f for f in save_dir.iterdir() if f.is_file()]
        log_files  = sorted(f for f in all_files if f.suffix == ".log")

        if not log_files:
            log(f"[error] No .log files found in:\n        {save_dir}")
            return

        log(f"[info]  Found {len(log_files)} log file(s): {[f.name for f in log_files]}")

        backup_dir = Path("./backup")
        work_dir   = Path("./save")
        backup_dir.mkdir(exist_ok=True)
        work_dir.mkdir(exist_ok=True)

        for f in all_files:
            shutil.copy2(f, backup_dir / f.name)
            shutil.copy2(f, work_dir / f.name)

        log(f"[info]  Backup saved to ./backup/  ({len(all_files)} file(s))")

        cv = encode_gold_varint(cur)
        tv = encode_gold_varint(tgt)
        log(f"[info]  {cur} → {(GOLD_PREFIX + cv).hex(' ').upper()}")
        log(f"[info]  {tgt} → {(GOLD_PREFIX + tv).hex(' ').upper()}\n")

        success = False
        for lf in sorted(work_dir.glob("*.log")):
            log(f"[scan]  {lf.name}")
            buf = io.StringIO()
            sys.stdout, old = buf, sys.stdout
            try:
                ok = patch_file(lf, cur, tgt)
            finally:
                sys.stdout = old
            for line in buf.getvalue().splitlines():
                log(f"        {line}")
            if ok:
                success = True

        if success:
            log(
                f"\n✓  Done — gold patched: {cur} → {tgt}\n\n"
                f"   Next steps:\n"
                f"   1. Close SolCesto completely.\n"
                f"   2. Copy all files from ./save/ to:\n"
                f"      {save_dir}\n"
                f"   3. Launch the game.\n\n"
                f"   To restore: copy files from ./backup/ back."
            )
        else:
            log(
                "\n✗  No files were patched.\n"
                "   • Make sure current gold matches your exact in-game amount.\n"
                "   • Close the game before running this tool.\n"
                "   • Originals are safe in ./backup/"
            )


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

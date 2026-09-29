"""Drag-and-drop GUI for converting audio files to CCITT G.711 u-law WAV.

Run:  python main.py
Drop audio files (or folders) onto the window, then click Convert.
The command-line version lives in converter.py.
"""

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from converter import convert, output_path_for

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".aifc", ".caf",
    ".flac", ".ogg", ".oga", ".opus", ".wma", ".mp4", ".mov", ".au", ".snd",
}
SUFFIX = "_ulaw"


class App:
    def __init__(self, root: TkinterDnD.Tk):
        self.root = root
        self.files: dict[str, Path] = {}  # tree item id -> source path
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title("CCITT u-law Converter")
        root.geometry("720x480")
        root.minsize(560, 360)

        self.output_dir = tk.StringVar(value="")
        self.overwrite = tk.BooleanVar(value=False)
        self.rate = tk.StringVar(value="8000")
        self.status = tk.StringVar(value="Drop audio files or folders onto the list, or click Add Files…")

        self._build()
        self._set_output_label()
        # Files dropped on the app's Dock/Finder icon (or opened with "Open With") arrive here.
        root.createcommand("::tk::mac::OpenDocument", lambda *paths: self.add_paths(Path(p) for p in paths))
        root.after(100, self._poll_events)

    # ---------- layout ----------

    def _build(self):
        pad = {"padx": 10, "pady": 6}
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        toolbar = ttk.Frame(main)
        toolbar.pack(fill="x", **pad)
        ttk.Button(toolbar, text="Add Files…", command=self.browse_files).pack(side="left")
        ttk.Button(toolbar, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Clear", command=self.clear).pack(side="left")

        list_frame = ttk.Frame(main)
        list_frame.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(list_frame, columns=("file", "status"), show="headings", selectmode="extended")
        self.tree.heading("file", text="File")
        self.tree.heading("status", text="Status")
        self.tree.column("file", width=480, anchor="w")
        self.tree.column("status", width=180, anchor="w")
        self.tree.tag_configure("ok", foreground="#1a7f37")
        self.tree.tag_configure("error", foreground="#cf222e")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected())

        # The whole window accepts drops, not just the list.
        for widget in (self.root, self.tree):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)

        options = ttk.LabelFrame(main, text="Output")
        options.pack(fill="x", **pad)
        row = ttk.Frame(options)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Save to:").pack(side="left")
        self.output_label = ttk.Label(row, foreground="#555")
        self.output_label.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(row, text="Same as Source", command=self.use_source_folder).pack(side="right")
        ttk.Button(row, text="Choose Folder…", command=self.choose_output_dir).pack(side="right", padx=6)

        row2 = ttk.Frame(options)
        row2.pack(fill="x", padx=8, pady=4)
        ttk.Label(row2, text="Sample rate:").pack(side="left")
        ttk.Combobox(row2, textvariable=self.rate, values=("8000", "16000"), width=7).pack(side="left", padx=6)
        ttk.Label(row2, text="Hz   (mono, 8-bit u-law; files saved as name_ulaw.wav)", foreground="#555").pack(side="left")
        ttk.Checkbutton(row2, text="Overwrite existing", variable=self.overwrite).pack(side="right")

        bottom = ttk.Frame(main)
        bottom.pack(fill="x", **pad)
        ttk.Label(bottom, textvariable=self.status).pack(side="left", fill="x", expand=True)
        self.open_button = ttk.Button(bottom, text="Show in Finder", command=self.reveal_output, state="disabled")
        self.open_button.pack(side="right", padx=6)
        self.convert_button = ttk.Button(bottom, text="Convert", command=self.start_conversion)
        self.convert_button.pack(side="right")
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

    # ---------- adding / removing files ----------

    def on_drop(self, event):
        self.add_paths(Path(p) for p in self.root.tk.splitlist(event.data))
        return event.action

    def browse_files(self):
        names = filedialog.askopenfilenames(
            title="Choose audio files",
            filetypes=[("Audio files", " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))), ("All files", "*")],
        )
        self.add_paths(Path(n) for n in names)

    def add_paths(self, paths):
        existing = set(self.files.values())
        added = 0
        for path in paths:
            candidates = (
                sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)
                if path.is_dir() else [path]
            )
            for p in candidates:
                if p in existing or p.stem.endswith(SUFFIX):
                    continue
                item = self.tree.insert("", "end", values=(str(p), "Ready"))
                self.files[item] = p
                existing.add(p)
                added += 1
        if added:
            self.status.set(f"{len(self.files)} file(s) ready.")

    def remove_selected(self):
        if self._busy():
            return
        for item in self.tree.selection():
            self.tree.delete(item)
            self.files.pop(item, None)
        self.status.set(f"{len(self.files)} file(s) ready.")

    def clear(self):
        if self._busy():
            return
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.progress["value"] = 0
        self.open_button.state(["disabled"])
        self.status.set("Drop audio files or folders onto the list, or click Add Files…")

    # ---------- output folder ----------

    def choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir.set(folder)
            self._set_output_label()

    def use_source_folder(self):
        self.output_dir.set("")
        self._set_output_label()

    def _set_output_label(self):
        self.output_label.configure(text=self.output_dir.get() or "Same folder as each source file")

    def reveal_output(self):
        target = self.output_dir.get() or getattr(self, "last_output", None)
        if target and sys.platform == "darwin":
            subprocess.run(["open", "-R", str(target)] if Path(target).is_file() else ["open", str(target)])

    # ---------- conversion ----------

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start_conversion(self):
        if self._busy() or not self.files:
            return
        try:
            rate = int(self.rate.get())
            if rate <= 0:
                raise ValueError
        except ValueError:
            self.status.set("Sample rate must be a positive whole number.")
            return

        out_dir = Path(self.output_dir.get()) if self.output_dir.get() else None
        jobs = list(self.files.items())
        for item, _ in jobs:
            self.tree.item(item, values=(self.tree.item(item, "values")[0], "Waiting…"), tags=())
        self.progress.configure(maximum=len(jobs), value=0)
        self.convert_button.state(["disabled"])
        self.open_button.state(["disabled"])
        self.status.set("Converting…")
        self.worker = threading.Thread(
            target=self._convert_all, args=(jobs, out_dir, rate, self.overwrite.get()), daemon=True)
        self.worker.start()

    def _convert_all(self, jobs, out_dir, rate, overwrite):
        """Runs on a background thread; reports back through self.events."""
        failures = 0
        for item, src in jobs:
            self.events.put(("status", item, "Converting…", ""))
            dest = output_path_for(src, out_dir, SUFFIX)
            try:
                if not src.is_file():
                    raise RuntimeError("file not found")
                if dest.exists() and not overwrite:
                    raise RuntimeError(f"{dest.name} exists")
                seconds = convert(src, dest, rate)
            except Exception as e:
                failures += 1
                self.events.put(("status", item, f"✗ {e}", "error"))
            else:
                self.events.put(("status", item, f"✓ {dest.name} ({seconds:.1f}s)", "ok"))
                self.events.put(("output", dest))
            self.events.put(("progress",))
        self.events.put(("done", len(jobs) - failures, len(jobs)))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "status":
                    _, item, text, tag = event
                    if self.tree.exists(item):
                        self.tree.item(item, values=(self.tree.item(item, "values")[0], text),
                                       tags=(tag,) if tag else ())
                elif kind == "output":
                    self.last_output = event[1]
                elif kind == "progress":
                    self.progress.step(1)
                elif kind == "done":
                    _, ok, total = event
                    self.status.set(f"Done — {ok} of {total} file(s) converted.")
                    self.convert_button.state(["!disabled"])
                    if ok:
                        self.open_button.state(["!disabled"])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main():
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

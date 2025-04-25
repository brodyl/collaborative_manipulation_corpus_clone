#!/usr/bin/env python3
"""
Interactive viewer for the ‘Natural-Language Instructions for Human-Robot
Collaborative Manipulation’ corpus (Scalise et al., 2018).

New in this version
-------------------
• On startup a popup explains: 
    – what each pane shows 
    – how images are ordered 
    – how the unique-instruction list can be re-sorted 
    – navigation shortcuts.
"""

import csv, re, sys, string
from collections import defaultdict, Counter
from pathlib import Path
from tkinter import (
    Tk, Canvas, Frame, BOTH, LEFT, RIGHT, Y, VERTICAL, Scrollbar,
    Listbox, Button, NW, YES, SINGLE, Label, StringVar, OptionMenu, Toplevel
)
from PIL import Image, ImageTk

# ---------- CONFIG --------------------------------------------------- #
ROOT        = Path(__file__).resolve().parent
CORPUS_CSV  = ROOT / "data" / "NLICorpusData.csv"
EVAL_CSV    = ROOT / "data" / "evaluationData.csv"
IMG_DIR     = ROOT / "study1_images_with_red_arrows"
VALID_EXTS  = {".png", ".jpg", ".jpeg"}
TITLE       = "Collaborative Manipulation Corpus Viewer"

# ---------- LAYOUT CONSTANTS ---------------------------------------- #
WINDOW_W          = 1700          # initial window width     (px)
WINDOW_H          = 720           # initial window height    (px)
IMG_FRACTION_W    = 0.40          # max % of window width for the image pane
IMG_FRACTION_H    = 0.95          # max % of window height   "
REDRAW_DELAY_MS   = 120           # ← how long to “wait” after last drag
LIST_FONT         = ("Consolas", 9)
CTRL_FONT         = ("Helvetica", 9, "bold")

# ---------- HELPERS -------------------------------------------------- #
name_pat = re.compile(r"Configuration_0*(\d+)_v0*(\d+)", re.I)

# strip every punctuation mark that might appear at the END of the line
_end_punct_re = re.compile(rf"[{re.escape(string.punctuation)}]+$")
_whitespace_re = re.compile(r"\s+")

def norm(s: str) -> str:
    """
    Canonicalise an instruction for equality / frequency checks:
      • trim leading/trailing whitespace
      • collapse internal whitespace (tabs, newlines, multiple spaces)
      • remove trailing punctuation (., !, ?, etc.)
      • convert to lowercase for case-insensitive comparison
    """
    s = s.strip()
    s = _whitespace_re.sub(" ", s)         # normalize all spacing
    s = _end_punct_re.sub("", s)           # remove ending punctuation
    return s.lower()


def canonical(raw: str) -> str:
    base = Path(raw).stem
    m = name_pat.match(base)
    return f"Configuration_{int(m.group(1))}_v{int(m.group(2))}" if m else base


def bool_from(val: str) -> bool:
    return val.strip().lower() in {"1", "true", "yes", "y", "correct"}


# ---------- LOAD CORPUS (Study-1) ------------------------------------ #
by_instr, difficulty_cnt = defaultdict(list), defaultdict(lambda: [0] * 5)
index_norm = {}  # Index → normalized instruction text

with CORPUS_CSV.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        scen = canonical(row["Scenario"])
        txt  = row["Instruction"]
        by_instr[scen].append(txt)
        index_norm[row["Index"]] = norm(txt)
        try:
            d = int(row["Difficulty"]); 0 < d < 6 and difficulty_cnt[scen].__setitem__(d - 1, difficulty_cnt[scen][d - 1] + 1)
        except Exception:
            pass

# ---------- LOAD EVALUATIONS (Study-2) ------------------------------- #
eval_stats = defaultdict(lambda: [0, 0])   # norm → [correct, wrong]

with EVAL_CSV.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        k = index_norm.get(row["Index"])
        if not k:
            continue
        eval_stats[k][0 if bool_from(row["Correctness"]) else 1] += 1

# ---------- MEAN DIFFICULTY PER SCENARIO ----------------------------- #
avg_diff = {
    s: sum((i + 1) * c for i, c in enumerate(cnt)) / sum(cnt) if sum(cnt) else float("inf")
    for s, cnt in difficulty_cnt.items()
}

# ---------- LIST IMAGES (easiest → hardest) -------------------------- #
images = []
for p in IMG_DIR.iterdir():
    if p.suffix.lower() not in VALID_EXTS:
        continue
    key = canonical(p.name)
    if key not in by_instr:
        continue
    m = name_pat.match(p.stem)
    order = (int(m.group(1)), int(m.group(2))) if m else (9999, 9999)
    images.append((p, key, avg_diff[key], order))

images.sort(key=lambda t: (t[2], t[3]))
if not images:
    sys.exit("No matching images found")

# ---------- UNIQUE-INSTRUCTION UTILITIES ----------------------------- #
def unique_rows(instrs):
    counter = Counter(norm(t) for t in instrs)
    disp_map = {norm(t): t.strip() for t in instrs[::-1]}  # last wins for display

    rows = []
    for k, count in counter.items():
        correct, wrong = eval_stats[k]
        acc = correct / (correct + wrong) if (correct + wrong) else None
        rows.append(dict(text=disp_map[k], count=count,
                         correct=correct, wrong=wrong, acc=acc))
    return rows


def sort_rows(rows, mode):
    if mode == "Count":
        return sorted(rows, key=lambda r: (-r["count"], r["text"].lower()))
    if mode == "Accuracy":
        return sorted(
            rows,
            key=lambda r: (-(r["acc"] if r["acc"] is not None else -1),
                           -r["count"], r["text"].lower())
        )
    if mode == "Length":
        return sorted(rows, key=lambda r: (len(r["text"]), r["text"].lower()))


# ---------- GUI CLASS ------------------------------------------------ #
class Viewer(Tk):
    def __init__(self, imgs):
        super().__init__()
        self.title(TITLE)
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self._resize_job = None   # ← new: id of the pending after-job

        # — key-bindings ------------------------------------------------
        self.bind("<Configure>", self._resize_widgets)
        self.bind("<Left>",  lambda *_: self.move(1))
        self.bind("<Right>", lambda *_: self.move(-1))
        self.bind("w", lambda e: self.listbox.yview_scroll(-1, "units"))
        self.bind("s", lambda e: self.listbox.yview_scroll( 1, "units"))
        self.bind("a", lambda e: self.listbox.xview_scroll(-1, "units"))
        self.bind("d", lambda e: self.listbox.xview_scroll( 1, "units"))

        # — top-level layout -------------------------------------------
        main = Frame(self)
        main.pack(fill=BOTH, expand=YES)

        # Image pane (left) – resizes with <Configure> ------------------
        self.canvas = Canvas(main, bg="black", highlightthickness=0)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=YES)

        # Right-hand column --------------------------------------------
        right = Frame(main, padx=3)
        right.pack(side=LEFT, fill=BOTH, expand=YES)

        Label(right, text="Order unique instructions by:",
              font=CTRL_FONT).pack(anchor="w")
        self.order_var = StringVar(value="Count")
        OptionMenu(right, self.order_var, "Count", "Accuracy", "Length",
                   command=lambda *_: self.refresh_list()).pack(anchor="w",
                                                                pady=(0, 4))

        list_fr = Frame(right); list_fr.pack(fill=BOTH, expand=YES)
        self.listbox = Listbox(list_fr, font=LIST_FONT, selectmode=SINGLE,
                               activestyle="none")
        sb = Scrollbar(list_fr, orient=VERTICAL, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=YES)
        sb.pack(side=RIGHT, fill=Y)

        self.stat_lbl = Label(right, font=("Courier", 10),
                              justify="left", padx=4, pady=4)
        self.stat_lbl.pack(pady=(6, 4), anchor="w")

        nav = Frame(self); nav.pack(pady=4)
        Button(nav, text="⟵ Previous", command=lambda: self.move(1)
               ).pack(side=LEFT, padx=8)
        Button(nav, text="Next ⟶", command=lambda: self.move(-1)
               ).pack(side=LEFT, padx=8)

        # — data --------------------------------------------------------
        self.imgs, self.idx, self._photo = imgs, 0, None
        self._cached_rows = []

        # — events ------------------------------------------------------
        self.bind("<Configure>", self._resize_widgets)
        self.render()
        self.after(200, self.show_help)

    # ---------- dynamic sizing --------------------------------------- #
    def _resize_widgets(self, event):
        """Resize canvas immediately, *schedule* image redraw."""
        w, h = event.width, event.height
        side = int(min(w * IMG_FRACTION_W, h * IMG_FRACTION_H))
        self.canvas.config(width=side, height=side)

        # debounce: cancel previous job & queue a new one
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(REDRAW_DELAY_MS, self._redraw_image)

    def _redraw_image(self):
        """Redraws the image using the actual canvas size."""
        self._resize_job = None  # reset the debounce tracker

        # Get actual canvas size
        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()

        # Sanity check: avoid triggering too early
        if c_w < 10 or c_h < 10:
            self._resize_job = self.after(REDRAW_DELAY_MS, self._redraw_image)
            return

        path, *_ = self.imgs[self.idx]
        img = Image.open(path)
        img.thumbnail((c_w, c_h), Image.LANCZOS)

        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=NW, image=self._photo)

    # ---------- render a scenario (unchanged except thumbnail size) --- #
    def render(self):
        path, scen, avg, _ = self.imgs[self.idx]

        # use current canvas size rather than a fixed 680×680 ------------
        side = max(32, int(self.canvas.winfo_width() or WINDOW_H
                           * IMG_FRACTION_H))
        img = Image.open(path); img.thumbnail((side, side), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=NW, image=self._photo)

        # uniques, stats (unchanged) ------------------------------------
        self._cached_rows = unique_rows(by_instr[scen])
        self.refresh_list()
        cnts, total = difficulty_cnt[scen], sum(difficulty_cnt[scen])
        self.stat_lbl.config(text="\n".join([
            f"Scenario difficulty (n={total}):",
            *[f"  {i}: {c}" for i, c in enumerate(cnts, 1)],
            f"  Avg: {avg:.1f}" if total else "  Avg: —"
        ]))
        self.title(f"{TITLE}   ({self.idx+1}/{len(self.imgs)})  {path.name}")

    # ---------- list refresh ---------- #
    def refresh_list(self):
        rows = sort_rows(self._cached_rows, self.order_var.get())
        self.listbox.delete(0, "end")
        for r in rows:
            acc_txt = f"{int(r['acc']*100):>3}%" if r["acc"] is not None else "--"
            self.listbox.insert(
                "end",
                f"{f'{r['count']}×':<3}  [✔ {r['correct']:<3} / ✖ {r['wrong']:<2} | "
                    f"{acc_txt:>4}]  {r['text']}"
            )
        self.listbox.yview_moveto(0)

    # ---------- nav ---------- #
    def move(self, delta):
        new = self.idx - delta
        if 0 <= new < len(self.imgs):
            self.idx = new
            self.render()

    # ---------- help popup ---------- #
    def show_help(self):
        top = Toplevel(self)
        top.title("About this viewer")
        top.resizable(False, False)

        msg = (
            "🔍  What you’re seeing\n"
            "• Left: scenario image (participant-constructed block world).\n"
            "• Right: “unique” instructions written in Study 1 that refer to this "
            "image. Each line shows:\n"
            "      writes ×  [✔ correct / ✖ wrong | accuracy%]  instruction text\n"
            "   –  writes: how many times that exact wording appeared in Study 1.\n"
            "   –  correct / wrong & accuracy: results from Study 2 where new "
            "participants tried to identify the target block.\n\n"
            "📊  Scenario order\n"
            "Images are presented from the *lowest* to *highest* mean difficulty "
            "rating given by Study 1 authors.\n\n"
            "↕️  Re-ordering instructions\n"
            "Use the drop-down to sort the list by:\n"
            "   Count   – most frequently written first (default)\n"
            "   Accuracy – highest % correct first (instructions never evaluated "
            "drop to the bottom).\n"
            "   Length   – shortest instructions listed first\n\n"
            "➡️  Navigation\n"
            "• Arrow keys  ←  →    or the on-screen buttons.\n"
        )
        Label(top, text=msg, justify=LEFT, padx=15, pady=10,
              font=("Helvetica", 10), wraplength=500).pack()
        Button(top, text="Got it!", command=top.destroy, width=12).pack(pady=(0, 12))
        top.transient(self)        # keep on top
        top.grab_set()             # modal
        self.wait_window(top)      # pause until closed


# ---------- RUN ------------------------------------------------------ #
if __name__ == "__main__":
    try:
        Viewer(images).mainloop()
    except KeyboardInterrupt:
        pass

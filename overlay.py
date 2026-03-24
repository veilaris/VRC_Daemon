"""
Grid overlay window for VRChat movement calibration.
Standalone — run separately from the bot server.

Usage:
  python overlay.py

Place the window over the VRChat window.
The overlay is captured by mss, so the LLM automatically sees the grid
in screenshots and can use it to measure position and character height.
"""

import tkinter as tk

H_COLOR     = "#FFDC00"   # yellow — horizontal pct lines
V_COLOR     = "#00D2FF"   # cyan   — zone lines
RULER_COLOR = "#44FF88"   # green  — character height ruler
BORDER_CLR  = "#334477"   # border around the window
BG_COLOR    = "#010101"   # near-black → made transparent via transparentcolor
RULER_W     = 80          # pixel width of the right-side ruler strip
BAR_H       = 26          # control bar height


class GridOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)      # no OS title bar
        self.root.geometry("1280x720+100+100")
        self.root.configure(bg=BG_COLOR)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", BG_COLOR)
        self.root.attributes("-alpha", 0.80)

        self._minimized  = False
        self._full_w     = 1280
        self._full_h     = 720
        self._drag_data  = {}
        self._resize_data = {}
        self._redraw_job = None

        self._build_ui()
        self.root.bind("<Configure>", lambda _: self._schedule_redraw())
        self._schedule_redraw()
        self.root.mainloop()

    # ------------------------------------------------------------------ #
    #  UI layout                                                           #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        # ── Control bar ────────────────────────────────────────────────
        self.bar = tk.Frame(self.root, bg="#111122", height=BAR_H)
        self.bar.pack(fill=tk.X, side=tk.TOP)
        self.bar.pack_propagate(False)

        # Drag handle (fills left portion of bar)
        drag = tk.Frame(self.bar, bg="#111122", cursor="fleur")
        drag.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        drag.bind("<Button-1>",  self._drag_start)
        drag.bind("<B1-Motion>", self._drag_move)

        tk.Label(drag, text="⊞  Grid Overlay", bg="#111122", fg="#cccccc",
                 font=("Arial", 8, "bold")).pack(side=tk.LEFT, padx=8, pady=2)

        self._size_var = tk.StringVar(value="")
        tk.Label(drag, textvariable=self._size_var, bg="#111122", fg="#555577",
                 font=("Courier", 8)).pack(side=tk.LEFT, padx=2)

        # Right-side buttons
        tk.Button(self.bar, text="✕", bg="#111122", fg="#886666", relief="flat",
                  bd=0, font=("Arial", 9), activebackground="#440000",
                  command=self.root.destroy).pack(side=tk.RIGHT, padx=6, pady=2)

        self._min_btn = tk.Button(
            self.bar, text="−", bg="#111122", fg="#8888aa", relief="flat",
            bd=0, font=("Arial", 11), activebackground="#223344",
            command=self._toggle_minimize)
        self._min_btn.pack(side=tk.RIGHT, padx=2, pady=2)

        # Opacity slider
        self._alpha_var = tk.DoubleVar(value=0.80)
        tk.Scale(self.bar, from_=0.15, to=1.0, resolution=0.05,
                 orient=tk.HORIZONTAL, variable=self._alpha_var, length=80,
                 bg="#111122", fg="#cccccc", troughcolor="#223344",
                 highlightthickness=0, showvalue=False,
                 command=lambda v: self.root.attributes("-alpha", float(v))
                 ).pack(side=tk.RIGHT, padx=2)
        tk.Label(self.bar, text="прозр.", bg="#111122", fg="#555566",
                 font=("Arial", 7)).pack(side=tk.RIGHT)

        # ── Grid canvas ────────────────────────────────────────────────
        self.canvas = tk.Canvas(self.root, bg=BG_COLOR, highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # ── Resize handle (bottom-right corner) ────────────────────────
        rh = tk.Frame(self.root, bg="#223366", width=14, height=14,
                      cursor="size_nw_se")
        rh.place(relx=1.0, rely=1.0, anchor="se")
        rh.bind("<Button-1>",  self._resize_start)
        rh.bind("<B1-Motion>", self._resize_move)

    # ------------------------------------------------------------------ #
    #  Minimize / expand                                                   #
    # ------------------------------------------------------------------ #

    def _toggle_minimize(self):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        if self._minimized:
            self.root.geometry(f"{self._full_w}x{self._full_h}+{x}+{y}")
            self._minimized = False
            self._min_btn.config(text="−")
        else:
            self._full_w = self.root.winfo_width()
            self._full_h = self.root.winfo_height()
            self.root.geometry(f"{self._full_w}x{BAR_H}+{x}+{y}")
            self._minimized = True
            self._min_btn.config(text="□")

    # ------------------------------------------------------------------ #
    #  Drag                                                                #
    # ------------------------------------------------------------------ #

    def _drag_start(self, e):
        self._drag_data = {"x": e.x_root - self.root.winfo_x(),
                           "y": e.y_root - self.root.winfo_y()}

    def _drag_move(self, e):
        d = self._drag_data
        if not d:
            return
        self.root.geometry(f"+{e.x_root - d['x']}+{e.y_root - d['y']}")

    # ------------------------------------------------------------------ #
    #  Resize                                                              #
    # ------------------------------------------------------------------ #

    def _resize_start(self, e):
        self._resize_data = {"x": e.x_root, "y": e.y_root,
                             "w": self.root.winfo_width(),
                             "h": self.root.winfo_height()}

    def _resize_move(self, e):
        d = self._resize_data
        if not d:
            return
        nw = max(320, d["w"] + (e.x_root - d["x"]))
        nh = max(200, d["h"] + (e.y_root - d["y"]))
        self.root.geometry(f"{nw}x{nh}")

    # ------------------------------------------------------------------ #
    #  Grid drawing                                                        #
    # ------------------------------------------------------------------ #

    def _schedule_redraw(self):
        if self._redraw_job:
            self.root.after_cancel(self._redraw_job)
        self._redraw_job = self.root.after(40, self._draw_grid)

    def _draw_grid(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50:
            return

        self._size_var.set(f"  {w} × {h} px")

        grid_w = w - RULER_W - 2   # grid area ends before the ruler strip

        # ── Window border ──────────────────────────────────────────────
        self.canvas.create_rectangle(1, 1, w - 2, h - 2,
                                     outline=BORDER_CLR, width=2)

        # ── Horizontal pct lines ───────────────────────────────────────
        for pct in range(10, 100, 10):
            y = int(h * pct / 100)
            major = (pct % 20 == 0)
            color = H_COLOR if major else "#5a4400"
            lw    = 2      if major else 1
            self.canvas.create_line(2, y, grid_w, y, fill=color, width=lw)
            if major:
                lbl = f"{pct}%"
                # shadow + label — large
                self.canvas.create_text(10, y - 10, text=lbl, fill="#000000",
                                        anchor="w", font=("Arial", 13, "bold"))
                self.canvas.create_text(9,  y - 11, text=lbl, fill=H_COLOR,
                                        anchor="w", font=("Arial", 13, "bold"))

        # ── Vertical zone lines ────────────────────────────────────────
        for frac in (0.33, 0.50, 0.67):
            x = int(grid_w * frac)
            self.canvas.create_line(x, 0, x, h, fill=V_COLOR,
                                    width=1, dash=(6, 4))

        # Labels at top — positioned between the zone lines
        self.canvas.create_text(int(grid_w * 0.17), 16, text="◄ LEFT",
                                fill=V_COLOR, font=("Arial", 13, "bold"), anchor="center")
        self.canvas.create_text(int(grid_w * 0.50), 16, text="CENTER",
                                fill=V_COLOR, font=("Arial", 13, "bold"), anchor="center")
        self.canvas.create_text(int(grid_w * 0.83), 16, text="RIGHT ►",
                                fill=V_COLOR, font=("Arial", 13, "bold"), anchor="center")

        # ── Center crosshair ───────────────────────────────────────────
        cx, cy = grid_w // 2, h // 2
        r = 6
        self.canvas.create_line(cx - r, cy, cx + r, cy, fill=V_COLOR, width=1)
        self.canvas.create_line(cx, cy - r, cx, cy + r, fill=V_COLOR, width=1)
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                outline=V_COLOR, width=1)

        # ── Character height ruler (right strip) ───────────────────────
        rx = w - RULER_W    # left edge of ruler

        # Dark background
        self.canvas.create_rectangle(rx, 0, w, h, fill="#071407", outline="")
        # Thick separator line
        self.canvas.create_line(rx, 0, rx, h, fill=RULER_COLOR, width=3)

        # Title — large and bold
        self.canvas.create_text(rx + RULER_W // 2, 14,
                                 text="РОСТ", fill=RULER_COLOR,
                                 font=("Arial", 12, "bold"), anchor="center")
        self.canvas.create_text(rx + RULER_W // 2, 28,
                                 text="ПЕРСОНАЖА", fill=RULER_COLOR,
                                 font=("Arial", 9, "bold"), anchor="center")

        # Tick marks and labels at every 10%; major ticks/labels at every 20%
        for pct in range(0, 101, 10):
            y = int(h * pct / 100)
            major = (pct % 20 == 0)
            lw   = 3 if major else 1
            tick = 20 if major else 10
            self.canvas.create_line(rx + 2, y, rx + 2 + tick, y,
                                    fill=RULER_COLOR, width=lw)
            # Label at every 10%: major = large, minor = smaller
            font_size = 13 if major else 9
            self.canvas.create_text(w - 4, y, text=f"{pct}%",
                                    fill=RULER_COLOR, anchor="e",
                                    font=("Arial", font_size, "bold"))

        # ── Body silhouette — visual reference for the LLM ─────────────
        # Centre x of silhouette sits between the tick marks and the % labels
        sc       = rx + RULER_W // 2 - 5   # silhouette centre x
        head_y   = int(h * 0.15)
        torso_y1 = int(h * 0.22)
        torso_y2 = int(h * 0.55)
        legs_y   = int(h * 0.82)
        feet_y   = int(h * 0.88)

        # Head oval
        self.canvas.create_oval(sc - 6, head_y - 8, sc + 6, head_y + 8,
                                outline=RULER_COLOR, fill="#071407", width=2)
        # Torso rectangle
        self.canvas.create_rectangle(sc - 8, torso_y1, sc + 8, torso_y2,
                                     outline=RULER_COLOR, fill="#071407", width=2)
        # Legs (two lines)
        self.canvas.create_line(sc - 4, torso_y2, sc - 4, legs_y,
                                fill=RULER_COLOR, width=2)
        self.canvas.create_line(sc + 4, torso_y2, sc + 4, legs_y,
                                fill=RULER_COLOR, width=2)
        # Feet (two small filled rectangles)
        self.canvas.create_rectangle(sc - 8, legs_y, sc - 1, feet_y,
                                     fill=RULER_COLOR, outline="")
        self.canvas.create_rectangle(sc + 1, legs_y, sc + 8, feet_y,
                                     fill=RULER_COLOR, outline="")


if __name__ == "__main__":
    GridOverlay()

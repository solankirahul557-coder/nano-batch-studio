"""Presentation layer. All generation, settings and worker actions live in nano_batch."""
import tkinter as tk
from tkinter import ttk, scrolledtext, font as tkfont

from nano_batch import (
    App, ROOT, MODEL_LABELS, RATIOS, GOOGLE_SIZES, OPENAI_QUALITY, FORMATS,
    DEFAULT_PROMPT,
)

BG = "#F5F6F3"
WHITE = "#FFFFFF"
INK = "#233C38"
MUTED = "#72807B"
LINE = "#DFE5DF"
TEAL = "#246B59"
SOFT = "#E5EFE8"


class StudioApp(App):
    def _init_style(self):
        self.root.configure(bg=BG)
        self.root.geometry("1320x960")
        self.root.minsize(980, 640)
        tkfont.nametofont("TkDefaultFont").configure(family="Segoe UI", size=10)
        self.root.option_add("*TCombobox*Listbox.background", WHITE)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", SOFT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)
        self.f_mono = ("Consolas", 10)
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(".", font=("Segoe UI", 10), background=WHITE, foreground=INK)
        st.configure("TFrame", background=WHITE)
        st.configure("Page.TFrame", background=BG)
        st.configure("TLabel", background=WHITE, foreground=INK)
        st.configure("Hint.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))
        st.configure("TEntry", fieldbackground=WHITE, bordercolor=LINE,
                     lightcolor=LINE, darkcolor=LINE, padding=8)
        st.configure("TCombobox", fieldbackground=WHITE, background=WHITE,
                     bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=7,
                     arrowsize=13)
        st.configure("TSpinbox", fieldbackground=WHITE, background=WHITE,
                     bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=7)
        for style in ("TEntry", "TCombobox", "TSpinbox"):
            st.map(style, bordercolor=[("focus", TEAL)],
                   fieldbackground=[("disabled", "#F2F4F1"), ("readonly", WHITE)],
                   foreground=[("disabled", "#9CA7A1")])
        st.configure("TButton", background=WHITE, bordercolor=LINE,
                     lightcolor=LINE, darkcolor=LINE, padding=(13, 8), focusthickness=0)
        st.map("TButton", background=[("active", "#EFF3EE"), ("pressed", SOFT)],
               foreground=[("disabled", "#A1AAA5")])
        st.configure("Go.TButton", font=("Segoe UI", 11, "bold"), padding=(24, 11),
                     background=TEAL, foreground=WHITE, bordercolor=TEAL,
                     lightcolor=TEAL, darkcolor=TEAL)
        st.map("Go.TButton", background=[("disabled", "#A8BDB3"), ("active", "#195541")],
               foreground=[("disabled", WHITE), ("active", WHITE)])
        st.configure("TCheckbutton", background=WHITE, padding=4)
        st.configure("TRadiobutton", background=WHITE, padding=4)
        st.map("TCheckbutton", background=[("active", WHITE)])
        st.map("TRadiobutton", background=[("active", WHITE)])
        st.configure("Mode.TRadiobutton", padding=(12, 11), background="#F4F6F2",
                     font=("Segoe UI", 10, "bold"))
        st.layout("Mode.TRadiobutton", [("Radiobutton.padding", {"children": [
            ("Radiobutton.focus", {"children": [("Radiobutton.label", {"sticky": "nswe"})],
                                    "sticky": "nswe"})], "sticky": "nswe"})])
        st.map("Mode.TRadiobutton", background=[("selected", SOFT), ("active", "#EDF1EB")],
               foreground=[("selected", TEAL)])
        st.configure("Horizontal.TProgressbar", background=TEAL, troughcolor="#E8EEE7",
                     borderwidth=0, lightcolor=TEAL, darkcolor=TEAL, thickness=5)
        st.configure("Vertical.TScrollbar", background="#D4DDD4", troughcolor=BG,
                     borderwidth=0, arrowsize=11)

    def _card(self, parent, title, subtitle=None):
        border = tk.Frame(parent, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        border.pack(fill="x", pady=(0, 16))
        body = ttk.Frame(border, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="Title.TLabel").pack(anchor="w")
        if subtitle:
            self._hint(body, subtitle).pack(fill="x", pady=(5, 0))
        inner = ttk.Frame(body)
        inner.pack(fill="x", pady=(16, 0))
        inner.columnconfigure(0, weight=1)
        return inner

    def _hint(self, parent, text):
        label = ttk.Label(parent, text=text, style="Hint.TLabel", wraplength=250)
        parent.bind("<Configure>", lambda e: label.configure(wraplength=max(80, e.width - 4)), add="+")
        return label

    def _field(self, parent, text, var, values=None, width=18):
        box = ttk.Frame(parent)
        label = ttk.Label(box, text=text)
        label.pack(anchor="w", pady=(0, 6))
        if values is None:
            widget = ttk.Entry(box, textvariable=var, width=width)
        else:
            widget = ttk.Combobox(box, textvariable=var, values=values, state="readonly", width=width)
        widget.pack(fill="x")
        return box, label, widget

    def _path(self, parent, text, var, row, file=False):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        label = ttk.Label(frame, text=text)
        label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        entry = ttk.Entry(frame, textvariable=var, width=18)
        entry.grid(row=1, column=0, sticky="ew")
        button = ttk.Button(frame, text="Browse", command=lambda: (
            self._pick_file(var) if file else self._pick_dir(var)))
        button.grid(row=1, column=1, padx=(8, 0))
        return frame, label, entry, button

    def _page(self, name, title, description):
        page = ttk.Frame(self.content, style="Page.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        heading = tk.Frame(page, bg=BG)
        heading.pack(fill="x", padx=28, pady=(26, 20))
        tk.Label(heading, text=title, bg=BG, fg=INK,
                 font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(heading, text=description, bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(5, 0))
        area = ttk.Frame(page, style="Page.TFrame")
        area.pack(fill="both", expand=True)
        canvas = tk.Canvas(area, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        body = ttk.Frame(canvas, style="Page.TFrame", padding=(28, 0, 18, 12))
        win = canvas.create_window(0, 0, anchor="nw", window=body)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        self.pages[name] = page
        self.canvases[name] = canvas
        return body

    def _show_page(self, name):
        self.current_page = name
        self.pages[name].tkraise()
        for key, button in self.nav.items():
            selected = key == name
            button.configure(bg=SOFT if selected else WHITE, fg=TEAL if selected else MUTED,
                             font=("Segoe UI", 10, "bold" if selected else "normal"))

    def _wheel(self, event):
        # Scroll only the page under the pointer; text editors keep native scrolling.
        widget = event.widget
        if isinstance(widget, (tk.Text, ttk.Combobox, ttk.Spinbox)):
            return
        page = self.pages[self.current_page]
        while widget is not None and widget != page:
            widget = getattr(widget, "master", None)
        if widget is None:
            return
        canvas = self.canvases[self.current_page]
        if canvas.yview() != (0.0, 1.0):
            delta = (-1 if event.delta > 0 else 1) if event.delta else (1 if event.num == 5 else -1)
            canvas.yview_scroll(delta * 3, "units")

    def _build(self):
        self.pages, self.canvases, self.nav = {}, {}, {}
        self.current_page = "workspace"
        sidebar = tk.Frame(self.root, bg=WHITE, width=186, highlightbackground=LINE,
                           highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        logo = tk.Canvas(sidebar, width=42, height=42, bg=WHITE, highlightthickness=0)
        logo.pack(anchor="w", padx=22, pady=(30, 12))
        logo.create_rectangle(0, 0, 42, 42, fill=TEAL, outline=TEAL)
        logo.create_line(12, 30, 12, 12, 30, 30, 30, 12, fill=WHITE, width=3)
        tk.Label(sidebar, text="nano batch", bg=WHITE, fg=INK,
                 font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=22)
        tk.Label(sidebar, text="IMAGE STUDIO", bg=WHITE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=24, pady=(2, 36))
        for name, label in (("workspace", "Workspace"), ("library", "Product library"),
                            ("activity", "Activity")):
            button = tk.Button(sidebar, text=label, anchor="w", relief="flat", bd=0,
                               padx=15, pady=12, cursor="hand2", bg=WHITE, fg=MUTED,
                               activebackground=SOFT, activeforeground=TEAL,
                               command=lambda n=name: self._show_page(n))
            button.pack(fill="x", padx=12, pady=3)
            self.nav[name] = button
        tk.Label(sidebar, text="Your products.\nA new perspective.", justify="left", bg=WHITE,
                 fg=MUTED, font=("Segoe UI", 10)).pack(side="bottom", anchor="w", padx=22, pady=26)
        ttk.Button(sidebar, text="Reset settings", command=self._reset).pack(
            side="bottom", fill="x", padx=18, pady=12)

        main = ttk.Frame(self.root, style="Page.TFrame")
        main.pack(side="left", fill="both", expand=True)
        footer = ttk.Frame(main, padding=(28, 14))
        footer.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(footer, mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 12))
        bar = ttk.Frame(footer)
        bar.pack(fill="x")
        self.btn_start = ttk.Button(bar, text="Generate images  →", style="Go.TButton", command=self._start)
        self.btn_start.pack(side="right")
        self.btn_stop = ttk.Button(bar, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", padx=10)
        self.status = ttk.Label(bar, text="Ready to create", style="Hint.TLabel", wraplength=360)
        self.status.pack(side="left", fill="x", expand=True, padx=(0, 10))
        bar.bind("<Configure>", lambda e: self.status.configure(
            wraplength=max(100, e.width - self.btn_start.winfo_width() - self.btn_stop.winfo_width() - 40)))
        self.content = ttk.Frame(main, style="Page.TFrame")
        self.content.pack(fill="both", expand=True)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self._build_workspace()
        self._build_library()
        self._build_activity()
        for var in (self.v_in, self.v_csv):
            var.trace_add("write", lambda *a: self._refresh_count())
        self.v_lib.trace_add("write", lambda *a: self._sync_lib())
        self.root.bind("<MouseWheel>", self._wheel, add="+")
        self.root.bind("<Button-4>", self._wheel, add="+")
        self.root.bind("<Button-5>", self._wheel, add="+")
        self._show_page("workspace")

    def _build_workspace(self):
        body = self._page("workspace", "Make room for imagination.",
                          "Turn your products into considered scenes, one batch at a time.")
        body.columnconfigure(0, weight=6, uniform="main")
        body.columnconfigure(1, weight=5, uniform="main")
        left = ttk.Frame(body, style="Page.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right = ttk.Frame(body, style="Page.TFrame")
        right.grid(row=0, column=1, sticky="nsew")

        def reflow(event):
            narrow = event.width < 920
            if getattr(self, "_narrow", None) == narrow:
                return
            self._narrow = narrow
            left.grid_configure(row=0, column=0, columnspan=2 if narrow else 1,
                                padx=0 if narrow else (0, 16))
            right.grid_configure(row=1 if narrow else 0, column=0 if narrow else 1,
                                 columnspan=2 if narrow else 1)
        body.bind("<Configure>", reflow, add="+")

        src = self._card(left, "01  /  Choose your source")
        modes = ttk.Frame(src)
        modes.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.v_mode = tk.StringVar(value="edit")
        for i, (value, label) in enumerate((("edit", "Photo scenes"), ("text", "Product list"),
                                            ("compose", "Combine"))):
            modes.columnconfigure(i, weight=1)
            ttk.Radiobutton(modes, text=label, value=value, variable=self.v_mode,
                            style="Mode.TRadiobutton", command=self._sync_mode).grid(
                                row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
        self.mode_hint = self._hint(src, "")
        self.mode_hint.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.v_in = tk.StringVar(value=str(ROOT / "inputs"))
        self.v_csv = tk.StringVar(value=str(ROOT / "products.csv"))
        self.input_frame, self.lbl_in, self.e_in, self.b_in = self._path(src, "Input folder", self.v_in, 2)
        self.csv_frame, self.lbl_csv, self.e_csv, self.b_csv = self._path(src, "Product list · CSV", self.v_csv, 3, True)
        self.lbl_count = self._hint(src, "")
        self.lbl_count.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        self.amounts = ttk.Frame(src)
        self.amounts.grid(row=5, column=0, sticky="ew")
        self.v_per, self.v_var, self.v_room = tk.IntVar(value=1), tk.IntVar(value=1), tk.StringVar(value="1")
        self.amount_frames = []
        for i, (text, var, limit) in enumerate((("Images per item", self.v_per, 8),
                                               ("Scene variations", self.v_var, 50),
                                               ("Photos per scene", self.v_room, None))):
            box = ttk.Frame(self.amounts)
            box.grid(row=0, column=i, sticky="ew", padx=(0, 12))
            self.amounts.columnconfigure(i, weight=1)
            label = ttk.Label(box, text=text)
            label.pack(anchor="w", pady=(0, 6))
            widget = (ttk.Spinbox(box, from_=1, to=limit, textvariable=var, width=6)
                      if limit else ttk.Entry(box, textvariable=var, width=8))
            widget.pack(fill="x")
            self.amount_frames.append(box)
            if i == 0:
                self.lbl_per, self.sp_per = label, widget
            elif i == 1:
                self.lbl_var, self.sp_var = label, widget
            else:
                self.lbl_room, self.e_room = label, widget
        self.amount_hint = self._hint(src, "")
        self.amount_hint.grid(row=6, column=0, sticky="ew", pady=(8, 0))

        prompt = self._card(left, "02  /  Describe the scene", "Set the mood, materials, lighting and composition.")
        self.t_prompt = scrolledtext.ScrolledText(prompt, height=8, width=20, wrap="word", relief="flat",
                    bg="#F8FAF6", fg=INK, insertbackground=TEAL, padx=14, pady=12,
                    font=("Segoe UI", 11), spacing1=3, spacing3=4, selectbackground=SOFT,
                    highlightthickness=1, highlightbackground=LINE, highlightcolor=TEAL, undo=True)
        self.t_prompt.insert("1.0", DEFAULT_PROMPT)
        self.t_prompt.pack(fill="x")
        self._hint(prompt, "In product-list mode, use {product} for each product name.").pack(fill="x", pady=(10, 0))
        ttk.Button(prompt, text="Manage supporting products  →", command=lambda: self._show_page("library")).pack(
            anchor="w", pady=(14, 0))

        model = self._card(right, "Generation model", "Choose the model behind your images.")
        self.v_model = tk.StringVar(value=MODEL_LABELS[0])
        box, _, self.cb_model = self._field(model, "Model", self.v_model, MODEL_LABELS)
        box.pack(fill="x", pady=(0, 14))
        self.cb_model.bind("<<ComboboxSelected>>", lambda e: self._sync_provider())
        self.v_gkey, self.v_okey = tk.StringVar(), tk.StringVar()
        box, self.lbl_key, self.e_key = self._field(model, "Google API key", self.v_gkey)
        self.e_key.configure(show="•")
        box.pack(fill="x")
        self.lbl_prov = self._hint(model, "")
        self.lbl_prov.pack(fill="x", pady=(8, 0))

        output = self._card(right, "Output settings")
        self.v_aspect, self.v_quality = tk.StringVar(value="3:2"), tk.StringVar(value="2K")
        self.v_oq, self.v_fmt = tk.StringVar(value="high"), tk.StringVar(value="jpg")
        output.columnconfigure(0, weight=1, uniform="output")
        output.columnconfigure(1, weight=1, uniform="output")
        for i, (text, var, values) in enumerate((("Aspect ratio", self.v_aspect, RATIOS),
                                                ("Resolution", self.v_quality, GOOGLE_SIZES),
                                                ("Quality", self.v_oq, OPENAI_QUALITY),
                                                ("File format", self.v_fmt, FORMATS))):
            box, label, cb = self._field(output, text, var, values, width=8)
            box.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 12) if i % 2 == 0 else 0, pady=(0, 14))
            if i == 0:
                self.cb_aspect = cb
                cb.bind("<<ComboboxSelected>>", lambda e: self._sync_provider())
            elif i == 1:
                self.lbl_q, self.cb_quality = label, cb
                cb.bind("<<ComboboxSelected>>", lambda e: self._sync_provider())
            elif i == 2:
                self.lbl_oq, self.cb_oq = label, cb
        self.lbl_asphint = self._hint(output, "")
        self.lbl_asphint.grid(row=2, column=0, columnspan=2, sticky="ew")

        dest = self._card(right, "Save your images")
        self.v_out = tk.StringVar(value=str(ROOT / "outputs"))
        self._path(dest, "Output folder", self.v_out, 0)
        ttk.Button(dest, text="Open output folder  ↗", command=self._open_out).grid(row=1, column=0, sticky="w")
        self._hint(dest, "Repeat filenames get a new version automatically.").grid(row=2, column=0, sticky="ew", pady=(12, 0))

    def _build_library(self):
        body = self._page("library", "A space for your collection.",
                          "Use your own furniture and decor as supporting pieces in photo scenes.")
        sec = self._card(body, "Furnish with your products", "Available when Photo scenes is selected in the workspace.")
        self.v_lib_on = tk.BooleanVar(value=False)
        self.chk_lib = ttk.Checkbutton(sec, text="Use only my own products to furnish the scene",
                                      variable=self.v_lib_on, command=self._sync_lib)
        self.chk_lib.grid(row=0, column=0, sticky="w")
        self._hint(sec, "The original photo stays the hero. Supporting items come from your collection.").grid(
            row=1, column=0, sticky="ew", pady=(8, 16))
        self.lbl_src = ttk.Label(sec, text="Library source")
        self.lbl_src.grid(row=2, column=0, sticky="w")
        radios = ttk.Frame(sec)
        radios.grid(row=3, column=0, sticky="w", pady=(6, 18))
        self.v_src = tk.StringVar(value="folder")
        for val, text in (("folder", "A folder on my computer"), ("web", "A website")):
            ttk.Radiobutton(radios, text=text, value=val, variable=self.v_src,
                            command=self._sync_lib).pack(side="left", padx=(0, 22))
        self.v_lib = tk.StringVar(value=str(ROOT / "library"))
        _, self.lbl_lib, self.e_lib, self.b_lib = self._path(sec, "Product library folder", self.v_lib, 4)
        self.v_url = tk.StringVar()
        url = ttk.Frame(sec)
        url.grid(row=5, column=0, sticky="ew", pady=(4, 16))
        url.columnconfigure(0, weight=1)
        self.lbl_url = ttk.Label(url, text="Website address")
        self.lbl_url.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.e_url = ttk.Entry(url, textvariable=self.v_url)
        self.e_url.grid(row=1, column=0, sticky="ew")
        self.b_fetch = ttk.Button(url, text="Fetch images", command=self._fetch_site)
        self.b_fetch.grid(row=1, column=1, padx=(8, 0))
        limits = ttk.Frame(sec)
        limits.grid(row=6, column=0, sticky="ew", pady=(0, 20))
        self.v_wmax, self.v_wpages, self.v_wmin = tk.IntVar(value=40), tk.IntVar(value=1), tk.IntVar(value=400)
        for i, (label, var, low, high, step) in enumerate((("Download up to", self.v_wmax, 1, 300, 1),
                ("Pages to read", self.v_wpages, 1, 30, 1), ("Minimum image size · px", self.v_wmin, 50, 2000, 50))):
            box = ttk.Frame(limits)
            box.grid(row=0, column=i, sticky="ew", padx=(0, 18))
            limits.columnconfigure(i, weight=1)
            lbl = ttk.Label(box, text=label)
            lbl.pack(anchor="w", pady=(0, 6))
            spin = ttk.Spinbox(box, from_=low, to=high, increment=step, textvariable=var, width=8)
            spin.pack(fill="x")
            if i == 0:
                self.lbl_wmax, self.sp_wmax = lbl, spin
            elif i == 1:
                self.lbl_wpages, self.sp_wpages = lbl, spin
            else:
                self.lbl_wmin, self.sp_wmin = lbl, spin
        self.v_libn = tk.StringVar(value="6")
        box, self.lbl_libn, self.e_libn = self._field(sec, "Supporting items per scene", self.v_libn, width=10)
        box.grid(row=7, column=0, sticky="w")
        self.lbl_libhint = self._hint(sec, "Enter a number, or 'all'. Up to 13 supporting images can be used.")
        self.lbl_libhint.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        self.lbl_libcount = self._hint(sec, "")
        self.lbl_libcount.grid(row=9, column=0, sticky="ew", pady=(12, 0))

    def _build_activity(self):
        body = self._page("activity", "Follow every creation.",
                          "Generation progress, saved files and website downloads, all in one place.")
        sec = self._card(body, "Batch activity", "Your activity will appear here when you generate or fetch images.")
        self.log = scrolledtext.ScrolledText(sec, height=22, width=30, state="disabled", wrap="word",
                        font=self.f_mono, bg="#F8FAF6", fg=INK, relief="flat", padx=16, pady=16,
                        highlightthickness=1, highlightbackground=LINE, spacing3=5)
        self.log.pack(fill="both", expand=True)
        ttk.Button(sec, text="Open output folder  ↗", command=self._open_out).pack(anchor="w", pady=(16, 0))

    def _sync_mode(self):
        super()._sync_mode()
        mode = self.v_mode.get()
        for frame, visible in ((self.input_frame, mode != "text"), (self.csv_frame, mode == "text")):
            frame.grid() if visible else frame.grid_remove()
        for i, box in enumerate(self.amount_frames):
            visible = (mode != "compose") if i == 0 else (mode == "compose")
            box.grid() if visible else box.grid_remove()
            self.amounts.columnconfigure(i, weight=1 if visible else 0)
        self.mode_hint.configure(text={
            "edit": "Create a new scene for each photo. Original filenames are kept.",
            "text": "Create images from a CSV with a product column and optional extra details.",
            "compose": "Blend multiple product photos into a scene, with variations.",
        }.get(mode, ""))
        self.amount_hint.configure(text="Photos per scene accepts a number or 'all' (up to 14)."
                                   if mode == "compose" else "")

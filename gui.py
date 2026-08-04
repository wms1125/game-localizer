from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from cli import format_result
from translator import TranslationError, process_resource


PALETTE = {
    "background": "#f7f3ec",
    "surface": "#fffdf8",
    "text": "#242321",
    "muted": "#6d6861",
    "border": "#cfc8bd",
    "primary": "#c83b2b",
    "primary_active": "#a92f23",
}
ETHICS = "\u4ec5\u7528\u4e8e\u5408\u6cd5\u62e5\u6709\u6216\u5df2\u83b7\u6388\u6743\u7684\u6e38\u620f\u8d44\u6e90"


class GameTranslatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.resource_path = tk.StringVar()
        self.dictionary_path = tk.StringVar()
        self._configure_window()
        self._build_layout()

    def _configure_window(self) -> None:
        self.root.title("\u672c\u5730\u6e38\u620f\u6c49\u5316\u5de5\u5177")
        self.root.geometry("900x620")
        self.root.minsize(760, 520)
        self.root.configure(bg=PALETTE["background"])

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=PALETTE["background"])
        style.configure(
            "App.TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["text"],
            font=("Microsoft YaHei UI", 11),
        )
        style.configure(
            "Title.TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["text"],
            font=("Microsoft YaHei UI", 24, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["muted"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Primary.TButton",
            background=PALETTE["primary"],
            foreground="white",
            font=("Microsoft YaHei UI", 12, "bold"),
            padding=(24, 10),
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", PALETTE["primary_active"]),
                ("pressed", PALETTE["primary_active"]),
            ],
        )

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, style="App.TFrame", padding=(32, 22, 32, 18))
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)

        ttk.Label(
            frame,
            text="\u672c\u5730\u6e38\u620f\u6c49\u5316\u5de5\u5177",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=3, pady=(0, 2))
        ttk.Label(frame, text=ETHICS, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=3, pady=(0, 20)
        )
        ttk.Separator(frame).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(0, 18)
        )

        ttk.Label(frame, text="\u9009\u62e9\u8d44\u6e90\u6587\u4ef6", style="App.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 14), pady=6
        )
        ttk.Entry(frame, textvariable=self.resource_path).grid(
            row=3, column=1, sticky="ew", pady=6
        )
        ttk.Button(
            frame,
            text="\u6d4f\u89c8\u2026",
            command=self.choose_resource,
        ).grid(row=3, column=2, padx=(10, 0), pady=6)

        ttk.Label(frame, text="\u52a0\u8f7d\u7ffb\u8bd1\u5b57\u5178", style="App.TLabel").grid(
            row=4, column=0, sticky="w", padx=(0, 14), pady=6
        )
        ttk.Entry(frame, textvariable=self.dictionary_path).grid(
            row=4, column=1, sticky="ew", pady=6
        )
        ttk.Button(
            frame,
            text="\u6d4f\u89c8\u2026",
            command=self.choose_dictionary,
        ).grid(row=4, column=2, padx=(10, 0), pady=6)

        ttk.Separator(frame).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(18, 0)
        )
        ttk.Button(
            frame,
            text="\u6267\u884c\u6c49\u5316",
            style="Primary.TButton",
            command=self.run_translation,
        ).grid(row=6, column=0, columnspan=3, pady=(20, 18))
        ttk.Separator(frame).grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(0, 18)
        )
        ttk.Label(frame, text="\u5904\u7406\u65e5\u5fd7", style="App.TLabel").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        self.log = scrolledtext.ScrolledText(
            frame,
            wrap="word",
            state="disabled",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            relief="solid",
            borderwidth=1,
            font=("Consolas", 10),
        )
        self.log.grid(row=9, column=0, columnspan=3, sticky="nsew")

    def choose_resource(self) -> None:
        selected = filedialog.askopenfilename(
            filetypes=[
                ("\u652f\u6301\u7684\u8d44\u6e90", "*.txt *.ks *.rpy *.script *.csv *.json"),
                ("\u6240\u6709\u6587\u4ef6", "*.*"),
            ]
        )
        if selected:
            self.resource_path.set(selected)

    def choose_dictionary(self) -> None:
        selected = filedialog.askopenfilename(
            filetypes=[("JSON \u5b57\u5178", "*.json"), ("\u6240\u6709\u6587\u4ef6", "*.*")]
        )
        if selected:
            self.dictionary_path.set(selected)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_translation(self) -> None:
        if not self.resource_path.get() or not self.dictionary_path.get():
            prompt = (
                "\u8bf7\u5148\u9009\u62e9\u8d44\u6e90\u6587\u4ef6\u5e76\u52a0\u8f7d\u7ffb\u8bd1\u5b57\u5178\u3002"
            )
            self._append_log(prompt)
            messagebox.showwarning("\u7f3a\u5c11\u6587\u4ef6", prompt)
            return

        self._append_log("\u5f00\u59cb\u6c49\u5316\u5904\u7406\u2026")
        try:
            result = process_resource(
                self.resource_path.get(),
                self.dictionary_path.get(),
            )
        except TranslationError as exc:
            self._append_log(f"\u9519\u8bef: {exc}")
            messagebox.showerror("\u6c49\u5316\u5931\u8d25", str(exc))
            return

        self._append_log(format_result(result))
        messagebox.showinfo(
            "\u6c49\u5316\u5b8c\u6210",
            f"\u6c49\u5316\u6587\u4ef6\u5df2\u8f93\u51fa\u5230\uff1a\n{result.output_path}",
        )


def main() -> None:
    root = tk.Tk()
    GameTranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

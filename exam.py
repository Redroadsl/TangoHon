import os
import sys
import csv
import copy
import random
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.font import Font

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("tango_exam")

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COL_NAMES = ["kanji", "kana", "trans", "pos", "phrase"]
COL_LABELS = {"kanji": "漢字", "kana": "仮名", "trans": "翻訳", "pos": "詞性", "phrase": "短语"}
COL_MAP = {"kanji": 0, "kana": 1, "trans": 2, "pos": 3, "phrase": 4}
COL_WIDTHS = {"index": 40, "kanji": 150, "kana": 160, "trans": 220, "pos": 60, "phrase": 200}
DEFAULT_ROW_H = 26
DEFAULT_HEADER_H = 24


class TangoExam:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("単語帳 試験モード")
        self.root.geometry("1100x650")
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        wx = (sw - 1100) // 2
        wy = (sh - 650) // 2
        self.root.geometry(f"1100x650+{wx}+{wy}")

        self.encoding = tk.StringVar(value="gbk")
        self.current_file = None
        self.flat_data = []
        self.original_data = []
        self.data = []
        self.exam_map = []
        self.hidden_cols = set()
        self._selected_hidden_cols = set()
        self.answers = {}
        self.results = {}

        self._edit_entry = None
        self._edit_data_idx = None
        self._edit_col_idx = None

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._dragging = False
        self._scroll_accum_y = 0

        self.font_size = tk.IntVar(value=10)
        self.font_size.trace_add("write", lambda *_: self._update_font_size())
        self._cell_font = Font(family="Consolas", size=10)
        self._row_h = DEFAULT_ROW_H
        self._header_h = DEFAULT_HEADER_H

        self._build_ui()
        self.refresh_file_list()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    # ═══════════════════════ UI ═══════════════════════

    def _build_ui(self):
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── Left panel ──
        left_frame = ttk.Frame(paned, width=260)
        paned.add(left_frame, weight=0)

        ttk.Label(left_frame, text="ファイル一覧", font=Font(weight="bold")).pack(anchor=tk.W, pady=(0, 4))

        btn_row = ttk.Frame(left_frame)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn_row, text="再読込", command=self.refresh_file_list, width=8).pack(side=tk.LEFT)

        enc_row = ttk.Frame(left_frame)
        enc_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(enc_row, text="エンコード:").pack(side=tk.LEFT)
        enc_combo = ttk.Combobox(enc_row, textvariable=self.encoding,
                                 values=["gbk", "cp932", "utf-8", "euc-jp"],
                                 width=10, state="readonly")
        enc_combo.pack(side=tk.LEFT, padx=(4, 0))

        self.file_listbox = tk.Listbox(left_frame, activestyle="none", exportselection=False,
                                       font=Font(family="Consolas", size=10))
        self.file_listbox.pack(fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<Double-Button-1>", self.on_file_select)

        # ── Right panel ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        toolbar = ttk.Frame(right_frame)
        toolbar.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(toolbar, text="単語一覧", font=Font(weight="bold")).pack(side=tk.LEFT)
        self.hint_var = tk.StringVar(value="ヘッダーをクリックして隠す列を選択")
        ttk.Label(toolbar, textvariable=self.hint_var, foreground="gray").pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(toolbar, text="文字サイズ:").pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Scale(toolbar, from_=8, to=24, variable=self.font_size,
                  orient=tk.HORIZONTAL, length=60).pack(side=tk.RIGHT, padx=(2, 0))
        self.fs_label = ttk.Label(toolbar, text="10", width=2)
        self.fs_label.pack(side=tk.RIGHT)

        self.btn_reset = ttk.Button(toolbar, text="リセット", command=self.reset_exam, width=8, state=tk.DISABLED)
        self.btn_reset.pack(side=tk.RIGHT, padx=(2, 0))
        self.btn_exam = ttk.Button(toolbar, text="出題開始", command=self.start_exam_from_selection, width=10, state=tk.DISABLED)
        self.btn_exam.pack(side=tk.RIGHT, padx=(2, 0))

        # ── Canvas table ──
        canvas_frame = ttk.Frame(right_frame)
        canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg='white', highlightthickness=0,
                                cursor="hand2")
        self.vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._scroll_y)
        self.hsb = ttk.Scrollbar(right_frame, orient=tk.HORIZONTAL, command=self._scroll_x)
        self.canvas.configure(yscrollcommand=self._sync_vsb, xscrollcommand=self._sync_hsb)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas.bind("<Button-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind("<Button-1>", self._on_any_click, "+")
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview("scroll", -3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview("scroll", 3, "units"))

        self._total_w = sum(COL_WIDTHS.values())

        # ── Status bar ──
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.enc_status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.enc_status_var,
                  relief=tk.SUNKEN, anchor=tk.E, width=14).pack(side=tk.RIGHT)

        self._update_font_size()

    def _update_font_size(self):
        size = self.font_size.get()
        self._cell_font = Font(family="Consolas", size=size)
        self._row_h = max(18, int(size * 2.6))
        self.fs_label.config(text=str(size))
        self._redraw()

    def _scroll_y(self, *args):
        self.canvas.yview(*args)
        self._move_edit()

    def _scroll_x(self, *args):
        self.canvas.xview(*args)
        self._move_edit()

    def _sync_vsb(self, *args):
        self.vsb.set(*args)

    def _sync_hsb(self, *args):
        self.hsb.set(*args)

    def _on_canvas_configure(self, event):
        self.canvas.configure(scrollregion=(0, 0, self._total_w,
                              self._header_h + len(self.data) * self._row_h + 4))

    def _move_edit(self):
        if self._edit_entry is not None and self._edit_data_idx is not None and self._edit_col_idx is not None:
            sx, sy = self._cell_screen_pos(self._edit_data_idx, self._edit_col_idx)
            if sx is not None:
                self._edit_entry.place(x=sx, y=sy, width=COL_WIDTHS[COL_NAMES[self._edit_col_idx]], height=self._row_h)

    def _cell_screen_pos(self, data_idx, col_idx):
        col_name = COL_NAMES[col_idx]
        x = sum(w for cn, w in COL_WIDTHS.items() if list(COL_WIDTHS.keys()).index(cn) < list(COL_WIDTHS.keys()).index(col_name))
        y = self._header_h + data_idx * self._row_h
        ox = int(self.canvas.canvasx(0))
        oy = int(self.canvas.canvasy(0))
        return x - ox, y - oy

    def _update_status(self):
        parts = []
        if self.current_file:
            parts.append(self.current_file)
        parts.append(f"単語数: {len(self.flat_data)}")
        if self.hidden_cols:
            hidden_names = [COL_LABELS[COL_NAMES[c]] for c in sorted(self.hidden_cols)]
            parts.append(f"出題中（{', '.join(hidden_names)}）")
            answered = len(self.results)
            correct = sum(1 for v in self.results.values() if v == "exact")
            partial = sum(1 for v in self.results.values() if v == "partial")
            if answered > 0:
                pct = correct / answered * 100
                label = f"正解: {correct}/{answered}（{pct:.1f}%）"
                if partial:
                    label += f" 近似: {partial}"
                parts.append(label)
        else:
            if self._selected_hidden_cols:
                names = [COL_LABELS[COL_NAMES[c]] for c in sorted(self._selected_hidden_cols)]
                parts.append(f"隠す列: {', '.join(names)}（ヘッダーをクリックして変更）")
            else:
                parts.append("待機中")
        self.status_var.set("  |  ".join(parts))
        self.enc_status_var.set(f"[{self.encoding.get()}]")

    # ═══════════════════════ File ═══════════════════════

    def csv_files(self):
        return sorted(f for f in os.listdir(BASE_DIR) if f.upper().endswith(".CSV"))

    def refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for f in self.csv_files():
            self.file_listbox.insert(tk.END, f)
        self._update_status()

    def on_file_select(self, event):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        fname = self.file_listbox.get(sel[0])
        self.load_file(fname)

    def load_file(self, fname):
        path = os.path.join(BASE_DIR, fname)
        self.current_file = fname
        logger.info("ファイル読み込み中: %s", fname)
        encodings_to_try = list(dict.fromkeys([self.encoding.get(), "utf-8", "gbk", "cp932", "euc-jp"]))
        self.flat_data.clear()
        last_error = None
        for enc in encodings_to_try:
            try:
                with open(path, "r", encoding=enc) as f:
                    reader = csv.reader(f)
                    rows = []
                    for row in reader:
                        if not row or all(cell.strip() == "" for cell in row):
                            continue
                        kanji = row[0].strip() if len(row) > 0 else ""
                        kana = row[1].strip() if len(row) > 1 else ""
                        trans = row[2].strip() if len(row) > 2 else ""
                        pos = row[3].strip() if len(row) > 3 else ""
                        phrase = row[4].strip() if len(row) > 4 else ""
                        rows.append([kanji, kana, trans, pos, phrase])
                    self.flat_data = rows
                    self.encoding.set(enc)
                    break
            except (UnicodeDecodeError, UnicodeError) as e:
                self.flat_data.clear()
                last_error = e
                continue
            except Exception as e:
                last_error = e
                break
        else:
            if last_error:
                logger.error("ファイル読込エラー: %s - %s", path, last_error)
                messagebox.showerror("読込エラー", f"{path}\n{last_error}")
            self.flat_data.clear()

        self.original_data = copy.deepcopy(self.flat_data)
        self.data = [row[:] for row in self.flat_data]
        self.hidden_cols = set()
        self._selected_hidden_cols.clear()
        self.answers.clear()
        self.results.clear()
        self.exam_map = list(range(len(self.flat_data)))
        self.btn_exam.config(state=tk.DISABLED)
        self.btn_reset.config(state=tk.DISABLED)
        self.hint_var.set("ヘッダーをクリックして隠す列を選択")
        self._redraw()
        self._update_status()
        logger.info("ファイル読込完了: %s (%d 語, encoding=%s)", fname, len(self.flat_data), self.encoding.get())

    # ═══════════════════════ Exam ═══════════════════════

    def start_exam_from_selection(self):
        if not self.flat_data:
            messagebox.showinfo("確認", "ファイルを先に開いてください")
            return
        if not self._selected_hidden_cols:
            messagebox.showwarning("警告", "隠す列を選択してください（表のヘッダーをクリック）")
            return
        if len(self._selected_hidden_cols) >= len(COL_NAMES):
            messagebox.showwarning("警告", "すべての列を隠すことはできません")
            return
        self.start_exam(set(self._selected_hidden_cols))

    def start_exam(self, hidden_cols):
        self.hidden_cols = hidden_cols
        self.answers.clear()
        self.results.clear()

        indices = list(range(len(self.flat_data)))
        random.shuffle(indices)
        self.exam_map = indices

        self.data = []
        for flat_idx in indices:
            row = self.flat_data[flat_idx][:]
            for ci in hidden_cols:
                row[ci] = ""
            self.data.append(row)

        self._selected_hidden_cols.clear()
        self.btn_reset.config(state=tk.NORMAL)
        self.btn_exam.config(state=tk.DISABLED)
        self.hint_var.set("空欄をクリックして入力  |  Enter↓  Tab→")
        self._redraw()
        self._update_status()
        logger.info("試験開始: %d 語, 隠し列=%s", len(self.data),
                     [COL_NAMES[c] for c in sorted(hidden_cols)])

    def reset_exam(self):
        self._destroy_edit()
        self.hidden_cols = set()
        self._selected_hidden_cols.clear()
        self.answers.clear()
        self.results.clear()
        self.data = [row[:] for row in self.flat_data]
        self.exam_map = list(range(len(self.flat_data)))
        self.btn_reset.config(state=tk.DISABLED)
        self.btn_exam.config(state=tk.DISABLED)
        self.hint_var.set("ヘッダーをクリックして隠す列を選択")
        self._redraw()
        self._update_status()
        logger.info("試験をリセットしました")

    # ═══════════════════════ Canvas drawing ═══════════════════════

    def _redraw(self):
        self._destroy_edit()
        self.canvas.delete("all")

        total_h = self._header_h + len(self.data) * self._row_h + 4
        self.canvas.configure(scrollregion=(0, 0, self._total_w, total_h))

        # Draw header
        x = 0
        header_labels = ["#", "漢字", "仮名", "翻訳", "詞性", "短语"]
        for i, (cn, w) in enumerate(COL_WIDTHS.items()):
            ci = COL_MAP.get(cn)
            selected = not self.hidden_cols and ci is not None and ci in self._selected_hidden_cols
            h_bg = "#aaddff" if selected else "#e8e8e8"
            self.canvas.create_rectangle(x, 0, x + w, self._header_h,
                                         fill=h_bg, outline="#ccc")
            self.canvas.create_text(x + w / 2, self._header_h / 2, anchor=tk.CENTER,
                                    text=header_labels[i], font=Font(size=self.font_size.get(), weight="bold"))
            x += w

        # Draw rows
        for row_idx, row in enumerate(self.data):
            y = self._header_h + row_idx * self._row_h
            x = 0
            for col_idx, (cn, w) in enumerate(COL_WIDTHS.items()):
                bg = "#f8f8f8" if row_idx % 2 == 0 else "#ffffff"
                self.canvas.create_rectangle(x, y, x + w, y + self._row_h,
                                             fill=bg, outline="#ddd", tags="cell")

                if cn == "index":
                    text = str(row_idx + 1)
                    color = "#888"
                    anchor = tk.CENTER
                    tx = x + w / 2
                else:
                    ci = COL_MAP.get(cn)
                    text = row[ci] if ci is not None and ci < len(row) else ""
                    if (row_idx, ci) in self.results:
                        m = self.results[(row_idx, ci)]
                        color = "#007700" if m == "exact" else "#996600" if m == "partial" else "#CC0000"
                    else:
                        color = "#000000"
                    anchor = tk.W
                    tx = x + 6

                self.canvas.create_text(tx, y + self._row_h / 2, anchor=anchor,
                                        text=text, fill=color,
                                        font=self._cell_font, tags="cell")
                x += w

    # ═══════════════════════ Canvas click ═══════════════════════

    def _on_any_click(self, event):
        if self._edit_entry is not None:
            w = event.widget
            if w != self.canvas and w != self._edit_entry:
                self._destroy_edit()

    def _on_mousewheel(self, event):
        self.canvas.yview("scroll", -1 * (event.delta // 120), "units")
        return "break"

    def _on_canvas_press(self, event):
        self._destroy_edit()
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._dragging = False
        self._scroll_accum_y = 0

    def _on_canvas_drag(self, event):
        dy = event.y - self._drag_start_y
        if abs(dy) > 10:
            if not self._dragging:
                self._dragging = True
            target_y = int(-dy / 26)
            delta_y = target_y - self._scroll_accum_y
            if delta_y:
                self.canvas.yview("scroll", delta_y, "units")
                self._scroll_accum_y = target_y

    def _on_canvas_release(self, event):
        if not self._dragging:
            cx = int(self.canvas.canvasx(event.x))
            cy = int(self.canvas.canvasy(event.y))
            self._process_canvas_click(cx, cy)
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._dragging = False
        self._scroll_accum_y = 0

    def _process_canvas_click(self, cx, cy):
        if cy < self._header_h:
            if not self.hidden_cols:
                x = 0
                for cn, w in COL_WIDTHS.items():
                    if x <= cx < x + w:
                        ci = COL_MAP.get(cn)
                        if ci is not None:
                            if ci in self._selected_hidden_cols:
                                self._selected_hidden_cols.discard(ci)
                            else:
                                self._selected_hidden_cols.add(ci)
                            self.btn_exam.config(state=tk.NORMAL if self._selected_hidden_cols else tk.DISABLED)
                            self._redraw()
                            self._update_status()
                        break
                    x += w
            return

        if not self.hidden_cols:
            return

        row_idx = (cy - self._header_h) // self._row_h
        if row_idx < 0 or row_idx >= len(self.data):
            return

        x = 0
        col_idx = None
        for cn, w in COL_WIDTHS.items():
            if x <= cx < x + w:
                if cn == "index":
                    return
                ci = COL_MAP.get(cn)
                if ci is not None and ci in self.hidden_cols:
                    col_idx = ci
                break
            x += w

        if col_idx is None:
            return
        if self.results.get((row_idx, col_idx)) == "exact":
            return

        self._start_edit(row_idx, col_idx)

    def _start_edit(self, data_idx, col_idx):
        self._destroy_edit()

        sx, sy = self._cell_screen_pos(data_idx, col_idx)
        if sx is None:
            return

        col_name = COL_NAMES[col_idx]
        width = COL_WIDTHS[col_name]

        self._edit_data_idx = data_idx
        self._edit_col_idx = col_idx

        entry = ttk.Entry(self.canvas, font=Font(family="Consolas", size=self.font_size.get()))
        entry.place(x=sx, y=sy, width=width, height=self._row_h)
        entry.insert(0, self.data[data_idx][col_idx])
        entry.select_range(0, tk.END)
        entry.focus_set()

        entry.bind("<Return>", self._on_exam_enter)
        entry.bind("<Tab>", self._on_exam_tab)
        entry.bind("<Escape>", lambda e: self._destroy_edit())
        entry.bind("<MouseWheel>", self._on_mousewheel)
        entry.bind("<Button-4>", lambda e: self.canvas.yview("scroll", -3, "units"))
        entry.bind("<Button-5>", lambda e: self.canvas.yview("scroll", 3, "units"))
        entry.bind("<FocusOut>", self._destroy_edit)
        self._edit_entry = entry

    def _destroy_edit(self, event=None):
        if self._edit_entry is not None:
            self._submit_answer()
            try:
                self._edit_entry.destroy()
            except tk.TclError:
                pass
            self._edit_entry = None
            self._edit_data_idx = None
            self._edit_col_idx = None
            self._redraw()
            self._update_status()
            total_blanks = len(self.hidden_cols) * len(self.data)
            if total_blanks > 0 and len(self.results) >= total_blanks:
                correct = sum(1 for v in self.results.values() if v == "exact")
                partial = sum(1 for v in self.results.values() if v == "partial")
                total = len(self.results)
                msg = f"すべての回答が完了しました！\n正解数: {correct}/{total}（{correct/total*100:.1f}%）"
                if partial:
                    msg += f"（近似: {partial}）"
                messagebox.showinfo("試験完了", msg)

    # ═══════════════════════ Answer logic ═══════════════════════

    def _submit_answer(self):
        if self._edit_entry is None:
            return
        user_answer = self._edit_entry.get().strip()
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        if data_idx is None or col_idx is None:
            return
        if col_idx not in self.hidden_cols:
            return

        flat_idx = self.exam_map[data_idx]
        correct_answer = self.flat_data[flat_idx][col_idx].strip()
        if user_answer == correct_answer:
            match = "exact"
        elif user_answer and user_answer in correct_answer:
            match = "partial"
        else:
            match = "wrong"

        self.data[data_idx][col_idx] = user_answer
        self.answers[(data_idx, col_idx)] = user_answer
        self.results[(data_idx, col_idx)] = match

    def _see_row(self, data_idx):
        canvas_h = self.canvas.winfo_height()
        if canvas_h <= 0:
            return
        y_top = int(self.canvas.canvasy(0))
        y_bot = int(self.canvas.canvasy(canvas_h))
        cell_top = self._header_h + data_idx * self._row_h
        cell_bot = cell_top + self._row_h
        if cell_top < y_top:
            frac = cell_top / max(1, self._header_h + len(self.data) * self._row_h)
            self.canvas.yview("moveto", frac)
        elif cell_bot > y_bot:
            frac = (cell_bot - canvas_h + 4) / max(1, self._header_h + len(self.data) * self._row_h)
            self.canvas.yview("moveto", frac)

    def _on_exam_enter(self, event):
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        self._destroy_edit()
        if data_idx is None:
            return "break"
        for di in range(data_idx + 1, len(self.data)):
            if col_idx in self.hidden_cols and (di, col_idx) not in self.results:
                self._see_row(di)
                self.canvas.update_idletasks()
                self._start_edit(di, col_idx)
                return "break"
        for di in range(0, data_idx):
            if col_idx in self.hidden_cols and (di, col_idx) not in self.results:
                self._see_row(di)
                self.canvas.update_idletasks()
                self._start_edit(di, col_idx)
                return "break"
        return "break"

    def _on_exam_tab(self, event):
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        self._destroy_edit()
        if data_idx is None:
            return "break"

        hidden_sorted = sorted(self.hidden_cols)
        found = False

        for next_col in hidden_sorted:
            if next_col != col_idx and (data_idx, next_col) not in self.results:
                self._start_edit(data_idx, next_col)
                found = True
                break

        if not found:
            for di in range(data_idx + 1, len(self.data)):
                for next_col in hidden_sorted:
                    if (di, next_col) not in self.results:
                        self._see_row(di)
                        self.canvas.update_idletasks()
                        self._start_edit(di, next_col)
                        found = True
                        break
                if found:
                    break

        if not found:
            for di in range(0, data_idx):
                for next_col in hidden_sorted:
                    if (di, next_col) not in self.results:
                        self._see_row(di)
                        self.canvas.update_idletasks()
                        self._start_edit(di, next_col)
                        found = True
                        break
                if found:
                    break

        return "break"

    def on_close(self):
        self.root.destroy()
        logger.info("単語帳 試験モードを終了しました")


if __name__ == "__main__":
    TangoExam()

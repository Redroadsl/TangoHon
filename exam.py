import os
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COL_NAMES = ["kanji", "kana", "trans", "pos", "phrase"]
COL_LABELS = {"kanji": "漢字", "kana": "仮名", "trans": "翻訳", "pos": "詞性", "phrase": "短语"}
COL_MAP = {"kanji": 0, "kana": 1, "trans": 2, "pos": 3, "phrase": 4}
COL_WIDTHS = {"index": 40, "kanji": 150, "kana": 160, "trans": 220, "pos": 60, "phrase": 200}
ROW_H = 26
HEADER_H = 24


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
        self.answers = {}
        self.results = {}

        self._edit_entry = None
        self._edit_data_idx = None
        self._edit_col_idx = None

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
        ttk.Label(toolbar, text="  出題中は空欄をクリックして入力", foreground="gray").pack(side=tk.LEFT)

        self.btn_reset = ttk.Button(toolbar, text="リセット", command=self.reset_exam, width=8, state=tk.DISABLED)
        self.btn_reset.pack(side=tk.RIGHT, padx=(2, 0))
        self.btn_exam = ttk.Button(toolbar, text="出題設定", command=self.show_exam_dialog, width=10, state=tk.DISABLED)
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

        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._total_w = sum(COL_WIDTHS.values())
        self._cell_font = Font(family="Consolas", size=10)

        # ── Status bar ──
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.enc_status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.enc_status_var,
                  relief=tk.SUNKEN, anchor=tk.E, width=14).pack(side=tk.RIGHT)

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
                              HEADER_H + len(self.data) * ROW_H + 4))

    def _move_edit(self):
        if self._edit_entry is not None and self._edit_data_idx is not None and self._edit_col_idx is not None:
            sx, sy = self._cell_screen_pos(self._edit_data_idx, self._edit_col_idx)
            if sx is not None:
                self._edit_entry.place(x=sx, y=sy, width=COL_WIDTHS[COL_NAMES[self._edit_col_idx]], height=ROW_H)

    def _cell_screen_pos(self, data_idx, col_idx):
        col_name = COL_NAMES[col_idx]
        x = sum(w for cn, w in COL_WIDTHS.items() if list(COL_WIDTHS.keys()).index(cn) < list(COL_WIDTHS.keys()).index(col_name))
        y = HEADER_H + data_idx * ROW_H
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
            correct = sum(1 for v in self.results.values() if v)
            if answered > 0:
                pct = correct / answered * 100
                parts.append(f"正解: {correct}/{answered}（{pct:.1f}%）")
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
        self.answers.clear()
        self.results.clear()
        self.exam_map = list(range(len(self.flat_data)))
        self.btn_exam.config(state=tk.NORMAL if self.flat_data else tk.DISABLED)
        self.btn_reset.config(state=tk.DISABLED)
        self._redraw()
        self._update_status()
        logger.info("ファイル読込完了: %s (%d 語, encoding=%s)", fname, len(self.flat_data), self.encoding.get())

    # ═══════════════════════ Exam ═══════════════════════

    def show_exam_dialog(self):
        if not self.flat_data:
            messagebox.showinfo("確認", "ファイルを先に開いてください")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("出題設定")
        dialog.geometry("320x280")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="隠す列を選択してください（少なくとも1つ）:",
                  font=Font(weight="bold")).pack(pady=(12, 6))

        vars = {}
        for cn in COL_NAMES:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(dialog, text=f"{COL_LABELS[cn]}（{cn}）", variable=var)
            cb.pack(anchor=tk.W, padx=30, pady=3)
            vars[cn] = var

        def on_start():
            selected = [i for i, cn in enumerate(COL_NAMES) if vars[cn].get()]
            if not selected:
                messagebox.showwarning("警告", "少なくとも1つの列を選択してください", parent=dialog)
                return
            if len(selected) >= len(COL_NAMES):
                messagebox.showwarning("警告", "すべての列を隠すことはできません", parent=dialog)
                return
            dialog.destroy()
            self.start_exam(set(selected))

        ttk.Button(dialog, text="出題開始", command=on_start, width=12).pack(pady=(15, 5))

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

        self.btn_reset.config(state=tk.NORMAL)
        self._redraw()
        self._update_status()
        logger.info("試験開始: %d 語, 隠し列=%s", len(self.data),
                     [COL_NAMES[c] for c in sorted(hidden_cols)])

    def reset_exam(self):
        self._destroy_edit()
        self.hidden_cols = set()
        self.answers.clear()
        self.results.clear()
        self.data = [row[:] for row in self.flat_data]
        self.exam_map = list(range(len(self.flat_data)))
        self.btn_reset.config(state=tk.DISABLED)
        self._redraw()
        self._update_status()
        self.show_exam_dialog()
        logger.info("試験をリセットしました")

    # ═══════════════════════ Canvas drawing ═══════════════════════

    def _redraw(self):
        self._destroy_edit()
        self.canvas.delete("all")

        total_h = HEADER_H + len(self.data) * ROW_H + 4
        self.canvas.configure(scrollregion=(0, 0, self._total_w, total_h))

        # Draw header
        x = 0
        header_labels = ["#", "漢字", "仮名", "翻訳", "詞性", "短语"]
        for i, (cn, w) in enumerate(COL_WIDTHS.items()):
            self.canvas.create_rectangle(x, 0, x + w, HEADER_H,
                                         fill="#e8e8e8", outline="#ccc")
            self.canvas.create_text(x + w / 2, HEADER_H / 2, anchor=tk.CENTER,
                                    text=header_labels[i], font=Font(size=10, weight="bold"))
            x += w

        # Draw rows
        for row_idx, row in enumerate(self.data):
            y = HEADER_H + row_idx * ROW_H
            x = 0
            for col_idx, (cn, w) in enumerate(COL_WIDTHS.items()):
                bg = "#f8f8f8" if row_idx % 2 == 0 else "#ffffff"
                self.canvas.create_rectangle(x, y, x + w, y + ROW_H,
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
                        color = "#007700" if self.results[(row_idx, ci)] else "#CC0000"
                    else:
                        color = "#000000"
                    anchor = tk.W
                    tx = x + 6

                self.canvas.create_text(tx, y + ROW_H / 2, anchor=anchor,
                                        text=text, fill=color,
                                        font=self._cell_font, tags="cell")
                x += w

    # ═══════════════════════ Canvas click ═══════════════════════

    def _on_canvas_click(self, event):
        self._destroy_edit()
        if not self.hidden_cols:
            return

        cx = int(self.canvas.canvasx(event.x))
        cy = int(self.canvas.canvasy(event.y))

        if cy < HEADER_H:
            return

        row_idx = (cy - HEADER_H) // ROW_H
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
        if self.results.get((row_idx, col_idx)) == True:
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

        entry = ttk.Entry(self.canvas, font=Font(family="Consolas", size=10))
        entry.place(x=sx, y=sy, width=width, height=ROW_H)
        entry.insert(0, self.data[data_idx][col_idx])
        entry.select_range(0, tk.END)
        entry.focus_set()

        entry.bind("<Return>", self._on_exam_enter)
        entry.bind("<Tab>", self._on_exam_tab)
        entry.bind("<Escape>", lambda e: self._destroy_edit())
        self._edit_entry = entry

    def _destroy_edit(self, event=None):
        if self._edit_entry is not None:
            try:
                self._edit_entry.destroy()
            except tk.TclError:
                pass
            self._edit_entry = None
            self._edit_data_idx = None
            self._edit_col_idx = None

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
        is_correct = (user_answer == correct_answer)

        self.data[data_idx][col_idx] = user_answer
        self.answers[(data_idx, col_idx)] = user_answer
        self.results[(data_idx, col_idx)] = is_correct

        self._redraw()
        self._update_status()

        total_blanks = len(self.hidden_cols) * len(self.data)
        if len(self.results) >= total_blanks:
            correct = sum(1 for v in self.results.values() if v)
            total = len(self.results)
            messagebox.showinfo("試験完了",
                                f"すべての回答が完了しました！\n"
                                f"正解数: {correct}/{total}（{correct/total*100:.1f}%）")

    def _on_exam_enter(self, event):
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        self._submit_answer()
        self._destroy_edit()
        if data_idx is None:
            return "break"
        for di in range(data_idx + 1, len(self.data)):
            if col_idx in self.hidden_cols and (di, col_idx) not in self.results:
                self._start_edit(di, col_idx)
                self.canvas.yview("moveto", (HEADER_H + di * ROW_H) /
                                  max(1, HEADER_H + len(self.data) * ROW_H))
                return "break"
        for di in range(0, data_idx):
            if col_idx in self.hidden_cols and (di, col_idx) not in self.results:
                self._start_edit(di, col_idx)
                self.canvas.yview("moveto", (HEADER_H + di * ROW_H) /
                                  max(1, HEADER_H + len(self.data) * ROW_H))
                return "break"
        return "break"

    def _on_exam_tab(self, event):
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        self._submit_answer()
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
                        self._start_edit(di, next_col)
                        self.canvas.yview("moveto", (HEADER_H + di * ROW_H) /
                                          max(1, HEADER_H + len(self.data) * ROW_H))
                        found = True
                        break
                if found:
                    break

        if not found:
            for di in range(0, data_idx):
                for next_col in hidden_sorted:
                    if (di, next_col) not in self.results:
                        self._start_edit(di, next_col)
                        self.canvas.yview("moveto", (HEADER_H + di * ROW_H) /
                                          max(1, HEADER_H + len(self.data) * ROW_H))
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

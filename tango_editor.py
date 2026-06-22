import os
import csv
import copy
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from tkinter.font import Font

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COL_MAP = {"kanji": 0, "kana": 1, "trans": 2, "pos": 3, "phrase": 4}
COL_NAMES = ["kanji", "kana", "trans", "pos", "phrase"]


class TangoEditor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("単語帳管理ツール")
        self.root.geometry("1100x650")
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        wx = (sw - 1100) // 2
        wy = (sh - 650) // 2
        self.root.geometry(f"1100x650+{wx}+{wy}")

        self.encoding = tk.StringVar(value="gbk")
        self.current_file = None
        self.data = []
        self.filtered = []
        self._saved_state = None
        self._undo_stack = []
        self._undoing = False
        self._sort_reverse = False
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.apply_filter())
        self.encoding.trace_add("write", lambda *_: self._update_status())

        self._edit_entry = None
        self._edit_data_idx = None
        self._edit_col_idx = None
        self._edit_iid = None

        self._build_ui()
        self.refresh_file_list()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-s>", lambda e: self.save_file())
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.mainloop()

    @property
    def dirty(self):
        return self._saved_state is not None and self.data != self._saved_state

    # ═══════════════════════ UI ═══════════════════════

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=26, borderwidth=1, relief="solid")
        style.configure("Treeview.Heading", borderwidth=1, relief="solid", padding=(4, 2))
        style.layout("Treeview", [
            ("Treeview.field", {"sticky": "nswe", "border": 1, "children": [
                ("Treeview.treearea", {"sticky": "nswe"})
            ]})
        ])

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── Left panel ──
        left_frame = ttk.Frame(paned, width=260)
        paned.add(left_frame, weight=0)

        ttk.Label(left_frame, text="ファイル一覧", font=Font(weight="bold")).pack(anchor=tk.W, pady=(0, 4))

        btn_row = ttk.Frame(left_frame)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn_row, text="再読込", command=self.refresh_file_list, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="新規作成", command=self.create_file, width=8).pack(side=tk.LEFT)

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
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_select)
        self.file_listbox.bind("<Button-3>", self.show_file_context_menu)

        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="新規作成", command=self.create_file)
        self.file_context_menu.add_command(label="名前変更", command=self.rename_file)
        self.file_context_menu.add_command(label="削除", command=self.delete_file)

        # ── Right panel ──
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        toolbar = ttk.Frame(right_frame)
        toolbar.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(toolbar, text="単語一覧", font=Font(weight="bold")).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="  ダブルクリックで編集 | Enter↓  Tab→", foreground="gray").pack(side=tk.LEFT)

        ttk.Button(toolbar, text="保存 (Ctrl+S)", command=self.save_file, width=12).pack(side=tk.RIGHT, padx=(2, 0))
        ttk.Button(toolbar, text="元に戻す", command=self.undo, width=8).pack(side=tk.RIGHT, padx=(2, 0))
        ttk.Button(toolbar, text="削除", command=self.delete_word, width=6).pack(side=tk.RIGHT, padx=(2, 0))
        ttk.Button(toolbar, text="追加", command=self.add_word, width=6).pack(side=tk.RIGHT, padx=(2, 0))

        ttk.Entry(toolbar, textvariable=self.search_var, width=18).pack(side=tk.RIGHT)
        ttk.Label(toolbar, text="検索:").pack(side=tk.RIGHT, padx=(10, 2))

        # ── Treeview ──
        tree_area = ttk.Frame(right_frame)
        tree_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        columns = ("index", "kanji", "kana", "trans", "pos", "phrase")
        self.tree = ttk.Treeview(tree_area, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("index", text="#")
        self.tree.heading("kanji", text="漢字", command=lambda: self.sort_by("kanji"))
        self.tree.heading("kana", text="仮名", command=lambda: self.sort_by("kana"))
        self.tree.heading("trans", text="翻訳", command=lambda: self.sort_by("trans"))
        self.tree.heading("pos", text="詞性", command=lambda: self.sort_by("pos"))
        self.tree.heading("phrase", text="短语", command=lambda: self.sort_by("phrase"))
        self.tree.column("index", width=40, anchor=tk.CENTER)
        self.tree.column("kanji", width=150, anchor=tk.W)
        self.tree.column("kana", width=160, anchor=tk.W)
        self.tree.column("trans", width=220, anchor=tk.W)
        self.tree.column("pos", width=60, anchor=tk.CENTER)
        self.tree.column("phrase", width=200, anchor=tk.W)

        vsb = ttk.Scrollbar(tree_area, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(right_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.tree.bind("<Double-1>", self.on_cell_double_click)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Delete>", lambda e: self.delete_word())
        self.tree.tag_configure("even", background="#f5f5f5")

        # Right-click context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="削除", command=self.delete_word)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="追加", command=self.add_word)
        self.tree.bind("<Button-3>", self.show_context_menu)

        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.enc_status_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.enc_status_var,
                  relief=tk.SUNKEN, anchor=tk.E, width=14).pack(side=tk.RIGHT)

    def _update_status(self):
        parts = []
        if self.current_file:
            parts.append(self.current_file)
        parts.append(f"単語数: {len(self.data)}")
        if self.dirty:
            parts.append("変更あり")
        undos = len(self._undo_stack)
        if undos:
            parts.append(f"取り消し可能: {undos}回")
        self.status_var.set("  |  ".join(parts))
        self.enc_status_var.set(f"[{self.encoding.get()}]")

    # ═══════════════════════ Undo ═══════════════════════

    def _ensure_trailing_empty(self):
        if not self.data or any(self.data[-1]):
            self.data.append(["", "", "", "", ""])

    def _data_idx(self, row):
        for i, r in enumerate(self.data):
            if r is row:
                return i
        return -1

    def _push_undo(self):
        if self._undoing:
            return
        self._undo_stack.append(copy.deepcopy(self.data))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._update_status()

    def undo(self):
        if not self._undo_stack:
            return
        self._destroy_edit()
        self._undoing = True
        self.data = self._undo_stack.pop()
        self._undoing = False
        self._ensure_trailing_empty()
        self.apply_filter()
        self._update_status()

    # ═══════════════════════ Inline editing ═══════════════════════

    def on_tree_click(self, event):
        self._destroy_edit()

    def on_cell_double_click(self, event):
        self._destroy_edit()

        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col_id = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not col_id or not iid:
            return

        col_name = self.tree.column(col_id)["id"]
        if col_name == "index":
            return

        col_idx = COL_MAP.get(col_name)
        if col_idx is None:
            return

        data_idx = int(iid)
        if data_idx < 0 or data_idx >= len(self.data):
            return

        x, y, w, h = self.tree.bbox(iid, col_id)
        if x is None:
            return

        self._edit_data_idx = data_idx
        self._edit_col_idx = col_idx
        self._edit_iid = iid

        entry = ttk.Entry(self.tree, font=Font(family="Consolas", size=10))
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, self.data[data_idx][col_idx])
        entry.select_range(0, tk.END)
        entry.focus_set()

        entry.bind("<Return>", self._on_enter)
        entry.bind("<Tab>", self._on_tab)
        entry.bind("<Escape>", lambda e: self._destroy_edit())

        self._edit_entry = entry

    def _destroy_edit(self, event=None):
        if self._edit_entry is not None:
            new_text = self._edit_entry.get().strip()
            if self._edit_data_idx is not None and self._edit_col_idx is not None:
                old_text = self.data[self._edit_data_idx][self._edit_col_idx]
                if new_text != old_text:
                    self._push_undo()
                    self.data[self._edit_data_idx][self._edit_col_idx] = new_text
                    self._ensure_trailing_empty()
                    self._refresh_single_row(self._edit_data_idx)
                self._edit_data_idx = None
                self._edit_col_idx = None
                self._edit_iid = None
            try:
                self._edit_entry.destroy()
            except tk.TclError:
                pass
            self._edit_entry = None
            self._update_status()

    def _on_enter(self, event):
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        self._destroy_edit()
        if data_idx is None:
            return "break"
        for fi, row in enumerate(self.filtered):
            if row is self.data[data_idx]:
                next_fi = fi + 1
                if next_fi < len(self.filtered):
                    next_data_idx = self._data_idx(self.filtered[next_fi])
                    self.tree.selection_set(str(next_data_idx))
                    self.tree.see(str(next_data_idx))
                    self._start_edit(next_data_idx, col_idx)
                break
        return "break"

    def _on_tab(self, event):
        data_idx = self._edit_data_idx
        col_idx = self._edit_col_idx
        self._destroy_edit()
        if data_idx is None:
            return "break"
        next_col = col_idx + 1
        if next_col < 5:
            self._start_edit(data_idx, next_col)
        return "break"

    def _start_edit(self, data_idx, col_idx):
        iid = str(data_idx)
        col_name = COL_NAMES[col_idx]
        if not self.tree.exists(iid):
            return
        x, y, w, h = self.tree.bbox(iid, col_name)
        if x is None:
            return

        self._edit_data_idx = data_idx
        self._edit_col_idx = col_idx
        self._edit_iid = iid

        entry = ttk.Entry(self.tree, font=Font(family="Consolas", size=10))
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, self.data[data_idx][col_idx])
        entry.select_range(0, tk.END)
        entry.focus_set()

        entry.bind("<Return>", self._on_enter)
        entry.bind("<Tab>", self._on_tab)
        entry.bind("<Escape>", lambda e: self._destroy_edit())
        self._edit_entry = entry

    # ═══════════════════════ File listing ═══════════════════════

    def csv_files(self):
        return sorted(f for f in os.listdir(BASE_DIR) if f.upper().endswith(".CSV"))

    def refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for f in self.csv_files():
            self.file_listbox.insert(tk.END, f)
        self._update_status()

    def create_file(self):
        name = simpledialog.askstring("新規作成", "ファイル名（例: 301）:", parent=self.root)
        if not name:
            return
        if not name.upper().endswith(".CSV"):
            name += ".CSV"
        path = os.path.join(BASE_DIR, name)
        if os.path.exists(path):
            messagebox.showwarning("警告", "ファイルが既に存在します")
            return
        try:
            with open(path, "w", encoding=self.encoding.get(), newline="") as f:
                pass
            self.refresh_file_list()
            self.status_var.set(f"作成しました: {name}")
        except Exception as e:
            messagebox.showerror("エラー", str(e))

    def show_file_context_menu(self, event):
        idx = self.file_listbox.nearest(event.y)
        if idx >= 0:
            self.file_listbox.selection_clear(0, tk.END)
            self.file_listbox.selection_set(idx)
            self.file_listbox.activate(idx)
        self.file_context_menu.tk_popup(event.x_root, event.y_root)

    def rename_file(self):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        old_name = self.file_listbox.get(sel[0])
        new_name = simpledialog.askstring("名前変更", "新しいファイル名:", initialvalue=old_name, parent=self.root)
        if not new_name or new_name == old_name:
            return
        if not new_name.upper().endswith(".CSV"):
            new_name += ".CSV"
        old_path = os.path.join(BASE_DIR, old_name)
        new_path = os.path.join(BASE_DIR, new_name)
        if os.path.exists(new_path):
            messagebox.showwarning("警告", "ファイルが既に存在します")
            return
        try:
            os.rename(old_path, new_path)
            if self.current_file == old_name:
                self.current_file = new_name
            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("エラー", str(e))

    def delete_file(self):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        fname = self.file_listbox.get(sel[0])
        if not messagebox.askyesno("確認", f"「{fname}」を削除しますか？"):
            return
        try:
            os.remove(os.path.join(BASE_DIR, fname))
            if self.current_file == fname:
                self.current_file = None
                self.data.clear()
                self._saved_state = None
                self.apply_filter()
            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("エラー", str(e))

    # ═══════════════════════ File I/O ═══════════════════════

    def on_file_select(self, event):
        sel = self.file_listbox.curselection()
        if not sel:
            return
        fname = self.file_listbox.get(sel[0])
        if self.dirty:
            if messagebox.askyesno("未保存", "変更が保存されていません。保存しますか？"):
                self.save_file()
        self._destroy_edit()
        self.load_file(fname)

    def load_file(self, fname):
        path = os.path.join(BASE_DIR, fname)
        self.current_file = fname
        encodings_to_try = list(dict.fromkeys([self.encoding.get(), "utf-8", "gbk", "cp932", "euc-jp"]))
        self.data.clear()
        self._undo_stack.clear()
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
                    self.data = rows
                    self.encoding.set(enc)
                    break
            except (UnicodeDecodeError, UnicodeError) as e:
                self.data.clear()
                last_error = e
                continue
            except Exception as e:
                last_error = e
                break
        else:
            if last_error:
                messagebox.showerror("読込エラー", f"{path}\n{last_error}")
            self.data.clear()
        self._ensure_trailing_empty()
        self._saved_state = copy.deepcopy(self.data)
        self.apply_filter()
        self._update_status()

    def save_file(self):
        if not self.current_file:
            messagebox.showwarning("警告", "ファイルが選択されていません")
            return
        path = os.path.join(BASE_DIR, self.current_file)
        enc = self.encoding.get()
        try:
            rows_to_save = [row for row in self.data if any(cell.strip() for cell in row)]
            with open(path, "w", encoding=enc, newline="") as f:
                writer = csv.writer(f)
                writer.writerows(rows_to_save)
            self._saved_state = copy.deepcopy(self.data)
            self._update_status()
            messagebox.showinfo("保存完了", f"{self.current_file}\n{len(self.data)} 語を保存しました")
        except Exception as e:
            messagebox.showerror("保存エラー", str(e))

    def on_close(self):
        self._destroy_edit()
        if self.dirty:
            if messagebox.askyesno("未保存", "変更が保存されていません。保存しますか？"):
                self.save_file()
        self.root.destroy()

    # ═══════════════════════ Display ═══════════════════════

    def apply_filter(self):
        keyword = self.search_var.get().strip().lower()
        if keyword:
            self.filtered = [row for row in self.data
                             if keyword in row[0].lower()
                             or keyword in row[1].lower()
                             or keyword in row[2].lower()
                             or keyword in row[3].lower()
                             or keyword in row[4].lower()]
        else:
            self.filtered = list(self.data)
        self.refresh_table()

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for fi, row in enumerate(self.filtered):
            data_idx = self._data_idx(row)
            tag = "even" if fi % 2 == 0 else ""
            self.tree.insert("", tk.END, iid=str(data_idx),
                             values=(str(fi + 1), row[0], row[1], row[2], row[3], row[4]),
                             tags=(tag,) if tag else ())

    def _refresh_single_row(self, data_idx):
        iid = str(data_idx)
        if not self.tree.exists(iid):
            self.refresh_table()
            return
        row = self.data[data_idx]
        fi = next((i for i, r in enumerate(self.filtered) if r is row), None)
        if fi is None:
            self.refresh_table()
            return
        self.tree.item(iid, values=(str(fi + 1), row[0], row[1], row[2], row[3], row[4]),
                       tags=("even",) if fi % 2 == 0 else ())

    def sort_by(self, col):
        idx = COL_MAP[col]
        self.filtered.sort(key=lambda r: r[idx].lower(), reverse=self._sort_reverse)
        self._sort_reverse = not self._sort_reverse
        self.refresh_table()

    def _get_selected_data_idx(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("確認", "単語を選択してください")
            return None
        iid = sel[0]
        data_idx = int(iid)
        if data_idx < 0 or data_idx >= len(self.data):
            return None
        return data_idx

    def show_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
        self.context_menu.tk_popup(event.x_root, event.y_root)

    # ═══════════════════════ CRUD ═══════════════════════

    def add_word(self):
        self._destroy_edit()
        data_idx = self._get_selected_data_idx()
        self._push_undo()
        if data_idx is not None:
            self.data.insert(data_idx, ["", "", "", "", ""])
        else:
            self.data.append(["", "", "", "", ""])
            data_idx = len(self.data) - 1
        self._ensure_trailing_empty()
        self.apply_filter()
        iid = str(data_idx)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
        self._update_status()

    def delete_word(self):
        self._destroy_edit()
        data_idx = self._get_selected_data_idx()
        if data_idx is None:
            return
        row = self.data[data_idx]
        if messagebox.askyesno("確認", f"「{row[0] or row[1]}」を削除しますか？"):
            self._push_undo()
            self.data.pop(data_idx)
            self._ensure_trailing_empty()
            self.apply_filter()
            self._update_status()


if __name__ == "__main__":
    TangoEditor()

"""
Windows FileTransfer Logger v2
==============================

v1 (Tkinter, tek klasor, tek thread, shutil.move) -> v2 (PyQt6):

  - Dosya / exe / resim / klasor — her seyi, birden fazla ogeyi tasir/kopyalar.
  - En hizli aktarim: tum CPU thread'leriyle paralel kopyalama (ThreadPoolExecutor),
    8 MB tampon; ayni disk icinde tasimada anlik os.replace.
  - Kopyala / Tasi modu, boyut dogrulama.
  - Loglama + HTML raporlama (dosya basi boyut/sure/hiz/durum).
  - Canli ilerleme: genel %, MB/s, dosya x/y, ETA, anlik dosya, iptal.
  - Arayuz: gece mavisi yazilar, Verdana kalin.

  Alea iacta est. — Engin Can Cicek
"""

import os
import sys
import time
import html
import shutil
import logging
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPlainTextEdit,
    QFileDialog, QRadioButton, QButtonGroup, QCheckBox, QSpinBox, QMessageBox,
    QGridLayout, QAbstractItemView,
)

MIDNIGHT = "#12315e"          # gece mavisi
MIDNIGHT_DARK = "#0a1f44"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


LOG_DIR = app_dir()
REPORT_DIR = LOG_DIR / "raporlar"
REPORT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "filetransfer.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8",
)


def human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024


def human_time(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec} sn"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} dk {s} sn"
    h, m = divmod(m, 60)
    return f"{h} sa {m} dk"


# --------------------------------------------------------------------------
# Aktarim motoru (QThread)
# --------------------------------------------------------------------------
class TransferWorker(QThread):
    progress = pyqtSignal(dict)          # canli ilerleme
    file_done = pyqtSignal(dict)         # dosya basi sonuc
    log = pyqtSignal(str)
    finished_report = pyqtSignal(dict)   # ozet + rapor yolu

    def __init__(self, sources, dest, mode, workers, verify, buf_mb=8):
        super().__init__()
        self.sources = [Path(s) for s in sources]
        self.dest = Path(dest)
        self.mode = mode                 # "copy" | "move"
        self.workers = max(1, int(workers))
        self.verify = verify
        self.buf = int(buf_mb) * 1024 * 1024
        self._cancel = threading.Event()
        self._done_bytes = 0
        self._lock = threading.Lock()
        self._current = ""

    def cancel(self):
        self._cancel.set()

    # --- kaynaklari tek tek dosyalara ac (klasor yapisini koru) ---
    def _enumerate(self):
        items = []
        for p in self.sources:
            if p.is_file():
                items.append((p, self.dest / p.name, p.stat().st_size))
            elif p.is_dir():
                base = p.parent          # klasorun kendisi de hedefte olusur
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        fp = Path(root) / f
                        try:
                            sz = fp.stat().st_size
                        except OSError:
                            sz = 0
                        items.append((fp, self.dest / fp.relative_to(base), sz))
        return items

    # --- tek dosya kopyala/tasi ---
    def _copy_one(self, src: Path, dst: Path, size: int) -> dict:
        res = {"src": str(src), "dst": str(dst), "size": size,
               "seconds": 0.0, "status": "TAMAM", "error": ""}
        if self._cancel.is_set():
            res["status"] = "IPTAL"
            return res
        with self._lock:
            self._current = src.name
        t0 = time.perf_counter()
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)

            fast_moved = False
            if self.mode == "move":
                try:
                    os.replace(src, dst)          # ayni disk -> anlik
                    fast_moved = True
                except OSError:
                    fast_moved = False            # farkli disk -> kopyala+sil

            if not fast_moved:
                with open(src, "rb", buffering=0) as fsrc, \
                        open(dst, "wb", buffering=0) as fdst:
                    while True:
                        if self._cancel.is_set():
                            raise InterruptedError("iptal edildi")
                        chunk = fsrc.read(self.buf)
                        if not chunk:
                            break
                        fdst.write(chunk)
                        with self._lock:
                            self._done_bytes += len(chunk)
                shutil.copystat(src, dst, follow_symlinks=False)
                if self.verify and dst.stat().st_size != size:
                    raise IOError("boyut dogrulama basarisiz")
                if self.mode == "move":
                    os.remove(src)
            else:
                with self._lock:
                    self._done_bytes += size

            res["seconds"] = time.perf_counter() - t0
        except Exception as e:                    # noqa: BLE001
            res["status"] = "HATA" if not self._cancel.is_set() else "IPTAL"
            res["error"] = str(e)
            res["seconds"] = time.perf_counter() - t0
            # yarim kalan hedefi temizle
            try:
                if dst.exists() and res["status"] == "HATA":
                    dst.unlink()
            except OSError:
                pass
        return res

    def run(self):
        t_start = time.perf_counter()
        self.log.emit("Kaynaklar taraniyor...")
        try:
            items = self._enumerate()
        except Exception as e:                    # noqa: BLE001
            self.log.emit(f"Tarama hatasi: {e}")
            self.finished_report.emit({"error": str(e)})
            return

        total_bytes = sum(i[2] for i in items)
        files_total = len(items)
        if files_total == 0:
            self.log.emit("Aktarilacak dosya bulunamadi.")
            self.finished_report.emit({"empty": True})
            return

        self.log.emit(
            f"{files_total} dosya  |  {human(total_bytes)}  |  "
            f"{self.workers} is parcacigi  |  mod: "
            f"{'TASI' if self.mode == 'move' else 'KOPYALA'}")
        logging.info(
            f"BASLADI mod={self.mode} dosya={files_total} "
            f"boyut={total_bytes} thread={self.workers} -> {self.dest}")

        results = []
        last_t, last_b = t_start, 0

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {ex.submit(self._copy_one, s, d, sz): None
                       for s, d, sz in items}
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=0.15)
                for fut in done:
                    r = fut.result()
                    results.append(r)
                    self.file_done.emit(r)
                    if r["status"] == "HATA":
                        self.log.emit(f"  HATA: {Path(r['src']).name} -> {r['error']}")
                        logging.error(f"HATA {r['src']} -> {r['error']}")

                now = time.perf_counter()
                with self._lock:
                    db = self._done_bytes
                    cur = self._current
                dt = now - last_t
                speed = (db - last_b) / dt if dt > 0 else 0.0
                last_t, last_b = now, db
                eta = (total_bytes - db) / speed if speed > 100 else -1
                self.progress.emit({
                    "done": db, "total": total_bytes,
                    "files_done": len(results), "files_total": files_total,
                    "speed": speed, "current": cur,
                    "elapsed": now - t_start, "eta": eta,
                })
                if self._cancel.is_set():
                    for f in pending:
                        f.cancel()

        # --- ozet + rapor ---
        elapsed = time.perf_counter() - t_start
        ok = sum(1 for r in results if r["status"] == "TAMAM")
        err = sum(1 for r in results if r["status"] == "HATA")
        cancelled = sum(1 for r in results if r["status"] == "IPTAL")
        moved_bytes = sum(r["size"] for r in results if r["status"] == "TAMAM")
        avg = moved_bytes / elapsed if elapsed > 0 else 0

        report_path = self._write_report(results, {
            "mode": self.mode, "dest": str(self.dest), "elapsed": elapsed,
            "ok": ok, "err": err, "cancelled": cancelled,
            "total_bytes": total_bytes, "moved_bytes": moved_bytes, "avg": avg,
            "files_total": files_total, "workers": self.workers,
        })
        logging.info(
            f"BITTI tamam={ok} hata={err} iptal={cancelled} "
            f"sure={elapsed:.1f}s ort={human(avg)}/s rapor={report_path.name}")

        self.finished_report.emit({
            "ok": ok, "err": err, "cancelled": cancelled, "elapsed": elapsed,
            "avg": avg, "moved_bytes": moved_bytes, "report": str(report_path),
            "cancelled_run": self._cancel.is_set(),
        })

    # --- HTML rapor ---
    def _write_report(self, results, s) -> Path:
        ts = datetime.now()
        path = REPORT_DIR / f"rapor_{ts:%Y%m%d_%H%M%S}.html"
        rows = []
        for r in results:
            spd = r["size"] / r["seconds"] if r["seconds"] > 0 else 0
            color = {"TAMAM": "#1a7f37", "HATA": "#b00020",
                     "IPTAL": "#8a6d00"}.get(r["status"], "#000")
            rows.append(
                f"<tr><td>{html.escape(Path(r['src']).name)}</td>"
                f"<td class='r'>{human(r['size'])}</td>"
                f"<td class='r'>{r['seconds']:.2f} sn</td>"
                f"<td class='r'>{human(spd)}/s</td>"
                f"<td style='color:{color};font-weight:bold'>{r['status']}"
                f"{(' — ' + html.escape(r['error'])) if r['error'] else ''}</td>"
                f"<td class='p'>{html.escape(r['dst'])}</td></tr>")

        doc = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>Aktarim Raporu {ts:%Y-%m-%d %H:%M:%S}</title><style>
body{{font-family:Verdana,Arial,sans-serif;color:{MIDNIGHT};margin:28px;background:#f7f9fc}}
h1{{color:{MIDNIGHT_DARK};margin:0 0 4px}}
.sum{{background:#fff;border:1px solid #d7deea;border-radius:10px;padding:14px 18px;margin:14px 0;display:flex;flex-wrap:wrap;gap:20px}}
.sum div b{{display:block;font-size:20px;color:{MIDNIGHT_DARK}}}
.sum div span{{font-size:12px;color:#5a6b86}}
table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid #d7deea;border-radius:10px;overflow:hidden}}
th,td{{padding:8px 10px;border-bottom:1px solid #eef1f6;font-size:13px;text-align:left}}
th{{background:{MIDNIGHT};color:#fff}}
td.r{{text-align:right;white-space:nowrap}} td.p{{color:#5a6b86;font-size:11px}}
.motto{{margin-top:18px;font-style:italic;color:{MIDNIGHT}}}
</style></head><body>
<h1>Windows FileTransfer Logger — Aktarim Raporu</h1>
<div style="color:#5a6b86">{ts:%d.%m.%Y %H:%M:%S} &nbsp;•&nbsp; Hedef: {html.escape(s['dest'])} &nbsp;•&nbsp; Mod: {'TASI' if s['mode']=='move' else 'KOPYALA'}</div>
<div class="sum">
  <div><b>{s['files_total']}</b><span>toplam dosya</span></div>
  <div><b style="color:#1a7f37">{s['ok']}</b><span>basarili</span></div>
  <div><b style="color:#b00020">{s['err']}</b><span>hata</span></div>
  <div><b style="color:#8a6d00">{s['cancelled']}</b><span>iptal</span></div>
  <div><b>{human(s['moved_bytes'])}</b><span>aktarilan</span></div>
  <div><b>{human_time(s['elapsed'])}</b><span>sure</span></div>
  <div><b>{human(s['avg'])}/s</b><span>ortalama hiz</span></div>
  <div><b>{s['workers']}</b><span>is parcacigi</span></div>
</div>
<table><thead><tr><th>Dosya</th><th>Boyut</th><th>Sure</th><th>Hiz</th><th>Durum</th><th>Hedef yol</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="motto">Alea iacta est. — Engin Can Cicek</p>
</body></html>"""
        path.write_text(doc, encoding="utf-8")
        return path


# --------------------------------------------------------------------------
# Surukle-birak destekli liste
# --------------------------------------------------------------------------
class DropList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            self.add_path(url.toLocalFile())

    def add_path(self, path):
        if not path:
            return
        for i in range(self.count()):
            if self.item(i).text() == path:
                return
        it = QListWidgetItem(("📁 " if Path(path).is_dir() else "📄 ") + path)
        it.setData(Qt.ItemDataRole.UserRole, path)
        self.addItem(it)

    def paths(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.count())]


# --------------------------------------------------------------------------
# Ana pencere
# --------------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.setWindowTitle("Windows FileTransfer Logger v2")
        self.setMinimumWidth(720)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QVBoxLayout(self)

        title = QLabel("Windows FileTransfer Logger  ·  v2")
        title.setObjectName("title")
        root.addWidget(title)

        # Kaynaklar
        root.addWidget(self._h("Kaynaklar (dosya / klasor / exe / resim — surukleyip birakabilirsin)"))
        self.src_list = DropList()
        self.src_list.setFixedHeight(150)
        root.addWidget(self.src_list)

        b = QHBoxLayout()
        for text, fn in (("+ Dosya ekle", self.add_files),
                         ("+ Klasor ekle", self.add_folder),
                         ("Secileni kaldir", self.remove_selected),
                         ("Temizle", self.clear_src)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            b.addWidget(btn)
        root.addLayout(b)

        # Hedef
        root.addWidget(self._h("Hedef klasor"))
        hd = QHBoxLayout()
        self.dest_edit = QLineEdit()
        pick = QPushButton("Hedef sec")
        pick.clicked.connect(self.pick_dest)
        hd.addWidget(self.dest_edit)
        hd.addWidget(pick)
        root.addLayout(hd)

        # Secenekler
        opt = QGridLayout()
        self.rb_copy = QRadioButton("Kopyala")
        self.rb_move = QRadioButton("Tasi")
        self.rb_copy.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_copy)
        grp.addButton(self.rb_move)
        opt.addWidget(self.rb_copy, 0, 0)
        opt.addWidget(self.rb_move, 0, 1)

        self.verify_chk = QCheckBox("Boyut dogrula")
        self.verify_chk.setChecked(True)
        opt.addWidget(self.verify_chk, 0, 2)

        opt.addWidget(QLabel("Is parcacigi:"), 0, 3)
        self.workers_spin = QSpinBox()
        cpu = os.cpu_count() or 4
        self.workers_spin.setRange(1, cpu * 4)
        self.workers_spin.setValue(cpu)                # tum thread'ler
        self.workers_spin.setToolTip(f"Bu makinede {cpu} mantiksal cekirdek var")
        opt.addWidget(self.workers_spin, 0, 4)
        opt.setColumnStretch(5, 1)
        root.addLayout(opt)

        # Ilerleme
        self.bar = QProgressBar()
        self.bar.setValue(0)
        root.addWidget(self.bar)
        self.stat_lbl = QLabel("Hazir.")
        self.stat_lbl.setObjectName("stat")
        root.addWidget(self.stat_lbl)

        # Baslat / Iptal / Rapor
        act = QHBoxLayout()
        self.start_btn = QPushButton("AKTARIMI BASLAT")
        self.start_btn.setObjectName("go")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Iptal")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        self.report_btn = QPushButton("Son raporu ac")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self.open_report)
        act.addWidget(self.start_btn, 2)
        act.addWidget(self.cancel_btn, 1)
        act.addWidget(self.report_btn, 1)
        root.addLayout(act)

        # Kayit
        root.addWidget(self._h("Kayit"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(130)
        root.addWidget(self.log)

        foot = QLabel("Alea iacta est.  —  Engin Can Cicek")
        foot.setObjectName("foot")
        foot.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(foot)

        self._last_report = None

    def _h(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("hdr")
        return lbl

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget {{ background:#eef2f8; color:{MIDNIGHT};
                       font-family:Verdana; font-weight:bold; font-size:12px; }}
            QLabel#title {{ font-size:20px; color:{MIDNIGHT_DARK}; padding:2px 0 6px; }}
            QLabel#hdr {{ color:{MIDNIGHT_DARK}; padding-top:6px; }}
            QLabel#stat {{ color:{MIDNIGHT}; }}
            QLabel#foot {{ color:{MIDNIGHT}; font-style:italic; padding-top:6px; }}
            QLineEdit, QListWidget, QPlainTextEdit, QSpinBox {{
                background:#ffffff; border:1px solid #b9c5db; border-radius:6px;
                padding:4px; color:{MIDNIGHT}; }}
            QPushButton {{ background:#ffffff; border:1px solid #9fb0cf;
                border-radius:6px; padding:6px 10px; color:{MIDNIGHT_DARK}; }}
            QPushButton:hover {{ background:#e3ebf7; }}
            QPushButton:disabled {{ color:#9aa7bd; border-color:#d0d8e6; }}
            QPushButton#go {{ background:{MIDNIGHT}; color:#ffffff; border:none;
                padding:10px; font-size:13px; }}
            QPushButton#go:hover {{ background:{MIDNIGHT_DARK}; }}
            QProgressBar {{ border:1px solid #b9c5db; border-radius:6px;
                background:#ffffff; height:22px; text-align:center; color:{MIDNIGHT_DARK}; }}
            QProgressBar::chunk {{ background:{MIDNIGHT}; border-radius:5px; }}
        """)

    # --- kaynak islemleri ---
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Dosya(lar) sec")
        for f in files:
            self.src_list.add_path(f)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Klasor sec")
        if d:
            self.src_list.add_path(d)

    def remove_selected(self):
        for it in self.src_list.selectedItems():
            self.src_list.takeItem(self.src_list.row(it))

    def clear_src(self):
        self.src_list.clear()

    def pick_dest(self):
        d = QFileDialog.getExistingDirectory(self, "Hedef klasor sec")
        if d:
            self.dest_edit.setText(d)

    def _log(self, msg):
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {msg}")

    # --- aktarim ---
    def start(self):
        sources = self.src_list.paths()
        dest = self.dest_edit.text().strip()
        if not sources:
            QMessageBox.warning(self, "Uyari", "En az bir kaynak ekleyin.")
            return
        if not dest:
            QMessageBox.warning(self, "Uyari", "Hedef klasor secin.")
            return
        Path(dest).mkdir(parents=True, exist_ok=True)

        mode = "move" if self.rb_move.isChecked() else "copy"
        self.worker = TransferWorker(
            sources, dest, mode, self.workers_spin.value(),
            self.verify_chk.isChecked())
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self._log)
        self.worker.finished_report.connect(self.on_finished)

        self._set_running(True)
        self.bar.setValue(0)
        self._log("——— Aktarim baslatildi ———")
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self._log("Iptal istendi, mevcut dosyalar tamamlaniyor...")

    def on_progress(self, p):
        if p["total"] > 0:
            self.bar.setValue(int(p["done"] * 100 / p["total"]))
        eta = human_time(p["eta"]) if p["eta"] >= 0 else "—"
        self.stat_lbl.setText(
            f"{human(p['done'])} / {human(p['total'])}  "
            f"·  {p['files_done']}/{p['files_total']} dosya  "
            f"·  {human(p['speed'])}/s  ·  ETA {eta}  "
            f"·  {p['current']}")

    def on_finished(self, s):
        self._set_running(False)
        if s.get("empty"):
            self._log("Aktarilacak dosya yok.")
            return
        if s.get("error"):
            self._log(f"Hata: {s['error']}")
            return
        self.bar.setValue(100)
        self._last_report = s.get("report")
        self.report_btn.setEnabled(bool(self._last_report))
        head = "Aktarim IPTAL edildi" if s.get("cancelled_run") else "Aktarim tamamlandi"
        self._log(
            f"——— {head} ———  basarili={s['ok']}  hata={s['err']}  "
            f"iptal={s['cancelled']}  ·  {human(s['moved_bytes'])}  "
            f"·  {human_time(s['elapsed'])}  ·  ort {human(s['avg'])}/s")
        self.stat_lbl.setText(
            f"{head}: {s['ok']} basarili, {s['err']} hata  ·  "
            f"ortalama {human(s['avg'])}/s")
        if s["err"] == 0 and not s.get("cancelled_run"):
            QMessageBox.information(
                self, "Tamamlandi",
                f"{s['ok']} dosya aktarildi.\n{human(s['moved_bytes'])} · "
                f"{human_time(s['elapsed'])} · ort {human(s['avg'])}/s\n\n"
                "Alea iacta est.")

    def _set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for w in (self.src_list, self.dest_edit, self.rb_copy, self.rb_move,
                  self.verify_chk, self.workers_spin):
            w.setEnabled(not running)

    def open_report(self):
        if self._last_report and Path(self._last_report).exists():
            webbrowser.open(self._last_report)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Verdana", 10, QFont.Weight.Bold))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

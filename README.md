# Windows FileTransfer Logger

> **GUI-based folder transfer tool with automated audit logging**

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)](https://www.python.org/)
[![Tkinter](https://img.shields.io/badge/GUI-Tkinter-orange)](https://docs.python.org/3/library/tkinter.html)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)](https://www.microsoft.com/windows)

## Overview

**Windows FileTransfer Logger** is a desktop GUI application for safely moving folders between directories. Every operation is timestamped and written to an audit log, making it ideal for regulated environments or workflows that require a transfer trail.

## Features

- **Graphical Interface** — simple source / destination folder picker built with Tkinter
- **Audit Logging** — every move (success or failure) is recorded in `dosya_hareketleri.log` with full timestamps
- **Multi-threaded** — folder moves run in a background thread; the UI stays responsive during large transfers
- **Progress Indicator** — animated progress bar provides visual feedback
- **Standalone Executable** — can be packaged with PyInstaller for zero-install deployment

## Requirements

```
tkinter  # included with standard Python on Windows
```

No third-party packages are required. For standalone `.exe` packaging:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed Windows-FileTransfer-Logger.py
```

## Usage

```bash
python Windows-FileTransfer-Logger.py
```

1. Click **Klasör Seç** to select the source folder.
2. Click **Hedef Seç** to choose the destination.
3. Click **KLASÖRÜ TAŞI** to start the transfer.
4. The result (success or error) is shown in a pop-up and written to `dosya_hareketleri.log`.

## Log Format

```
2025-01-14 18:21:34,012 - INFO  - TASIMA_BASARILI: C:\Source\FolderA -> D:\Archive\FolderA
2025-01-14 18:25:10,457 - ERROR - TASIMA_HATASI: Source folder not found
```

## Author

**Engin Can Cicek**

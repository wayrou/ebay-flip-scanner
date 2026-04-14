import logging
import os
import queue
import threading
import tkinter as tk
from ctypes import windll
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import main as scanner


APP_ID = "alexh.ebay_flip_scanner"


class QueueLogHandler(logging.Handler):
    def __init__(self, output_queue: "queue.Queue[tuple[str, str]]"):
        super().__init__()
        self.output_queue = output_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.output_queue.put(("log", self.format(record)))


class ScannerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.output_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.worker_thread: threading.Thread | None = None
        self.log_file = scanner.BASE_DIR / "scanner.log"
        self.status_var = tk.StringVar(value="Starting app...")
        self.env_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="Runs scans while this window stays open.")

        self._configure_window()
        self._build_ui()
        self._configure_logging()
        self._refresh_env_status()

        self.root.after(150, self._drain_output_queue)
        self.root.after(350, self.start_scanner)

    def _configure_window(self) -> None:
        self.root.title("eBay Flip Scanner")
        self.root.geometry("900x640")
        self.root.minsize(760, 520)
        self.root.configure(bg="#f6f1e6")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        main_frame = ttk.Frame(self.root, padding=18)
        main_frame.pack(fill="both", expand=True)

        header = ttk.Frame(main_frame)
        header.pack(fill="x")

        title = tk.Label(
            header,
            text="eBay Flip Scanner",
            font=("Segoe UI Semibold", 20),
            bg="#f6f1e6",
            fg="#1d2a38",
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            header,
            text="Open this app and it keeps scanning across multiple resale markets until you close it.",
            font=("Segoe UI", 10),
            bg="#f6f1e6",
            fg="#506174",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        card = tk.Frame(
            main_frame,
            bg="#fffaf1",
            bd=1,
            relief="solid",
            highlightbackground="#d8ccba",
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(14, 12))

        status_label = tk.Label(
            card,
            textvariable=self.status_var,
            font=("Segoe UI Semibold", 11),
            bg="#fffaf1",
            fg="#16324f",
            anchor="w",
        )
        status_label.pack(fill="x", padx=14, pady=(12, 4))

        env_label = tk.Label(
            card,
            textvariable=self.env_var,
            font=("Consolas", 9),
            bg="#fffaf1",
            fg="#5a4d3c",
            anchor="w",
            justify="left",
        )
        env_label.pack(fill="x", padx=14, pady=(0, 4))

        mode_label = tk.Label(
            card,
            textvariable=self.mode_var,
            font=("Segoe UI", 9),
            bg="#fffaf1",
            fg="#6b5a43",
            anchor="w",
        )
        mode_label.pack(fill="x", padx=14, pady=(0, 12))

        controls = ttk.Frame(main_frame)
        controls.pack(fill="x", pady=(0, 10))

        self.start_button = ttk.Button(controls, text="Start Scanner", command=self.start_scanner)
        self.start_button.pack(side="left")

        self.stop_button = ttk.Button(controls, text="Stop Scanner", command=self.stop_scanner)
        self.stop_button.pack(side="left", padx=(8, 0))

        self.open_log_button = ttk.Button(controls, text="Open Log", command=self.open_log_file)
        self.open_log_button.pack(side="left", padx=(8, 0))

        self.log_output = ScrolledText(
            main_frame,
            wrap="word",
            font=("Consolas", 10),
            bg="#13202b",
            fg="#e8f0f7",
            insertbackground="#e8f0f7",
            padx=10,
            pady=10,
        )
        self.log_output.pack(fill="both", expand=True)
        self.log_output.insert(
            "end",
            "Scanner log will appear here.\n"
            f"Logs are also written to {self.log_file}.\n\n",
        )
        self.log_output.configure(state="disabled")

        self._set_button_state(running=False)

    def _configure_logging(self) -> None:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        queue_handler = QueueLogHandler(self.output_queue)
        queue_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)

        scanner.LOGGER.handlers.clear()
        scanner.LOGGER.setLevel(logging.INFO)
        scanner.LOGGER.propagate = False
        scanner.LOGGER.addHandler(queue_handler)
        scanner.LOGGER.addHandler(file_handler)

    def _refresh_env_status(self) -> None:
        present_files = [path.name for path in scanner.ENV_PATHS if path.exists()]
        if present_files:
            self.env_var.set(f"Secrets file detected: {', '.join(present_files)}")
        else:
            self.env_var.set(
                "No secrets file found. Expected one of: "
                + ", ".join(path.name for path in scanner.ENV_PATHS)
            )

    def _set_button_state(self, running: bool) -> None:
        self.start_button.configure(state=("disabled" if running else "normal"))
        self.stop_button.configure(state=("normal" if running else "disabled"))

    def _append_log(self, message: str) -> None:
        self.log_output.configure(state="normal")
        self.log_output.insert("end", message + "\n")
        self.log_output.see("end")
        self.log_output.configure(state="disabled")

    def _update_status(self, message: str) -> None:
        self.output_queue.put(("status", message))

    def _drain_output_queue(self) -> None:
        try:
            while True:
                item_type, payload = self.output_queue.get_nowait()
                if item_type == "log":
                    self._append_log(payload)
                elif item_type == "status":
                    self.status_var.set(payload)
                elif item_type == "stopped":
                    self._set_button_state(running=False)
        except queue.Empty:
            pass

        self.root.after(150, self._drain_output_queue)

    def _run_scanner(self) -> None:
        try:
            scanner.run_forever(stop_event=self.stop_event, on_status=self._update_status)
        except RuntimeError as exc:
            scanner.LOGGER.error("%s", exc)
            self._update_status("Configuration error")
        except Exception:
            scanner.LOGGER.exception("Scanner app worker crashed.")
            self._update_status("Scanner crashed")
        finally:
            self.output_queue.put(("stopped", ""))

    def start_scanner(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        self._refresh_env_status()
        self.status_var.set("Starting scanner...")
        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(target=self._run_scanner, daemon=True)
        self.worker_thread.start()
        self._set_button_state(running=True)

    def stop_scanner(self) -> None:
        if not self.stop_event:
            return

        self.status_var.set("Stopping after the current scan finishes...")
        self.stop_event.set()

    def open_log_file(self) -> None:
        self.log_file.touch(exist_ok=True)
        os.startfile(self.log_file)

    def on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_scanner()
            self.root.after(200, self._close_when_stopped)
            return

        self.root.destroy()

    def _close_when_stopped(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self.root.after(200, self._close_when_stopped)
            return

        self.root.destroy()


def main() -> None:
    try:
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    root = tk.Tk()
    app = ScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

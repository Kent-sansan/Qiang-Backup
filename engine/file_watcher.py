"""File system watcher with global debounce using watchdog."""

import threading
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class DebounceFileHandler(FileSystemEventHandler):
    def __init__(self, extensions, on_change_callback, debounce_seconds=3, max_debounce_seconds=30):
        super().__init__()
        self.extensions = [e.lower() for e in extensions]
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self.max_debounce_seconds = max_debounce_seconds
        self._pending_folders = set()
        self._timer = None
        self._first_event_time = None
        self._lock = threading.Lock()
        self._shutdown = False

    def _should_handle(self, path):
        lowered = path.lower()
        if lowered.endswith((".7z", ".tmp")) or path.endswith("~"):
            return False
        return any(lowered.endswith(ext) for ext in self.extensions)

    def _schedule(self, folder_path):
        folder_path = str(folder_path)
        with self._lock:
            if self._shutdown:
                return
            self._pending_folders.add(folder_path)
            now = time.monotonic()
            if self._first_event_time is None:
                self._first_event_time = now
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            elapsed = now - self._first_event_time
            if elapsed >= self.max_debounce_seconds:
                self._fire_now()
            else:
                remaining = max(0.1, self.debounce_seconds - elapsed)
                self._timer = threading.Timer(remaining, self._on_timer)
                self._timer.start()

    def _on_timer(self):
        with self._lock:
            if self._shutdown:
                return
            self._timer = None
        self._fire_now()

    def _fire_now(self):
        folders = []
        with self._lock:
            if not self._pending_folders:
                return
            folders = [Path(p) for p in self._pending_folders]
            self._pending_folders.clear()
            self._first_event_time = None
        if not self._shutdown:
            self.on_change_callback(folders)

    def shutdown(self):
        self._shutdown = True
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_folders.clear()
            self._first_event_time = None

    def on_modified(self, event):
        if not event.is_directory and self._should_handle(event.src_path):
            self._schedule(Path(event.src_path).parent)

    def on_created(self, event):
        if not event.is_directory and self._should_handle(event.src_path):
            self._schedule(Path(event.src_path).parent)

    def on_deleted(self, event):
        if not event.is_directory and self._should_handle(event.src_path):
            self._schedule(Path(event.src_path).parent)

    def on_moved(self, event):
        if event.is_directory:
            self._schedule(Path(event.src_path).parent)
            self._schedule(Path(event.dest_path).parent)
        else:
            if self._should_handle(event.dest_path):
                self._schedule(Path(event.dest_path).parent)
            if self._should_handle(event.src_path):
                self._schedule(Path(event.src_path).parent)


class FileWatcher:
    def __init__(self):
        self._observer = None
        self._handler = None
        self._source_folders = []

    def start(self, source_folders, extensions, on_change, debounce_seconds=3, max_debounce_seconds=30):
        if self._observer is not None:
            self.stop()
        self._source_folders = [str(Path(f)) for f in source_folders]
        self._handler = DebounceFileHandler(
            extensions, on_change, debounce_seconds, max_debounce_seconds
        )
        self._observer = Observer()
        for folder in source_folders:
            folder_path = Path(folder)
            if folder_path.exists():
                self._observer.schedule(self._handler, str(folder_path), recursive=True)
        self._observer.start()

    def stop(self):
        if self._handler:
            self._handler.shutdown()
            self._handler = None
        if self._observer:
            try:
                self._observer.unschedule_all()
            except Exception:
                pass
            try:
                self._observer.stop()
            except Exception:
                pass
            self._observer = None
        self._source_folders = []

    def is_running(self):
        if self._observer is None:
            return False
        return self._observer.is_alive()

    def health_check(self):
        if not self.is_running():
            return False
        for folder in self._source_folders:
            if not Path(folder).exists():
                return False
        return True

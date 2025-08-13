from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import asyncio
import time
import os

from main import broadcast_event  # fungsi dari FastAPI
from main import event_file

class EventFileHandler(FileSystemEventHandler):
    def __init__(self, loop):
        self.loop = loop

    def on_modified(self, event):
        if os.path.abspath(event.src_path) == os.path.abspath(event_file):
            print(f"[Watcher] File {event_file} berubah, broadcast...")
            asyncio.run_coroutine_threadsafe(broadcast_event(), self.loop)

def start_watcher(loop, path="."):
    event_handler = EventFileHandler(loop)
    observer = Observer()
    observer.schedule(event_handler, path=path, recursive=False)
    observer.start()
    print("[Watcher] Menjalankan file watcher...")

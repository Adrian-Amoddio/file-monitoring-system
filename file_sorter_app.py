import os
import time
import shutil
import sys
import json
import logging
from datetime import datetime
import tkinter as tk
from tkinter import filedialog
from threading import Thread
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Set up logging (prints to console and logs to file)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("file_monitor.log"),
        logging.StreamHandler()
    ]
)

# Figure out where the script is running from
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# Load config.json with error handling
try:
    with open(CONFIG_PATH, 'r') as f:
        CONFIG = json.load(f)
    logging.info(f"Using config file: {CONFIG_PATH}")
    logging.info(f"Config keys loaded: {list(CONFIG.keys())}")
except FileNotFoundError:
    logging.error(
        f"No config found at {CONFIG_PATH} — you need one to run this.")
    sys.exit(1)
except json.JSONDecodeError as e:
    logging.error(f"Couldn't parse config file: {e}")
    sys.exit(1)


def archive_file(dest_path, archive_dir):
    """
    Make a dated backup copy of the file in the archive folder.
    I keep it separate from move_file() so archiving logic can change without touching the move logic.
    """
    date_folder = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(archive_dir, date_folder)
    os.makedirs(archive_path, exist_ok=True)

    try:
        shutil.copy2(dest_path, archive_path)
        logging.info(f"Archived {dest_path} to {archive_path}")
    except Exception as e:
        logging.error(f"Error archiving file: {e}")


def get_unique_filename(dest_dir, filename):
    """
    If there's already a file with the same name, add a counter to the new one.
    """
    base_name, ext = os.path.splitext(filename)
    counter = 1
    dest_path = os.path.join(dest_dir, filename)
    while os.path.exists(dest_path):
        dest_path = os.path.join(dest_dir, f"{base_name} {counter}{ext}")
        counter += 1
    return dest_path


def move_file(src_path, base_dir, ext_map, sorted_dir_name, archive_dir_name):
    """
    Move a file to the appropriate folder based on its extension.
    """
    sorted_dir = os.path.join(base_dir, sorted_dir_name)
    archive_dir = os.path.join(base_dir, archive_dir_name)
    _, ext = os.path.splitext(src_path)
    ext = ext.lower()

    if ext in ext_map:
        dest_dir = os.path.join(sorted_dir, ext_map[ext])
    else:
        logging.warning(f"Unknown / unsupported file type: {src_path}")
        return

    try:
        filename = os.path.basename(src_path)
        # This extra variable isn't necessary, but leaving it here helps with debugging
        final_dest = get_unique_filename(dest_dir, filename)
        shutil.move(src_path, final_dest)
        logging.info(f"Moved {src_path} to {final_dest}")
        archive_file(final_dest, archive_dir)
    except Exception as e:
        logging.error(f"Error moving file: {e}")


class WatcherHandler(FileSystemEventHandler):
    """Handles file system events like new file creation."""

    def __init__(self, base_dir, ext_map, sorted_dir_name, archive_dir_name):
        self.base_dir = base_dir
        self.ext_map = ext_map
        self.sorted_dir_name = sorted_dir_name
        self.archive_dir_name = archive_dir_name

    def on_created(self, event):
        # Only care about files, not directories
        if not event.is_directory:
            logging.info(f"New file detected: {event.src_path}")
            move_file(event.src_path, self.base_dir, self.ext_map,
                      self.sorted_dir_name, self.archive_dir_name)


class FileSorterApp:
    def __init__(self, root):
        self.root = root
        self.observer = None
        self.base_dir = None

        self.config = CONFIG  # Loaded from the JSON above

        root.title("Live File Sorting Monitor")
        root.geometry("500x300")

        self.select_button = tk.Button(
            root, text="Select Base Directory", command=self.select_directory)
        self.select_button.pack(pady=10)

        self.dir_label = tk.Label(root, text="No directory selected")
        self.dir_label.pack(pady=10)

        self.start_button = tk.Button(
            root, text="Start Monitoring", command=self.start_monitoring, state=tk.DISABLED)
        self.start_button.pack(pady=10)

        self.stop_button = tk.Button(
            root, text="Stop Monitoring", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_button.pack(pady=10)

    def select_directory(self):
        """Pick the folder where the monitoring will happen."""
        chosen_dir = filedialog.askdirectory()
        if chosen_dir:
            self.base_dir = chosen_dir
            self.dir_label.config(text=self.base_dir)
            self.prepare_directories()
            self.start_button.config(state=tk.NORMAL)

    def prepare_directories(self):
        """Create the incoming, sorted, and archive folders if they don't exist."""
        incoming = os.path.join(
            self.base_dir, self.config["incoming_directory"])
        sorted_dir = os.path.join(
            self.base_dir, self.config["sorted_directory"])
        archive_dir = os.path.join(
            self.base_dir, self.config["archive_directory"])

        # These three lines could be looped, but I left them separate for readability
        os.makedirs(incoming, exist_ok=True)
        os.makedirs(sorted_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)

        for folder_name in set(self.config["extensions"].values()):
            os.makedirs(os.path.join(sorted_dir, folder_name), exist_ok=True)

    def start_monitoring(self):
        """Begin watching the incoming folder for new files."""
        if not self.base_dir:
            logging.warning(
                "No base directory selected. Cannot start monitoring.")
            return

        incoming = os.path.join(
            self.base_dir, self.config["incoming_directory"])
        event_handler = WatcherHandler(
            self.base_dir,
            self.config["extensions"],
            self.config["sorted_directory"],
            self.config["archive_directory"]
        )

        self.observer = Observer()
        self.observer.schedule(event_handler, path=incoming, recursive=False)
        self.observer.start()

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        Thread(target=self.run_observer, daemon=True).start()

    def run_observer(self):
        """Keep the observer running."""
        try:
            while self.observer and self.observer.is_alive():
                time.sleep(1)
        except Exception as e:
            logging.error(f"Observer error: {e}")

    def stop_monitoring(self):
        """Stop watching the incoming folder."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)


if __name__ == "__main__":
    root = tk.Tk()
    app = FileSorterApp(root)
    root.mainloop()

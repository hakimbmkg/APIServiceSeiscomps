import os
import time
import threading
import logging
import re
from typing import List, Dict, Tuple

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from obspy.clients.fdsn import Client
from obspy import UTCDateTime

# Logging setup
logger = logging.getLogger("waveform_watcher")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# --- Function to parse event_detail.txt (improved, removes +/- and extra) ---
def parse_seiscomp_log(log_text: str):
    lines = log_text.strip().splitlines()
    event_data = {
        "event": {},
        "origin": {},
        "network_magnitudes": [],
        "phase_arrivals": [],
        "station_magnitudes": []
    }

    phase_section = False
    station_mag_section = False

    for i, line in enumerate(lines):
        line = line.strip()

        if line.startswith("Public ID") and "Preferred Origin ID" not in lines[i+1]:
            event_data["event"]["public_id"] = line.split()[-1]
        elif "Preferred Origin ID" in line:
            event_data["event"]["preferred_origin_id"] = line.split()[-1]
        elif "Preferred Magnitude ID" in line:
            event_data["event"]["preferred_magnitude_id"] = line.split()[-1]
        elif "region name:" in line:
            event_data["event"]["region"] = line.split("region name:")[-1].strip()
        elif "Creation time" in line and "event" in lines[i-1].lower():
            event_data["event"]["creation_time"] = line.split()[-1]

        elif line.startswith("Public ID"):
            event_data["origin"]["public_id"] = line.split()[-1]
        elif line.startswith("Date"):
            event_data["origin"]["date"] = line.split()[1]
        elif line.startswith("Time"):
            time_cleaned = line.split()[1]  # only time string, discard +/-
            event_data["origin"]["time"] = time_cleaned
        elif line.startswith("Latitude"):
            event_data["origin"]["latitude"] = float(line.split()[1])
        elif line.startswith("Longitude"):
            event_data["origin"]["longitude"] = float(line.split()[1])
        elif line.startswith("Depth"):
            event_data["origin"]["depth_km"] = float(line.split()[1])

        elif "Phase arrivals:" in line:
            phase_section = True
            continue
        elif phase_section and line.strip():
            parts = line.split()
            if parts[0].lower() == "sta" or not parts[2].replace('.', '', 1).isdigit():
                continue
            if len(parts) >= 9:
                arrival = {
                    "station": parts[0],
                    "network": parts[1],
                    "distance_deg": float(parts[2]),
                    "azimuth": float(parts[3]),
                    "phase": parts[4],
                    "time": parts[5],
                    "residual": float(parts[6]),
                    "weight": float(parts[8])
                }
                event_data["phase_arrivals"].append(arrival)
        elif phase_section and not line.strip():
            phase_section = False

    return event_data

# --- Folder creation ---
def create_event_directory(base_dir: str, public_id: str) -> str:
    safe_id = public_id.replace("/", "_")
    path = os.path.join(base_dir, safe_id)
    os.makedirs(path, exist_ok=True)
    return path

# --- Improved channel + location finder ---
def get_available_channels_with_locations(client: Client, network: str, station: str, time: UTCDateTime, priorities=("BHZ", "SHZ", "EHZ")) -> List[Tuple[str, str]]:
    results = []
    try:
        inventory = client.get_stations(
            network=network,
            station=station,
            level="channel",
            starttime=time,
            endtime=time + 1
        )
        for net in inventory:
            for sta in net:
                for ch in sta.channels:
                    code = ch.code
                    loc = ch.location_code or ""
                    if any(code.startswith(p) for p in priorities):
                        results.append((code, loc))
    except Exception as e:
        logger.warning(f"[WARN] Gagal get inventory {network}.{station}: {e}")
    return results

# --- Waveform download ---
def download_waveforms(phase_arrivals: List[Dict], origin_time: str, event_dir: str, client_name="LOC"):
    client = Client(client_name, user="admin", password="admin")
    origin_utc = UTCDateTime(origin_time)

    for arrival in phase_arrivals:
        try:
            network = arrival['network']
            station = arrival['station']
            starttime = origin_utc - 30
            endtime = origin_utc + 600

            channel_locs = get_available_channels_with_locations(client, network, station, origin_utc)
            downloaded = False

            for ch_code, loc in channel_locs:
                try:
                    st = client.get_waveforms(
                        network=network,
                        station=station,
                        location=loc,
                        channel=ch_code,
                        starttime=starttime,
                        endtime=endtime
                    )
                    fname = os.path.join(event_dir, f"{network}.{station}.mseed")
                    st.write(fname, format="MSEED")
                    logger.info(f"[OK] Saved {fname}")
                    downloaded = True
                    break
                except Exception as e:
                    logger.warning(f"[FAIL] {network}.{station} {loc}.{ch_code}: {e}")

            if not downloaded:
                logger.warning(f"[SKIP] Tidak ada channel valid untuk {network}.{station}")
        except Exception as e:
            logger.warning(f"[ERR] Failed {network}.{station}: {e}")

# --- Watchdog Handler ---
class EventFileHandler(FileSystemEventHandler):
    def __init__(self, file_path: str, base_dir: str = "./events", client_name="LOC"):
        self.file_path = os.path.abspath(file_path)
        self.base_dir = base_dir
        self.client_name = client_name

    def on_modified(self, event):
        if not event.is_directory and os.path.abspath(event.src_path) == self.file_path:
            logger.info(f"[WATCHDOG] File changed: {event.src_path}")
            try:
                with open(self.file_path, "r") as f:
                    content = f.read()
                parsed = parse_seiscomp_log(content)
                origin = parsed.get("origin", {})
                public_id = origin.get("public_id", "unknown_event")
                date = origin.get("date")
                time_str = origin.get("time")
                if not date or not time_str:
                    logger.warning("[WAVEFORM] 'date' or 'time' missing in origin section")
                    return

                origin_time = f"{date}T{time_str}"
                arrivals = parsed.get("phase_arrivals", [])
                event_dir = create_event_directory(self.base_dir, public_id)
                download_waveforms(arrivals, origin_time, event_dir, self.client_name)
            except Exception as e:
                logger.warning(f"[WAVEFORM] Failed processing {self.file_path}: {e}")

# --- Start Watcher ---
def start_watcher(file_path: str, base_dir="./events", client_name="LOC"):
    abs_path = os.path.abspath(file_path)
    dir_path = os.path.dirname(abs_path)

    event_handler = EventFileHandler(abs_path, base_dir, client_name)
    observer = Observer()
    observer.schedule(event_handler, path=dir_path, recursive=False)
    observer.start()
    logger.info(f"[STARTED] Watching {abs_path}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("[STOPPED] Watcher stopped")
    observer.join()

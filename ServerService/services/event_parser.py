import json
import re
from datetime import datetime

# --- Fungsi: Parse event summary file (| delimited) ---
def parse_event_file(filepath: str) -> dict:
    try:
        with open(filepath, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
        if not lines or not lines[0].startswith("#"):
            return {}
        keys = lines[0].lstrip("#").split("|")
        values = lines[1].split("|") if len(lines) > 1 else []
        event = {}
        for key, value in zip(keys, values):
            event[key.strip()] = value.strip()
        return event
    except FileNotFoundError:
        print(f"[ERROR] File not found: {filepath}")
        return {}
    except Exception as e:
        print(f"[ERROR] Error parsing {filepath}: {e}")
        return {}

# --- Fungsi: Parse event detail (300 format) ---
def parse_event_300(file_path: str):
    try:
        with open(file_path, "r") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        header_line = next((line for line in lines if line.startswith("#")), None)
        if not header_line:
            raise ValueError("Header not found in file.")
        headers = [h.strip() for h in header_line.lstrip("#").split("|")]
        data_lines = [line for line in lines if not line.startswith("#")]
        result = []
        for line in data_lines:
            values = [v.strip() for v in line.split("|")]
            if len(values) != len(headers):
                print(f"[WARNING] Invalid row in {file_path}: {line}")
                continue
            result.append(dict(zip(headers, values)))
        return result
    except FileNotFoundError:
        print(f"[ERROR] File not found: {file_path}")
        return []
    except Exception as e:
        print(f"[ERROR] Parsing failed for {file_path}: {e}")
        raise

# --- Fungsi: Parse log bulletin SeisComP dinamis ke JSON ---
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
            event_data["origin"]["date"] = line.split()[-1]
        elif line.startswith("Time"):
            event_data["origin"]["time"] = line.split()[1]
            event_data["origin"]["time_error"] = "±" + line.split()[-2] + line.split()[-1]
        elif line.startswith("Latitude"):
            event_data["origin"]["latitude"] = float(line.split()[1])
            event_data["origin"]["latitude_error_km"] = float(line.split()[-2])
        elif line.startswith("Longitude"):
            event_data["origin"]["longitude"] = float(line.split()[1])
            event_data["origin"]["longitude_error_km"] = float(line.split()[-2])
        elif line.startswith("Depth"):
            event_data["origin"]["depth_km"] = float(line.split()[1])
            event_data["origin"]["depth_fixed"] = "fixed" in line
        elif line.startswith("Agency"):
            event_data["origin"]["agency"] = line.split()[-1]
        elif line.startswith("Author"):
            event_data["origin"]["author"] = line.split()[-1]
        elif line.startswith("Mode"):
            event_data["origin"]["mode"] = line.split()[-1]
        elif line.startswith("Status"):
            event_data["origin"]["status"] = line.split()[-1]
        elif "Residual RMS" in line:
            event_data["origin"]["residual_rms"] = float(line.split()[-2])
        elif "Azimuthal gap" in line:
            event_data["origin"]["azimuthal_gap"] = float(line.split()[-2])

        elif "Network magnitudes:" in line:
            j = i + 1
            while j < len(lines) and lines[j].strip():
                parts = lines[j].split()
                if len(parts) >= 5:
                    mag = {
                        "type": parts[0],
                        "value": float(parts[1]),
                        "error": float(parts[3]) if parts[2] == "+/-" else None,
                        "station_count": int(parts[4]),
                        "agency": parts[-1]
                    }
                    event_data["network_magnitudes"].append(mag)
                j += 1

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

        elif "Station magnitudes:" in line:
            station_mag_section = True
            continue
        elif station_mag_section and line.strip():
            parts = line.split()
            if parts[0].lower() == "sta" or not parts[2].replace('.', '', 1).isdigit():
                continue
            if len(parts) >= 9:
                mag = {
                    "station": parts[0],
                    "network": parts[1],
                    "distance_deg": float(parts[2]),
                    "azimuth": float(parts[3]),
                    "type": parts[4],
                    "value": float(parts[5]),
                    "residual": float(parts[6]),
                    "amplitude": float(parts[7]) if parts[7] != '' else None
                }
                event_data["station_magnitudes"].append(mag)
        elif station_mag_section and not line.strip():
            station_mag_section = False

    return event_data



from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from event_parser import parse_event_file, parse_event_300, parse_seiscomp_log
from waveform_watcher import start_watcher
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from matplotlib import pyplot as plt
from obspy import read
import os
import threading
import asyncio
import logging
from typing import List
from lxml import etree
from influxdb_client import InfluxDBClient
from datetime import datetime as dt, timedelta
import io



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
event_file = os.path.join(BASE_DIR, "event_parameter.txt")
event_300 = os.path.join(BASE_DIR, "event_300.txt")
event_detail_file = os.path.join(BASE_DIR, "event_detail.txt")
# stations_smart = os.path.join(BASE_DIR, "stations.xml") 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[INFO] Client connected: {len(self.active_connections)} total")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"[INFO] Client disconnected: {len(self.active_connections)} remaining")

    async def broadcast(self, message: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception as e:
                logger.warning(f"[WS] Failed to send: {e}")
                disconnected.append(conn)
        for d in disconnected:
            self.disconnect(d)

manager = ConnectionManager()

@app.get("/last_event")
async def get_last_event_data():
    try:
        data = parse_event_file(event_file)
        return JSONResponse(content=data)
    except Exception as e:
        logger.error(f"[API] Error reading last_event: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/last_300")
async def get_300_event_data():
    try:
        datas = parse_event_300(event_300)
        return JSONResponse(content=datas)
    except Exception as e:
        logger.error(f"[API] Error reading last_300: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/event_detail")
async def get_event_detail_data():
    try:
        with open(event_detail_file, "r") as f:
            content = f.read()
        datas = parse_seiscomp_log(content)
        return JSONResponse(content=datas)
    except FileNotFoundError:
        logger.error(f"[API] Event detail file not found: {event_detail_file}")
        return JSONResponse(status_code=404, content={"error": f"File not found: {event_detail_file}"})
    except Exception as e:
        logger.error(f"[API] Error reading event_detail: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/waveform_data/{public_id}/{filename}")
def get_waveform_data(public_id: str, filename: str):
    path = os.path.join(BASE_DIR, "events", public_id.replace("/", "_"), filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})

    try:
        st = read(path)
        traces = []
        for tr in st:
            times = tr.times().tolist()
            data = tr.data.tolist()
            start_seconds = tr.stats.starttime.timestamp % 86400
            traces.append({
                "station": tr.stats.station,
                "channel": tr.stats.channel,
                "network": tr.stats.network,
                "times": times,
                "amplitudes": data,
                "start_seconds": start_seconds
            })
        return JSONResponse(content={"traces": traces})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/station_coords")
def get_station_coords():
    try:
        xml_path = os.path.join(BASE_DIR, "stations.xml")  # Ubah sesuai lokasi file
        with open(xml_path, "rb") as f:
            tree = etree.parse(f)

        ns = {"ns": "http://www.fdsn.org/xml/station/1"}
        root = tree.getroot()
        stations = {}

        for net in root.findall(".//ns:Network", namespaces=ns):
            network_code = net.get("code")
            for sta in net.findall("ns:Station", namespaces=ns):
                station_code = sta.get("code")
                latitude = float(sta.find("ns:Latitude", namespaces=ns).text)
                longitude = float(sta.find("ns:Longitude", namespaces=ns).text)
                key = f"{network_code}.{station_code}"
                stations[key] = {"lat": latitude, "lon": longitude}

        return JSONResponse(content=stations)

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "XXXTOKEN"
INFLUX_ORG = "XXXORG"
INFLUX_BUCKET = "seedlinksmart"

client = InfluxDBClient(
    url=INFLUX_URL,
    token=INFLUX_TOKEN,
    org=INFLUX_ORG
)

@app.get("/waveform_image")
def waveform_image(
    net: str,
    sta: str,
    cha: str = "SHZ",
    seconds: int = 360,
    width: float = 10,
    height: float = 2
):
    from fastapi.responses import Response
    from matplotlib import pyplot as plt
    import matplotlib.dates as mdates

    query_api = client.query_api()
    now = dt.utcnow()
    start = now - timedelta(seconds=seconds)

    flux = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {start.isoformat()}Z, stop: {now.isoformat()}Z)
      |> filter(fn: (r) => r["_measurement"] == "waveform")
      |> filter(fn: (r) => r["network"] == "{net}")
      |> filter(fn: (r) => r["station"] == "{sta}")
      |> filter(fn: (r) => r["channel"] == "{cha}")
      |> sort(columns: ["_time"])
    '''

    result = query_api.query(flux)

    times, values = [], []
    for table in result:
        for row in table.records:
            times.append(row.get_time())
            values.append(row.get_value())

    plt.figure(figsize=(width, height))

    if not values:
        plt.text(0.5, 0.5, f"{net}.{sta}.{cha}\nNo Data", ha='center', va='center', fontsize=12)
        plt.axis('off')
    else:
        plt.plot(times, values, linewidth=0.8, color='black')
        plt.title(f"{net}.{sta}.{cha}", fontsize=10)
        plt.xlabel("Time (UTC)")
        plt.ylabel("Amplitude")
        plt.grid(True, linestyle='--', alpha=0.4)
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


from fastapi import Query

@app.get("/waveform_image_multi")
def waveform_image_multi(
    net: str,
    sta: str,
    channels: List[str] = Query(["SHZ", "SHN", "SHE"]),
    seconds: int = 30
):
    from fastapi.responses import Response
    from matplotlib import pyplot as plt
    import matplotlib.dates as mdates

    query_api = client.query_api()
    now = dt.utcnow()
    start = now - timedelta(seconds=seconds)

    fig, axs = plt.subplots(len(channels), 1, figsize=(6, 2.5 * len(channels)), sharex=True)

    # handle jika hanya satu channel
    if len(channels) == 1:
        axs = [axs]

    for i, cha in enumerate(channels):
        flux = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: {start.isoformat()}Z, stop: {now.isoformat()}Z)
          |> filter(fn: (r) => r["_measurement"] == "waveform")
          |> filter(fn: (r) => r["network"] == "{net}")
          |> filter(fn: (r) => r["station"] == "{sta}")
          |> filter(fn: (r) => r["channel"] == "{cha}")
          |> sort(columns: ["_time"])
        '''

        result = query_api.query(flux)
        times, values = [], []

        for table in result:
            for row in table.records:
                times.append(row.get_time())
                values.append(row.get_value())

        ax = axs[i]
        if values:
            ax.plot(times, values, color='black', linewidth=0.8)
            ax.set_title(f"{net}.{sta}.{cha}", fontsize=10)
            ax.set_ylabel("Amplitude", fontsize=9)
            ax.grid(True, linestyle='--', alpha=0.4)
            # Format waktu lebih rapi
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        else:
            ax.text(0.5, 0.5, f"{net}.{sta}.{cha}\nNo Data", ha='center', va='center')
            ax.axis('off')

    axs[-1].set_xlabel("Time (UTC)", fontsize=9)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")

@app.get("/realtime_waveform")
async def get_all_stream_data():
    try:
        query = (
            f'from(bucket: "seedlinksmart") '
            f'|> range(start: -30s) '
            f'|> filter(fn: (r) => r._measurement == "waveform") '
            f'|> filter(fn: (r) => r["_field"] == "value") '
            f'|> group(columns: ["network", "station", "channel"]) '
            f'|> sort(columns: ["_time"]) '
        )
        result = client.query_api().query(org="smart_psi", query=query)

        output = []

        for table in result:
            records = table.records
            if not records:
                continue

            values = []
            times = []
            meta = records[0].values
            for r in records:
                times.append(r.get_time().isoformat())
                values.append(r.get_value())

            output.append({
                "network": meta["network"],
                "station": meta["station"],
                "channel": meta["channel"],
                "times": times,
                "values": values
            })

        return output
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})



@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"[WS] WebSocket error: {e}")
        manager.disconnect(websocket)

@app.post("/broadcast")
async def broadcast_last_event():
    try:
        data = parse_event_file(event_file)
        await manager.broadcast(data)
        return {"status": "ok", "message": "Notifikasi dikirim ke semua klien"}
    except Exception as e:
        logger.error(f"[BROADCAST] Error broadcasting event: {e}")
        return {"status": "error", "detail": str(e)}

class EventFileHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, event_path: str, callback):
        self.loop = loop
        self.event_path = os.path.abspath(event_path)
        self.callback = callback
        logger.info(f"[WATCHDOG] Initializing handler for: {self.event_path}")

    def on_modified(self, event):
        if not event.is_directory and os.path.abspath(event.src_path) == self.event_path:
            logger.info(f"[WATCHDOG] File changed: {event.src_path}")
            asyncio.run_coroutine_threadsafe(self.callback(), self.loop)

def start_file_watcher(loop, file_path, callback):
    dir_path = os.path.dirname(file_path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
        logger.info(f"[WATCHDOG] Created directory: {dir_path}")

    if not os.path.exists(file_path):
        try:
            open(file_path, 'w').close()
            logger.warning(f"[WATCHDOG] File {file_path} not found. Created empty.")
        except IOError as e:
            logger.error(f"[WATCHDOG] Could not create file {file_path}: {e}")
            return

    event_handler = EventFileHandler(loop, file_path, callback)
    observer = Observer()
    watch_path = os.path.dirname(file_path) or "."
    observer.schedule(event_handler, watch_path, recursive=False)
    observer.start()
    logger.info(f"[WATCHDOG] Watching {file_path} in directory {watch_path}")

@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_running_loop()

    threading.Thread(
        target=start_file_watcher,
        args=(loop, event_file, broadcast_last_event),
        daemon=True
    ).start()

    threading.Thread(
        target=start_watcher,
        args=(event_detail_file, "./events", "LOC"),
        daemon=True
    ).start()

    logger.info("[STARTUP] FastAPI app started and watcher thread running.")

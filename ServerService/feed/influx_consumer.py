from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from obspy import Stream
import logging
import queue
from datetime import timedelta
from threads import q, shutdown_event
import numpy as np

logger = logging.getLogger("influx_consumer")

class InfluxDBConsumer:
    def __init__(self, url, token, org, bucket, measurement, net_filter, dryrun=False):
        self.client = InfluxDBClient(url=url, token=token, org=org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = bucket
        self.measurement = measurement
        self.net_filter = net_filter
        self.dryrun = dryrun
        self.force_shutdown = None

    def run(self):
        logger.info("[InfluxConsumer] Running...")
        while not shutdown_event.is_set():
            try:
                trace = q.get(timeout=5)
                self.process_trace(trace)
            except queue.Empty:
                logger.debug("Rx: timeout: no data in queue")
            except Exception as e:
                logger.error(f"Consumer error: {e}", exc_info=True)
                if self.force_shutdown:
                    self.force_shutdown(e)
        self.close()

    def process_trace(self, trace):
        net = trace.stats.network
        sta = trace.stats.station
        loc = trace.stats.location
        cha = trace.stats.channel
        starttime = trace.stats.starttime.datetime
        delta = trace.stats.delta

        if self.net_filter and net not in self.net_filter:
            return
        
        print(f"[DEBUG] {sta}: type(trace.data[0]) =", type(trace.data[0]))

        points = []
        for i, val in enumerate(trace.data):
            # Skip NaN or inf
            if not np.isfinite(val):
                continue

            timestamp = starttime + timedelta(seconds=i * delta)
            # safe_val = float(val.item() if hasattr(val, "item") else val)

            point = Point(self.measurement) \
                .tag("network", net) \
                .tag("station", sta) \
                .tag("location", loc) \
                .tag("channel", cha) \
                .field("value", float(val)) \
                .time(timestamp, WritePrecision.NS)

            points.append(point)

        if not points:
            logger.warning(f"No valid data to write for: {net}.{sta}.{loc}.{cha}")
            return

        try:
            self.write_api.write(bucket=self.bucket, record=points)
            logger.info(f"Wrote {len(points)} samples: {net}.{sta}.{loc}.{cha}")
        except Exception as e:
            logger.error(f"[{sta}] Write error: {e}")
            if self.force_shutdown:
                self.force_shutdown(e)


    def close(self):
        logger.info("Closing InfluxDB client...")
        try:
            self.write_api.flush()
            self.client.close()
        except Exception as e:
            logger.error(f"Error during client shutdown: {e}")

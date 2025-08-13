import logging
from threads import ProducerThread, ConsumerThread
from myseedlink import MySeedlinkClient
from influx_consumer import InfluxDBConsumer
import os


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("app.log", mode='w'),
        logging.StreamHandler()
    ]
)

logging.getLogger("obspy.seedlink").setLevel(logging.DEBUG)
logging.getLogger("threads").setLevel(logging.DEBUG)
logging.getLogger("influx_consumer").setLevel(logging.DEBUG)

if __name__ == "__main__":
    # CONFIG
    SEEDLINK_SERVER = os.getenv("SEEDLINK_SERVER", "localhost:18000")
    STREAM_PATTERNS = [["AM", ".*", "SHZ", ".*"]]  # semua stream
    STATEFILE = "statefile.sl"
    RECOVER = True

    INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
    # INFLUXDB_TOKEN = "TOKEN"
    INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "XXX_TOKEN")
    INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "XXX_ORG")
    INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "seedlinksmart")
    INFLUXDB_MEASUREMENT = "waveform"
    NETWORK_FILTER = ["AM"]  # None untuk semua

    # SEEDLINK
    producer = ProducerThread(
        name="SeedLinkProducer",
        slclient=MySeedlinkClient,
        args=(SEEDLINK_SERVER, STREAM_PATTERNS, STATEFILE, RECOVER)
    )

    # CONSUME
    consumer = ConsumerThread(
        name="InfluxConsumer",
        dbclient=InfluxDBConsumer,
        args=(INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG,
              INFLUXDB_BUCKET, INFLUXDB_MEASUREMENT,
              NETWORK_FILTER, False)
    )

    producer.start()
    consumer.start()

    producer.join()
    consumer.join()

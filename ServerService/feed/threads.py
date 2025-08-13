import logging
from queue import Queue
import sys
import threading
from obspy.clients.seedlink.seedlinkexception import SeedLinkException

# Logger default
logger = logging.getLogger('threads')

# Variabel global bersama antar-thread
BUF_SIZE = 1000000
q = Queue(BUF_SIZE)
shutdown_event = threading.Event()
last_packet_time = {}
lock = threading.Lock()


class ProducerThread(threading.Thread):
    def __init__(self, name=None, slclient=None, args=(), kwargs=None):
        super().__init__(name=name)
        if slclient is None:
            raise ValueError("slclient (SeedLink client) must be provided.")

        self.name = name
        kwargs = kwargs or {}

        try:
            self.slclient = slclient(*args, **kwargs)
        except SeedLinkException as e:
            self.force_shutdown(f"SeedLink init error: {e}")

    def run(self):
        logger.info(f"[{self.name}] Starting SeedLink producer thread.")
        try:
            self.slclient.run()
        except SeedLinkException as e:
            self.force_shutdown(f"SeedLink runtime error: {e}")
        except Exception as e:
            self.force_shutdown(f"Unexpected error: {e}")

    def force_shutdown(self, msg):
        logger.error(msg)
        logger.error(f"[{self.name}] Thread has called force_shutdown()")
        shutdown_event.set()
        sys.exit(1)


class ConsumerThread(threading.Thread):
    def __init__(self, name=None, dbclient=None, args=(), kwargs=None):
        super().__init__(name=name)
        if dbclient is None:
            raise ValueError("dbclient must be provided.")

        self.name = name
        kwargs = kwargs or {}

        try:
            self.dbclient = dbclient(*args, **kwargs)
        except Exception as e:
            self.force_shutdown(f"DB client init error: {e}")

        # Inject force_shutdown method ke dalam dbclient
        self.dbclient.force_shutdown = self.force_shutdown

    def run(self):
        logger.info(f"[{self.name}] Starting consumer thread.")
        try:
            self.dbclient.run()
        except Exception as e:
            self.force_shutdown(f"Consumer runtime error: {e}")

    def force_shutdown(self, msg):
        logger.error(msg)
        logger.error(f"[{self.name}] Thread has called force_shutdown()")
        shutdown_event.set()
        sys.exit(1)

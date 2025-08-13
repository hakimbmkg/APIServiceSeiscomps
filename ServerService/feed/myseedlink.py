#!/usr/bin/env python3

import sys
import re
import queue
import logging
from datetime import datetime
from io import StringIO

from obspy import UTCDateTime
from obspy.clients.seedlink import EasySeedLinkClient
from obspy.clients.seedlink.seedlinkexception import SeedLinkException
from lxml import etree

from threads import q, shutdown_event

logger = logging.getLogger('obspy.seedlink')


class MySeedlinkClient(EasySeedLinkClient):
    def __init__(self, server, streams, statefile, recover):
        super().__init__(server)
        self.selected_streams = []
        self.statefile = statefile
        self.recover = recover
        self.queue_timeout = 15  # seconds
        self.SL_PACKET_TIME_MAX = 60. * 30.  # 30 minutes
        self.resample_rate = 10.  # Hz
        self.show_too_old_packet_msg = {}

        # Ambil stream dari server dan seleksi
        for patterns in streams:
            if not self.select_stream_re(patterns):
                logger.critical(f"[SeedLink] Invalid stream pattern: {patterns}")

        # Recovery state lama jika diperlukan
        if self.recover:
            self.conn.statefile = statefile
            try:
                self.conn.recover_state(statefile)
            except SeedLinkException as e:
                logger.error(e)
            self.conn.statefile = None

    def get_stream_info(self):
        """Parse stream info XML dari server."""
        try:
            stream_xml = self.get_info('STREAMS')
        except Exception as e:
            logger.error(f"Failed to get stream info: {e}")
            return []

        stream_xml = stream_xml.replace('encoding="utf-8"', '')
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(StringIO(stream_xml), parser)
        root = tree.getroot()
        stream_info = []

        for s in root.iterchildren():
            if s.tag == "station":
                s_dic = dict(zip(s.keys(), s.values()))
                s_dic['channel'] = []
                stream_info.append(s_dic)
                for c in s.iterchildren():
                    if c.tag == "stream":
                        c_dic = dict(zip(c.keys(), c.values()))
                        s_dic['channel'].append(c_dic)

        return stream_info

    def select_stream_re(self, pattern):
        """Pilih stream berdasarkan regex [net, sta, cha, loc]."""
        try:
            net_re = re.compile(pattern[0])
            sta_re = re.compile(pattern[1])
            cha_re = re.compile(pattern[2])
            loc_re = re.compile(pattern[3])
        except Exception as e:
            logger.error(f"Regex error: {e}")
            return False

        stream_info = self.get_stream_info()
        for s in stream_info:
            if not net_re.match(s['network']) or not sta_re.match(s['name']):
                continue
            for c in s['channel']:
                if cha_re.match(c['seedname']) and loc_re.match(c['location']):
                    self.add_stream(s['network'], s['name'], c['seedname'], c['location'])
        return True

    def add_stream(self, net, sta, cha, loc):
        """Tambahkan stream ke daftar untuk diproses."""
        self.select_stream(net, sta, cha)
        stream = ".".join([net, sta, loc or "", cha])
        self.selected_streams.append(stream)
        # logger.info(f"[SeedLink] stream added: {stream}")

    def on_data(self, trace):
        """Callback saat data diterima dari SeedLink."""
        channel = ".".join([
            trace.stats.network,
            trace.stats.station,
            trace.stats.location or "",
            trace.stats.channel
        ])

        if channel not in self.selected_streams:
            logger.warning(f"[on_data] Skipping unselected stream: {channel}")
            return

        now = datetime.utcnow()
        latency = UTCDateTime(now) - trace.stats.endtime

        if self.SL_PACKET_TIME_MAX and latency > self.SL_PACKET_TIME_MAX:
            if self.show_too_old_packet_msg.get(channel, True):
                logger.info(f"[{channel}] Latency too high: {latency:.1f}s — ignoring")
                self.show_too_old_packet_msg[channel] = False
            return
        else:
            if self.show_too_old_packet_msg.get(channel, False) is False:
                logger.info(f"[{channel}] Latency OK again: {latency:.1f}s")
                self.show_too_old_packet_msg[channel] = True

        # Resampling
        if self.resample_rate:
            try:
                trace.resample(self.resample_rate)
            except Exception as e:
                logger.warning(f"Can't resample {channel}: {e}")

        # Masukkan ke antrian
        try:
            q.put(trace, block=True, timeout=self.queue_timeout)
            logger.debug(f"[on_data] Trace put to queue: {channel}")
        except queue.Full:
            logger.error("Queue is full, dropping data!")

        if shutdown_event.is_set():
            logger.info(f"{self.__class__.__name__} caught shutdown_event")
            self.stop_seedlink()

    def on_seedlink_error(self):
        logger.error(f"[{datetime.utcnow()}] Seedlink error")

    def stop_seedlink(self):
        self.conn.statefile = self.statefile
        try:
            self.conn.save_state(self.statefile)
        except SeedLinkException as e:
            logger.error(e)
        self.conn.close()
        sys.exit(0)

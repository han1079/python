import usb
import re
import os
import subprocess
import signal
import pathlib
import logging
import pyvisa
from lazybench.database.db_inspector import SQLWriter, InstrumentConfigBase, RunHistoryBase
from lazybench.database import instrument_db
from lazybench.util import find_root
import asyncio
import threading


_CONFIG_PATH = find_root() / 'config/known_instruments.db'
_HISTORY_PATH = find_root() / 'config/run_history.db'

logger = logging.getLogger(__name__)

class KnownInstrumentDBWriter(SQLWriter):
    def __init__(self):
        super().__init__(_CONFIG_PATH)
        self.add_schema('known_instruments', InstrumentConfigBase)

    @property
    def table(self):
        return self.schema('known_instruments').table('instrument_config')


class RunHistoryDBWriter(SQLWriter):
    def __init__(self):
        super().__init__(_HISTORY_PATH)
        with self:
            self.add_schema('run_history', RunHistoryBase)

    @property
    def table(self):
        return self.schema('run_history')

    

def _describe_usb_device(dev):
    """Extract {vendor_id, product_id, serial} from one USB device, or None
    if it has no serial descriptor. """
    try:
        if not dev.iSerialNumber:
            return None
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber)
        except usb.core.USBError:
            serial = None
        return {'vendor_id': dev.idVendor, 'product_id': dev.idProduct, 'serial': serial}
    finally:
        """Always releases the device handle. If not, GC may not happen before the next
        call and `libusb_ref_device: Assertion 'refcnt >= 2' failed` sees two usb handles
        and treats that as a memory violation.
        """
        usb.util.dispose_resources(dev)


def _run_with_timeout(cmd, timeout):
    """Run cmd, killing its whole process group (not just the leader) on
    timeout instead of leaving an orphan behind. Returns (stdout, returncode),
    or None if it had to be killed."""
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout)
        return stdout, process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.communicate()
        return None


class HardwareScanner:
    def __init__(self):
        self.records = []
        self.config_rw = KnownInstrumentDBWriter()
        self.history_rw = RunHistoryDBWriter()
        self._loop = asyncio.new_event_loop()
        self._loop_running = threading.Event()

    def scan_usb(self):
        records = (_describe_usb_device(dev) for dev in usb.core.find(find_all=True))
        return [r for r in records if r is not None]

    def usb_serial_present(self, serial, vendor_id, product_id):
        devices = usb.core.find(find_all=True, idVendor=vendor_id, idProduct=product_id)
        records = (_describe_usb_device(dev) for dev in devices)
        return any(r is not None and r['serial'] == serial for r in records)

    def scan_ip(self, ip_addr):
        ip_regex = r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        cmd = f'nmap -sn {ip_addr}/24 --max-retries 2 --scan-delay 0 --min-rtt-timeout 5ms --max-rtt-timeout 10ms'

        hostname_result = _run_with_timeout(['hostname', '-I'], timeout=2.0)
        if hostname_result is None:
            return None
        host_ips = hostname_result[0].strip('\n').strip().split(' ')

        scan_result = _run_with_timeout(cmd.split(' '), timeout=2.0)
        if scan_result is None:
            return None
        found_ips = re.findall(ip_regex, scan_result[0])
        return [ip for ip in found_ips if ip not in host_ips]

    def ping_single_ip(self, ip_addr, timeout=1.0):
        result = _run_with_timeout(['ping', '-c', '1', '-W', '1', ip_addr], timeout=timeout)
        return result is not None and result[1] == 0

    def query(self, addr, query_str):
        rm = pyvisa.ResourceManager()
        try:
            visa_resource = rm.open_resource(addr)
        except Exception as e:
            logger.debug(e)
            return False

        tm = visa_resource.timeout
        visa_resource.timeout = 100
        try:
            result = visa_resource.query(query_str)
        except pyvisa.VisaIOError:
            visa_resource.timeout = tm
            visa_resource.close_resource(addr)
            return False

        visa_resource.timeout = tm
        visa_resource.close_resource(addr)
        return result
        


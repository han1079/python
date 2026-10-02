import pyvisa
import yaml
import logging

logger = logging.getLogger(__name__)


def _get_next_ip_block():
    if not hasattr(_get_next_ip_block, 'idx'):
        _get_next_ip_block.idx = 0

    _idx = _get_next_ip_block.idx
    _ip_blocks = [1,16,17,18,19,20,21,22]

    if _idx < len(_ip_blocks):
        _get_next_ip_block.idx += 1
        return f"192.168.{_ip_blocks[_idx]}.0"
    else:
        _get_next_ip_block.idx = 0
        return f"10.65.8.0"

def _get_idn(visa_address):
    """Given a visa address, open up a pyvisa resource and check IDN / responsiveness"""
    rm = pyvisa.ResourceManager()
    try:
        with rm.open_resource(visa_address) as res:
            try:
                res.read_termination = '\n'
                res.write_termination = '\n'
                for i in range(5):
                    res.write(':SYST:ERR?')
                    result = res.read_raw()
                    if '0' in str(result):
                        break
                res.write('*IDN?')
                idn = res.read_raw()
                return idn
            except Exception as ex:
                logger.debug(f"Attempted {visa_address}. Device opened, but got {ex} during query")
                return False

            try:
                res.read_termination = '\r\n'
                res.write_termination = '\r\n'
                for i in range(5):
                    res.write(':SYST:ERR?')
                    result = res.read_raw()
                    if '0' in str(result):
                        break
                res.write('*IDN?')
                idn = res.read_raw()
                return idn
            except Exception as ex:
                logger.debug(f"Attempted {visa_address}. Device opened, but got {ex} during query")
                return False
    except Exception as e:
        logger.debug(f"Attempted {visa_address}. Got Exception: {e}")
        return False


## ========================= Known-instrument index / matching ====================================

def hex_str_to_int(value):
    """Idempotent string-hex - to - int conversion"""
    return int(value, 16) if isinstance(value, str) else value


def build_known_instrument_lut(known_instrument_db):
    """(vendor_id, product_id) -> [(model_id, [idn_match values]), ...]"""
    index = {}
    with known_instrument_db as db:
        table = db.table
        for model_id in table.primary_keys():
            row = table.row(model_id)
            key = (hex_str_to_int(row.vendor_id), hex_str_to_int(row.product_id))
            index.setdefault(key, []).append((row.model_id, list(row.idn_match)))
    return index


def match_model_by_vidpid_and_idn(vendor_id, product_id, idn_readback, known_inst_lut):
    """VID and PID do not necessarily specify model. Disambiguate using the
    model's *IDN? response"""
    for model_id, known_idn_matches in known_inst_lut.get((vendor_id, product_id), []):
        if any(idn_match in idn_readback for idn_match in known_idn_matches):
            return model_id, vendor_id, product_id
    return None, vendor_id, product_id


def match_model_by_idn_only(idn_readback, known_inst_lut):
    """Vid/pid-agnostic search -- used for IP-discovered devices, where no
    USB descriptor gives us vendor/product ids upfront."""
    for (vendor_id, product_id), candidates in known_inst_lut.items():
        for model_id, idn_values in candidates:
            if any(v in idn_readback for v in idn_values):
                return model_id, vendor_id, product_id
    return None, None, None


def canonical_name_from_yaml(yaml_catalog, vendor_id, product_id, serial=None, ip_addr=None):
    return None


## ========================= RunHistory sync / catalog building ====================================

def sync_entry(entry_table, session_id, serial, new_fields):
    """Idempotent update -- within-SESSION dedup across scans.
    
    Can be run with a catalog with no elements to bootstrap the sessions'
    instrument data.
    """

    existing = entry_table.row((session_id, serial)).read()

    # Handle case of first session write
    if existing is None:
        entry_table.insert(dict(session_id=session_id, serial=serial, **new_fields))
        return 'inserted'

    # Check for diffs between old session and current session.
    changed = {k: v for k, v in new_fields.items() if getattr(existing, k) != v}
    if not changed:
        return 'unchanged'

    entry_table.row((session_id, serial)).update(**changed)
    return 'updated'


def build_catalog_protobuf_msg(catalog: message_pb2.Catalog, 
                        model_id: str, 
                        vendor_id: int, 
                        product_id: int, 
                        sticker_name: str, 
                        connection_type: message_pb2.Protocol, 
                        address: str):

    """Writes the detected instrument info into a message_pb2.Catalog
    object in-place.
    """
    model = catalog.model_info[model_id]
    model.vendor_id = vendor_id
    model.product_id = product_id
    model.connection_protocols[connection_type] = message_pb2.Protocol.PROTOCOL_TYPE_VISA
    model.device_info[sticker_name].connection_to_address[connection_type] = address


## ========================= Periodic scan (TaskNode: instrument_scanner) ====================================
## TaskNode is a wrapper around this function that dependency injects the scanner and session logger
## objects. 
## Jobs:
## 1. Periodically scan all IP and USB connections and sync's the current session's database record
## 2. If there is a diff, create a fresh protobuf Catalog object so the Router can be used to 
##    initialize the new class of instrument

def scan_network_and_sync_catalog(resources):
    scanner = resources.hardware_scanner
    session = resources.session_logger

    known_inst_lut = build_known_instrument_lut(scanner.config_rw)
    yaml_catalog = yaml.safe_load(_INSTRUMENT_CATALOG_YAML.read_text())
    entry_table = session.instrument_entry_table()

    catalog = message_pb2.Catalog()
    usb_detected = scanner.scan_usb()
    ip_detected = scanner.scan_ip(_get_next_ip_block()) or []

    for usb_dev in usb_detected:
        vid, pid, serial = usb_dev['vendor_id'], usb_dev['product_id'], usb_dev['serial']
        if serial is None:
            continue
        visa_address = f'USB0::{vid}::{pid}::{serial}::0::INSTR'

        idn = _get_idn(visa_address)
        if not idn:
            continue
        idn_fields = idn.decode().strip().split(',')
        if len(idn_fields) != 4:
            continue

        model_id, _, _ = match_model_by_vidpid_and_idn(vid, pid, idn_fields[1], known_inst_lut)
        if model_id is None:
            continue
        canonical = canonical_name_from_yaml(yaml_catalog, vid, pid, serial=serial) or serial

        sync_entry(entry_table, session.session_id, serial, dict(
            model_id=model_id, vendor_id=vid, product_id=pid, ip_addr='', canonical_name=canonical,
        ))

        build_catalog_protobuf_msg(
            catalog, model_id, vid, pid, canonical, message_pb2.CONNECTION_TYPE_USB, serial,
        )

    for ip_addr in ip_detected:
        visa_address = f'TCPIP0::{ip_addr}::INSTR'
        idn = _get_idn(visa_address)
        if not idn:
            continue

        idn_fields = idn.decode().strip().split(',')
        if len(idn_fields) != 4:
            continue

        serial = idn_fields[2]
        model_id, vid, pid = match_model_by_idn_only(idn_fields[1], known_inst_lut)
        if model_id is None:
            continue

        canonical = canonical_name_from_yaml(yaml_catalog, vid, pid, ip_addr=ip_addr) or serial
        sync_entry(entry_table, session.session_id, serial, dict(
            model_id=model_id, vendor_id=vid, product_id=pid, ip_addr=ip_addr, canonical_name=canonical,
        ))
        build_catalog_protobuf_msg(
            catalog, model_id, vid, pid, canonical, message_pb2.CONNECTION_TYPE_IP, ip_addr,
        )

    if len(catalog.model_info) > 0:
        resources.connector_router.refresh_catalog(catalog)


## ========================= One-shot boot recheck (install.by_factory: session_logger) =================

def bootstrap_from_previous_session(nodespec):
    """One-shot, fired right after session_logger installs. Rechecks only
    the instruments the PREVIOUS session actually recorded."""
    session = nodespec.node
    router = session.resources.connector_router
    scanner = session.resources.hardware_scanner
    entry_table = session.instrument_entry_table()
    catalog = message_pb2.Catalog()

    for prev in session.previous_session_entries():
        if prev.ip_addr:
            present = scanner.ping_single_ip(prev.ip_addr)
            connection_type = message_pb2.CONNECTION_TYPE_IP
            address = prev.ip_addr
        else:
            present = scanner.usb_serial_present(prev.serial, prev.vendor_id, prev.product_id)
            connection_type = message_pb2.CONNECTION_TYPE_USB
            address = prev.serial

        if not present:
            continue

        build_catalog_protobuf_msg(
            catalog, prev.model_id, prev.vendor_id, prev.product_id,
            prev.canonical_name, connection_type, address,
        )
        sync_entry(entry_table, session.session_id, prev.serial, dict(
            model_id=prev.model_id, vendor_id=prev.vendor_id, product_id=prev.product_id,
            ip_addr=prev.ip_addr, canonical_name=prev.canonical_name,
        ))

    if len(catalog.model_info) > 0:
        router.refresh_catalog(catalog)

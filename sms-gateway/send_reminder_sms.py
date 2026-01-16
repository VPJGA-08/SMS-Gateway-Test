#!/usr/bin/env python3
import time
import sys
import re
import configparser
import serial
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logger(cfg):
    log_path = cfg.get("LOGGING", "log_file", fallback="./sms_sender.log").strip()
    level_str = cfg.get("LOGGING", "level", fallback="INFO").strip().upper()
    max_bytes = cfg.getint("LOGGING", "max_bytes", fallback=1_048_576)
    backup_count = cfg.getint("LOGGING", "backup_count", fallback=3)

    level = getattr(logging, level_str, logging.INFO)
    log_file = str(Path(log_path).expanduser())

    logger = logging.getLogger("sms_sender")
    logger.setLevel(level)
    logger.handlers.clear()

    fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console output too (simple)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("%(message)s"))
    ch.setLevel(level)
    logger.addHandler(ch)

    logger.debug(f"Logger initialized. File={log_file}, level={level_str}")
    return logger

def read_until(ser, want_any_of, timeout):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            txt = buf.decode(errors="ignore")
            for w in want_any_of:
                if w in txt:
                    return True, txt
            if "ERROR" in txt:
                return False, txt
        time.sleep(0.05)
    return False, buf.decode(errors="ignore")

def send_at(ser, cmd, expect="OK", timeout=5, logger=None):
    if logger:
        logger.debug(f">>> {cmd}")
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    ok, resp = read_until(ser, [expect, "ERROR"], timeout)
    if logger:
        # Collapse newlines for cleaner logs
        oneline = " ".join(resp.split())
        logger.debug(f"<<< {oneline}")
    return ok and (expect in resp), resp

def parse_recipients(cfg):
    # Prefer phone_numbers (can be comma/newline separated)
    numbers_block = cfg.get("SMS", "phone_numbers", fallback="").strip()
    if numbers_block:
        raw = [p.strip() for p in re.split(r"[,\n]", numbers_block)]
        nums = [p for p in raw if p]
        if nums:
            return nums
    # Fallback to single phone_number (old behavior)
    single = cfg.get("SMS", "phone_number", fallback="").strip()
    return [single] if single else []

def open_serial(port, baud, logger):
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=1,
            write_timeout=5,
            rtscts=False,
            dsrdtr=False,
        )
        logger.debug(f"Opened serial port {port} @ {baud}")
        return ser
    except Exception as e:
        logger.error(f"Could not open serial port {port}: {e}")
        sys.exit(2)

def handshake_and_prepare(ser, sim_pin, logger):
    # Basic handshake
    for _ in range(3):
        ok, resp = send_at(ser, "AT", "OK", timeout=2, logger=logger)
        if ok:
            break
        time.sleep(0.5)
    else:
        logger.error("Modem did not respond to AT. Is the SIM7600 powered and the port correct?")
        logger.error(resp)
        sys.exit(3)

    # Quiet echo & verbose errors
    send_at(ser, "ATE0", "OK", timeout=2, logger=logger)
    send_at(ser, "AT+CMEE=2", "OK", timeout=2, logger=logger)

    # SIM PIN handling (if needed)
    ok, resp = send_at(ser, "AT+CPIN?", "OK", timeout=3, logger=logger)
    if "SIM PIN" in resp:
        if not sim_pin:
            logger.error("SIM requires PIN but no pin provided in config (MODEM.sim_pin).")
            sys.exit(4)
        ok, resp = send_at(ser, f'AT+CPIN="{sim_pin}"', "OK", timeout=5, logger=logger)
        if not ok:
            logger.error(f"Failed to enter SIM PIN: {resp}")
            sys.exit(4)
        # Wait for SIM ready
        for _ in range(20):
            time.sleep(1)
            ok, resp = send_at(ser, "AT+CPIN?", "OK", timeout=2, logger=logger)
            if "READY" in resp:
                break
        else:
            logger.error("SIM did not become READY in time.")
            sys.exit(4)

    # Optional: network checks
    send_at(ser, "AT+CREG?", "OK", timeout=2, logger=logger)
    send_at(ser, "AT+COPS?", "OK", timeout=5, logger=logger)

    # SMS text mode & GSM charset
    ok, resp = send_at(ser, "AT+CMGF=1", "OK", timeout=2, logger=logger)
    if not ok:
        logger.error(f"Failed to set text mode: {resp}")
        sys.exit(5)
    send_at(ser, 'AT+CSCS="GSM"', "OK", timeout=2, logger=logger)
    send_at(ser, "AT+CSMP=17,167,0,0", "OK", timeout=2, logger=logger)

def send_sms_to_number(ser, number, reminder_message, logger):
    logger.info(f"Sending SMS to {number}")
    ok, resp = send_at(ser, f'AT+CMGS="{number}"', ">", timeout=5, logger=logger)
    if not ok:
        logger.error(f"No '>' prompt for CMGS to {number}. Response: {resp}")
        return False, resp

    ser.write(reminder_message.encode("ascii", errors="replace"))
    ser.write(b"\x1A")  # Ctrl+Z
    ser.flush()

    ok, resp = read_until(ser, ["+CMGS", "OK", "ERROR"], timeout=60)
    # Try to extract message reference
    m = re.search(r"\+CMGS:\s*(\d+)", resp or "")
    msg_ref = m.group(1) if m else "?"
    if "+CMGS" in resp and "OK" in resp:
        logger.info(f"✅ Sent to {number} (ref {msg_ref})")
        return True, resp
    else:
        logger.error(f"❌ Failed to send to {number}. Response: {resp}")
        return False, resp

def main():
    # Load config
    cfg = configparser.ConfigParser()
    cfg.read("sms_config.ini")

    logger = setup_logger(cfg)

    port = cfg.get("MODEM", "port", fallback="/dev/ttyUSB2")
    baud = cfg.getint("MODEM", "baudrate", fallback=115200)
    sim_pin = cfg.get("MODEM", "sim_pin", fallback="").strip()

    recipients = parse_recipients(cfg)
    reminder_message = cfg.get("SMS", "reminder_message", fallback="").strip()
    delay_between = cfg.getfloat("SMS", "delay_between_sends", fallback=2.0)

    if not recipients:
        logger.error("Config error: set [SMS].phone_numbers or [SMS].phone_number in sms_config.ini")
        sys.exit(2)
    if not reminder_message:
        logger.error("Config error: set [SMS].reminder_message in sms_config.ini")
        sys.exit(2)

    ser = open_serial(port, baud, logger)
    try:
        handshake_and_prepare(ser, sim_pin, logger)

        successes = 0
        for i, number in enumerate(recipients, 1):
            ok, _ = send_sms_to_number(ser, number, reminder_message, logger)
            successes += int(ok)
            if i < len(recipients):
                time.sleep(max(0.0, delay_between))

        if successes == len(recipients):
            logger.info(f"All {successes}/{len(recipients)} messages sent successfully.")
            print(f"✅ Done. See log for details.")
            sys.exit(0)
        elif successes == 0:
            logger.error("No messages were sent successfully.")
            print("❌ No messages sent. Check the log for details.")
            sys.exit(8)
        else:
            logger.warning(f"Partial success: {successes}/{len(recipients)} messages sent.")
            print(f"⚠️ Partial success ({successes}/{len(recipients)}). Check the log.")
            sys.exit(9)
    finally:
        try:
            ser.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()

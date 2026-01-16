#!/usr/bin/env python3
import subprocess
import sys
import time
import logging
import signal
import configparser
from pathlib import Path

# ---------- Configuration loading ----------
DEFAULTS = {
    "router_ip": "172.168.133.1",
    "internet_ip": "8.8.8.8",                     # <<< NEW (primary target)
    "check_interval_seconds": "30",
    "ping_count": "4",
    "failure_threshold": "4",
    "reminder_interval_seconds": "300",
    "alert_power_script": "send_alert_power_sms.py",
    "alert_network_script": "send_alert_network_sms.py",  # <<< NEW
    "reminder_script": "send_reminder_sms.py",
    "clear_script": "send_clear_sms.py",
    "log_file": "network_monitor.log",
    "log_level": "INFO",
}

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "monitor_config.ini"

def load_config():
    cfg = DEFAULTS.copy()
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE)
        if "monitor" in parser:
            section = parser["monitor"]
            for k in DEFAULTS:
                if k in section and section[k] != "":
                    cfg[k] = section[k]
    # cast numerics
    cfg["check_interval_seconds"] = int(cfg["check_interval_seconds"])
    cfg["ping_count"] = int(cfg["ping_count"])
    cfg["failure_threshold"] = int(cfg["failure_threshold"])
    cfg["reminder_interval_seconds"] = int(cfg["reminder_interval_seconds"])
    return cfg

def setup_logging(log_path: Path, level_name: str):
    level = getattr(logging, level_name.upper(), logging.INFO)
    log_path = log_path if log_path.is_absolute() else BASE_DIR / log_path
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")]
    )
    # Log startup
    logging.info("Network monitor starting.")

# ---------- Helpers ----------
def run_ping(ip: str, count: int) -> bool:
    """
    Returns True if at least one reply is received (ping exit code 0),
    False otherwise.
    """
    try:
        proc = subprocess.run(
            ["ping", "-c", str(count), "-W", "2", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return proc.returncode == 0
    except Exception as e:
        # If ping itself errors out, treat as a failure and log it.
        logging.exception(f"Ping command error: {e}")
        return False

def run_script(script_name: str):
    script_path = (BASE_DIR / script_name).resolve()
    if not script_path.exists():
        logging.error(f"Script not found: {script_path}")
        return
    try:
        res = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=120
        )
        if res.returncode == 0:
            logging.info(f"Executed {script_name} successfully.")
        else:
            logging.error(f"{script_name} failed with code {res.returncode}. "
                          f"stdout: {res.stdout.strip()} stderr: {res.stderr.strip()}")
    except Exception as e:
        logging.exception(f"Error running {script_name}: {e}")

# ---------- Main loop ----------
def main():
    cfg = load_config()
    setup_logging(Path(cfg["log_file"]), cfg["log_level"])

    router_ip = cfg["router_ip"]
    internet_ip = cfg["internet_ip"]                 # <<< NEW
    check_interval = cfg["check_interval_seconds"]
    ping_count = cfg["ping_count"]                   # per-try echo requests
    failure_threshold = cfg["failure_threshold"]     # tries before declaring outage
    reminder_interval = cfg["reminder_interval_seconds"]

    alert_power_script = cfg["alert_power_script"]
    alert_network_script = cfg["alert_network_script"]   # <<< NEW
    reminder_script = cfg["reminder_script"]
    clear_script = cfg["clear_script"]

    failure_streak = 0
    in_outage = False
    last_reminder_monotonic = 0.0

    stop_flag = {"stop": False}
    def handle_sig(signum, frame):
        logging.info(f"Received signal {signum}. Exiting.")
        stop_flag["stop"] = True
    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    while not stop_flag["stop"]:
        # <<< CHANGED: ping the INTERNET target first, not the router
        ok = run_ping(internet_ip, ping_count)

        if ok:
            # Do not log for normal success
            if in_outage:
                # Recovery detected (power & network assumed back if internet is reachable)
                in_outage = False
                failure_streak = 0
                run_script(clear_script)
                logging.info("Connectivity restored (internet reachable); cleared outage state.")
            else:
                failure_streak = 0

        else:
            failure_streak += 1
            logging.warning(f"Primary ping FAILED ({failure_streak}/{failure_threshold}) to {internet_ip}.")

            if not in_outage and failure_streak >= failure_threshold:
                # <<< NEW: Diagnose root cause by pinging the router ONCE
                router_ok = run_ping(router_ip, 1)   # <<< NEW (single attempt)
                if router_ok:
                    # Network-only outage (WAN or upstream), power is OK
                    run_script(alert_network_script)  # <<< NEW
                    logging.error("Network-only outage detected (router reachable, internet not). Alerted network.")
                else:
                    # Likely power outage impacting router/network
                    run_script(alert_power_script)
                    logging.error("Power/network outage detected (router unreachable). Alerted power.")

                in_outage = True
                last_reminder_monotonic = time.monotonic()  # wait full interval before 1st reminder

            elif in_outage:
                # During outage, keep trying internet and send periodic reminders
                if time.monotonic() - last_reminder_monotonic >= reminder_interval:
                    run_script(reminder_script)
                    logging.warning("Reminder sent during outage (internet still unreachable).")
                    last_reminder_monotonic = time.monotonic()

        time.sleep(check_interval)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        sys.exit(1)
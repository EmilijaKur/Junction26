# SPDX-FileCopyrightText: Copyright (C) Arduino s.r.l. and/or its affiliated companies
#
# SPDX-License-Identifier: MPL-2.0

import csv
import datetime
import math
import time
from pathlib import Path

from arduino.app_bricks.dbstorage_tsstore import TimeSeriesStore
from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App, Bridge
from fire_logic import FireAssessor

db = TimeSeriesStore()
assessor = FireAssessor()
last_alarm = 0

# ---------- Event log (CSV) setup ----------
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

FIRE_HEADER = ["date", "time", "event", "temperature_c", "humidity_pct", "emc_pct", "flame_raw"]
SOUND_HEADER = ["date", "time", "event", "amplitude_raw", "baseline_raw"]

FIRE_REASONS = {1: "flame detected", 2: "high temperature",
                3: "rapid temperature rise", 4: "dry and hot (fuel moisture low)"}
SOUND_REASONS = {1: "impulse (possible gunshot)", 2: "sustained loud noise (possible chainsaw)"}

TEST_FIRE_CSV = DATA_DIR / "test_fire_events.csv"
TEST_SOUND_CSV = DATA_DIR / "test_sound_events.csv"
TEST_SAMPLES = 5

# Start every run with empty test files; they fill from real sensor readings
TEST_FIRE_CSV.unlink(missing_ok=True)
TEST_SOUND_CSV.unlink(missing_ok=True)
test_count = {"fire": 0, "sound": 0}


def fire_csv():
    return DATA_DIR / f"fire_events_{datetime.datetime.now():%Y-%m}.csv"

def sound_csv():
    return DATA_DIR / f"sound_events_{datetime.datetime.now():%Y-%m}.csv"

def append_row(path, header, row):
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(header)
        w.writerow(row)

def stamp():
    now = datetime.datetime.now().astimezone()
    return now.date().isoformat(), now.strftime("%H:%M:%S")


# ---------- Web UI ----------
def on_get_samples(resource: str, start: str, aggr_window: str):
    samples = db.read_samples(measure=resource, start_from=start, aggr_window=aggr_window, aggr_func="mean", limit=100)
    return [{"ts": s[1], "value": s[2]} for s in samples]

ui = WebUI()
ui.expose_api("GET", "/get_samples/{resource}/{start}/{aggr_window}", on_get_samples)
#UNCOMMENT AFTER WE GET DATA FROM EMILIJA'S FILE ui.expose_api("GET", "/camera_result/{conf}/{area}", on_camera_result)


# ---------- Sensor samples -> DB + UI ----------
def record_sensor_samples(celsius: float, humidity: float):
    """Callback invoked by the board sketch via Bridge.notify to send sensor samples.
    Stores temperature and humidity samples in the time-series DB and forwards them to the Web UI.
    """
    if celsius is None or humidity is None:
        print("Received invalid sensor samples: celsius=%s, humidity=%s" % (celsius, humidity))
        return

    assessor.add_temp(float(celsius))

    # --- TEMPORARY TEST CALL---
    on_camera_result(0.9, 0.05)

    ts = int(datetime.datetime.now().timestamp() * 1000)
    # Write samples to time-series DB
    db.write_sample("temperature", float(celsius), ts)
    db.write_sample("humidity", float(humidity), ts)

    # Push realtime updates to the UI
    ui.send_message('temperature', {"value": float(celsius), "ts": ts})
    ui.send_message('humidity', {"value": float(humidity), "ts": ts})

    # --- Derived metrics ---
    T = float(celsius)
    RH = float(humidity)

    # Dew point (Magnus formula) - compute only when RH > 0 to avoid math.log(0)
    a = 17.27
    b = 237.7
    dew_point = None
    if RH > 0.0:
        rh_frac = max(min(RH, 100.0), 1e-6)
        gamma = (a * T) / (b + T) + math.log(rh_frac / 100.0)
        dew_point = (b * gamma) / (a - gamma)

    # Heat Index (Rothfusz regression). Convert to Fahrenheit and back to Celsius.
    T_f = T * 9.0 / 5.0 + 32.0
    R = max(min(RH, 100.0), 0.0)
    HI_f = (-42.379 + 2.04901523 * T_f + 10.14333127 * R - 0.22475541 * T_f * R
            - 0.00683783 * T_f * T_f - 0.05481717 * R * R
            + 0.00122874 * T_f * T_f * R + 0.00085282 * T_f * R * R
            - 0.00000199 * T_f * T_f * R * R)
    heat_index = (HI_f - 32.0) * 5.0 / 9.0

    # Absolute humidity (g/m^3)
    absolute_humidity = None
    if RH is not None and RH >= 0.0:
        es = 6.112 * math.exp((17.67 * T) / (T + 243.5))
        absolute_humidity = es * (R / 100.0) * 2.1674 / (273.15 + T)

    # Store and forward derived metrics if computed
    if dew_point is not None:
        db.write_sample("dew_point", float(dew_point), ts)
        ui.send_message('dew_point', {"value": float(dew_point), "ts": ts})
    if heat_index is not None:
        db.write_sample("heat_index", float(heat_index), ts)
        ui.send_message('heat_index', {"value": float(heat_index), "ts": ts})
    if absolute_humidity is not None:
        db.write_sample("absolute_humidity", float(absolute_humidity), ts)
        ui.send_message('absolute_humidity', {"value": float(absolute_humidity), "ts": ts})


# ---------- Camera result -> status + alarm ----------
def on_camera_result(conf: float, area: float):
    """Called once per camera frame with the model's confidence and flame size."""
    global last_alarm
    status = assessor.assess(conf, area)
    print("status:", status)
    ui.send_message('status', {"value": status})

    if status == "UNCONTROLLED" and time.time() - last_alarm > 3:
        last_alarm = time.time()
        Bridge.notify("alarm")
        Bridge.call("alert-matei")

    return status


# ---------- Real event logs ----------
def fire_event(code, temp, hum, emc, flame):
    d, t = stamp()
    append_row(fire_csv(), FIRE_HEADER,
               [d, t, FIRE_REASONS.get(code, code), round(temp, 2), round(hum, 2), round(emc, 2), flame])

def sound_event(code, amplitude, baseline):
    d, t = stamp()
    append_row(sound_csv(), SOUND_HEADER,
               [d, t, SOUND_REASONS.get(code, code), round(amplitude, 1), round(baseline, 1)])


# ---------- Test files from real readings (first few samples after boot) ----------
def test_fire_sample(temp, hum, emc, flame):
    if test_count["fire"] >= TEST_SAMPLES:
        return
    test_count["fire"] += 1
    d, t = stamp()
    append_row(TEST_FIRE_CSV, FIRE_HEADER,
               [d, t, "test sample (real reading)", round(temp, 2), round(hum, 2), round(emc, 2), flame])

def test_sound_sample(amplitude, baseline):
    if test_count["sound"] >= TEST_SAMPLES:
        return
    test_count["sound"] += 1
    d, t = stamp()
    append_row(TEST_SOUND_CSV, SOUND_HEADER,
               [d, t, "test sample (real reading)", round(amplitude, 1), round(baseline, 1)])

def record_live_extras(sound: float, flame: float, emc: float):
    """Called once per second by the sketch. Goes to the DB and UI only, not to the CSVs."""
    print(f"[live] sound={sound:.0f}  flame={flame:.0f}  emc={emc:.2f} %")
    ts = int(datetime.datetime.now().timestamp() * 1000)
    for name, value in (("sound", sound), ("flame", flame), ("emc", emc)):
        if value is None:
            continue
        db.write_sample(name, float(value), ts)
        ui.send_message(name, {"value": float(value), "ts": ts})
# ---------- Register all callbacks, then run ----------
Bridge.provide("record_sensor_samples", record_sensor_samples)
Bridge.provide("fire_event", fire_event)
Bridge.provide("sound_event", sound_event)
Bridge.provide("test_fire_sample", test_fire_sample)
Bridge.provide("test_sound_sample", test_sound_sample)
Bridge.provide("record_live_extras", record_live_extras)
print("Registered callbacks: record_sensor_samples, fire_event, sound_event, test_*_sample")

print("Starting App...")
App.run()
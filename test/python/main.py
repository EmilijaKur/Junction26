import csv
from datetime import datetime
from pathlib import Path

from arduino.app_utils import *   # provides Bridge and App; keep whatever imports your original had

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
    return DATA_DIR / f"fire_events_{datetime.now():%Y-%m}.csv"

def sound_csv():
    return DATA_DIR / f"sound_events_{datetime.now():%Y-%m}.csv"

def append_row(path, header, row):
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(header)
        w.writerow(row)

def stamp():
    now = datetime.now().astimezone()
    return now.date().isoformat(), now.strftime("%H:%M:%S")

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

Bridge.provide("fire_event", fire_event)
Bridge.provide("sound_event", sound_event)
Bridge.provide("test_fire_sample", test_fire_sample)
Bridge.provide("test_sound_sample", test_sound_sample)

App.run()
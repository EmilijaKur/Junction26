#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>
#include <tuple>

ModulinoThermo thermo;
ModulinoBuzzer buzzer;

const int MIC_PIN   = A0;   // KY-038 AO
const int FLAME_PIN = A1;

int frequency = 440;   // buzzer tone in Hz
int duration  = 3000;  // buzzer tone length in ms

float latestTemp  = NAN;
float latestHum   = NAN;
float latestSound = 0;

// ---- Tune these after watching your normal values (12-bit: 0-4095) ----
const int   FLAME_THRESHOLD   = 500;
const bool  FLAME_ACTIVE_LOW  = true;   // flip if your flame module reads higher with fire
const float TEMP_ALARM_C      = 50.0;
const float RISE_ALARM_C_MIN  = 8.0;
const float EMC_DANGER        = 5.0;
const float DRY_HOT_MIN_TEMP  = 30.0;

// KY-038 starting guesses: check the "MIC max amp" printout and adjust
const float MIN_IMPULSE_AMP   = 150;
const float MIN_SUSTAINED_AMP = 80;
const unsigned long SUSTAINED_MS = 8000;
// -----------------------------------------------------------------------

const unsigned long MIC_WINDOW_MS   = 50;
const unsigned long THERMO_INTERVAL = 1000;
const unsigned long WARMUP_MS       = 5000;

// Real-data test samples sent right after boot
const unsigned long TEST_START_MS = 6000;
const int TEST_SAMPLES = 5;
int testSent = 0;
float ampMaxSec = 0;   // loudest mic window since the last once-per-second reset

// Fire codes: 1 flame, 2 high temp, 3 rapid rise, 4 dry and hot
// Sound codes: 1 impulse, 2 sustained

unsigned long lastThermo = 0;
unsigned long lastRiseRef = 0;
float tempRef = NAN;
unsigned long lastFireLog[5] = {0, 0, 0, 0, 0};

unsigned long winStart = 0;
int winMin = 4095, winMax = 0;
float baseline = -1;
unsigned long loudSince = 0, lastLoudSeen = 0;
unsigned long lastImpulseLog = 0, lastSustainedLog = 0;

float emcPercent(float tempC, float rh) {
  float t = tempC * 9.0 / 5.0 + 32.0;
  if (rh < 10)  return 0.03229 + 0.281073 * rh - 0.000578 * rh * t;
  if (rh < 50)  return 2.22749 + 0.160107 * rh - 0.01478 * t;
  return 21.0606 + 0.005565 * rh * rh - 0.00035 * rh * t - 0.483199 * rh;
}

bool cooldownOk(unsigned long &last, unsigned long period, unsigned long now) {
  if (last == 0 || now - last >= period) { last = now; return true; }
  return false;
}

void buzz() {
  buzzer.tone(frequency, duration);
}

std::tuple<float, float, float> set_data_temp() {
  return std::make_tuple(latestTemp, latestHum, latestSound);
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);   // fixes the range at 0-4095
  Bridge.begin();
  Modulino.begin();
  buzzer.begin();
  Bridge.provide_safe("alert-matei", buzz);
  Bridge.provide_safe("get_stuff", set_data_temp);

  if (!thermo.begin()) {
    Serial.println("- Modulino Thermo not detected! Check the Qwiic connection...");
    while (1);
  }
  Serial.println("- Started");
  winStart = millis();
}

void handleSoundWindow(unsigned long now, float amp) {
  if (baseline < 0) baseline = amp;
  bool warm = now > WARMUP_MS;
  if (amp > ampMaxSec) ampMaxSec = amp;

  float impulseThr   = max(baseline * 4.0f, MIN_IMPULSE_AMP);
  float sustainedThr = max(baseline * 2.5f, MIN_SUSTAINED_AMP);

  bool impulse = warm && amp > impulseThr;
  bool loud = amp > sustainedThr;

  if (impulse && cooldownOk(lastImpulseLog, 2000, now)) {
    Bridge.notify("sound_event", 1, amp, baseline);
    Serial.println(">>> SOUND EVENT 1 (impulse) sent to CSV");
  }

  if (loud) {
    lastLoudSeen = now;
    if (loudSince == 0) loudSince = now;
    if (warm && now - loudSince >= SUSTAINED_MS) {
      Serial.println("SUSTAINED LOUD NOISE DETECTED");
      if (cooldownOk(lastSustainedLog, 60000, now)) {
        Bridge.notify("sound_event", 2, amp, baseline);
        Serial.println(">>> SOUND EVENT 2 (sustained) sent to CSV");
      }
    }
  } else if (loudSince != 0 && now - lastLoudSeen > 1000) {
    loudSince = 0;
  }

  // Slowly adapt baseline, but don't learn from loud events
  if (amp < baseline * 2.0f + 5) baseline += 0.01f * (amp - baseline);
}

void loop() {
  unsigned long now = millis();

  // Sample the mic continuously, so short bangs are not missed
  int v = analogRead(MIC_PIN);
  if (v < winMin) winMin = v;
  if (v > winMax) winMax = v;

  if (now - winStart >= MIC_WINDOW_MS) {
    float amp = winMax - winMin;
    winStart = now;
    winMin = 4095; winMax = 0;
    handleSoundWindow(now, amp);
  }

  // Thermo + humidity + flame + mic summary: once per second
  if (now - lastThermo >= THERMO_INTERVAL) {
    lastThermo = now;

    // Loudest mic window of the last second (reset right away)
    float soundMax = ampMaxSec;
    ampMaxSec = 0;

    Serial.print("MIC max amp (last 1 s): "); Serial.print(soundMax);
    Serial.print(" | baseline: "); Serial.print(baseline);
    Serial.print(" | impulseThr: "); Serial.print(max(baseline * 4.0f, MIN_IMPULSE_AMP));
    Serial.print(" | sustainedThr: "); Serial.println(max(baseline * 2.5f, MIN_SUSTAINED_AMP));

    float temperature = thermo.getTemperature();
    float humidity = thermo.getHumidity();
    int flameLevel = analogRead(FLAME_PIN);

    if (isnan(temperature) || isnan(humidity)) {
      Serial.println("THERMO: invalid reading (NaN)");
      Serial.print("FLAME raw: "); Serial.println(flameLevel);
      return;
    }

    float emc = emcPercent(temperature, humidity);

    latestTemp = temperature;
    latestHum = humidity;
    latestSound = soundMax;

    // Real readings for the test CSVs
    if (now >= TEST_START_MS && testSent < TEST_SAMPLES) {
      Bridge.notify("test_fire_sample", temperature, humidity, emc, flameLevel);
      Bridge.notify("test_sound_sample", soundMax, baseline);
      testSent++;
      Serial.print(">>> TEST SAMPLE "); Serial.print(testSent);
      Serial.print("/"); Serial.println(TEST_SAMPLES);
    }

    float rise = 0;
    if (isnan(tempRef)) { tempRef = temperature; lastRiseRef = now; }
    else if (now - lastRiseRef >= 10000) {
      rise = (temperature - tempRef) * 6.0;
      tempRef = temperature;
      lastRiseRef = now;
    }

    bool flame = FLAME_ACTIVE_LOW ? (flameLevel < FLAME_THRESHOLD)
                                  : (flameLevel > FLAME_THRESHOLD);
    int code = 0;
    if (flame) code = 1;
    else if (temperature >= TEMP_ALARM_C) code = 2;
    else if (rise >= RISE_ALARM_C_MIN) code = 3;
    else if (emc < EMC_DANGER && temperature > DRY_HOT_MIN_TEMP) code = 4;

    Serial.print("T: "); Serial.print(temperature);
    Serial.print(" C | RH: "); Serial.print(humidity);
    Serial.print(" % | EMC: "); Serial.print(emc);
    Serial.print(" % | flame raw: "); Serial.print(flameLevel);
    Serial.print(" | rise: "); Serial.print(rise);
    Serial.println(" C/min");
    Bridge.notify("record_sensor_samples", temperature, humidity);   // existing callback: temp + humidity
    Bridge.notify("record_live_extras", soundMax, flameLevel, emc);  // new callback: sound, flame, fuel moisture

    if (code) {
      const char* names[] = {"", "FLAME", "HIGH TEMP", "RAPID RISE", "DRY AND HOT"};
      Serial.print("!!! FIRE CONDITION DETECTED: "); Serial.println(names[code]);

      unsigned long period = (code == 4) ? 600000UL : 30000UL;
      if (cooldownOk(lastFireLog[code], period, now)) {
        Bridge.notify("fire_event", code, temperature, humidity, emc, flameLevel);
        Serial.println(">>> FIRE EVENT sent to CSV");
        if (code != 4) buzzer.tone(frequency, duration);  // non-blocking local alarm
      }
    }
  }
}
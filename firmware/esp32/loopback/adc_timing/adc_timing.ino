// adc_timing.ino
//
// Measures how long one analogRead() really takes on this board, in the same order the
// capture loop uses (V on GPIO34, then I on GPIO35 — see dual_core_loopback.ino loop()).
// Why it matters: V and I are read one after the other, so I is sampled later than V by
// roughly one analogRead(). That gap is a fake phase shift between the two channels:
//     skew_deg = 360 * gap_us / drive_period_us     (50 Hz: gap * 0.018 deg, 1 kHz: gap * 0.36 deg)
// Negligible at 50 Hz; matters if the drive moves toward the ~1 kHz ROADMAP target.
//
// Two independent measurements, so one can check the other:
//   1. esp_timer_get_time() around each read, averaged over N reads (timer resolution is 1 us,
//      the average resolves well below that). The cost of the timer call itself is measured
//      with an empty pair and subtracted.
//   2. GPIO23 is HIGH while V is being read and LOW while I is being read, for a logic
//      analyzer: HIGH pulse width = V read time = V->I gap. digitalWrite() adds well under 1 us.
//
// Wiring: same loopback jumpers as dual_core_loopback (GPIO25 -> GPIO34 and GPIO35), so the
// reads see a real voltage. Optional: logic analyzer CH0 -> GPIO23, GND -> GND.
// The DAC is just held at mid-scale here; this sketch doesn't drive a sine.
//
// Serial (921600 baud): one summary line per round, e.g.
//   V read: avg <x> us (min <x>, max <x>) | I read: avg <x> us | timer overhead <x> us | V->I gap ~ <x> us
//
// Board: ESP32 DevKit V1 (DOIT ESP32 DEVKIT V1).

#include "esp_timer.h"

const int DAC_PIN   = 25;
const int ADC_V_PIN = 34;
const int ADC_I_PIN = 35;
const int PROBE_PIN = 23;   // logic-analyzer marker
const unsigned long BAUD = 921600;
const int N_TIMED  = 10000; // reads per channel for method 1
const int N_PULSES = 2000;  // marker pulses for method 2

void setup() {
  Serial.begin(BAUD);
  pinMode(PROBE_PIN, OUTPUT);
  digitalWrite(PROBE_PIN, LOW);
  dacWrite(DAC_PIN, 128);
  delay(500);
  Serial.printf("# adc_timing: N=%d, V=GPIO%d then I=GPIO%d, marker=GPIO%d\n",
                N_TIMED, ADC_V_PIN, ADC_I_PIN, PROBE_PIN);
}

void loop() {
  volatile int sink = 0;   // keeps the compiler from dropping the reads
  int64_t sumOv = 0, sumV = 0, sumI = 0;
  int64_t minV = INT64_MAX, maxV = 0;

  // ---- Method 1: hardware timer ----
  for (int k = 0; k < N_TIMED; k++) {
    int64_t a = esp_timer_get_time();
    int64_t b = esp_timer_get_time();   // empty pair = cost of the timer call itself
    sink += analogRead(ADC_V_PIN);
    int64_t c = esp_timer_get_time();
    sink += analogRead(ADC_I_PIN);
    int64_t d = esp_timer_get_time();
    sumOv += b - a;
    sumV  += c - b;
    sumI  += d - c;
    if (c - b < minV) minV = c - b;
    if (c - b > maxV) maxV = c - b;
  }
  double ov   = (double)sumOv / N_TIMED;
  double vAvg = (double)sumV / N_TIMED - ov;
  double iAvg = (double)sumI / N_TIMED - ov;
  Serial.printf("V read: avg %.2f us (min %lld, max %lld) | I read: avg %.2f us | "
                "timer overhead %.2f us | V->I gap ~ %.2f us\n",
                vAvg, minV, maxV, iAvg, ov, vAvg);

  // ---- Method 2: marker pulses for a logic analyzer ----
  for (int k = 0; k < N_PULSES; k++) {
    digitalWrite(PROBE_PIN, HIGH);
    sink += analogRead(ADC_V_PIN);      // HIGH width = V read time = V->I gap
    digitalWrite(PROBE_PIN, LOW);
    sink += analogRead(ADC_I_PIN);      // LOW width  = I read time
  }

  delay(1000);
}

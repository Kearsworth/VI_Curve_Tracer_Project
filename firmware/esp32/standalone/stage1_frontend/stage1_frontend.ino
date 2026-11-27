// stage1_frontend.ino
//
// Stage 1 of docs/STANDALONE_TESTER_PLAN.md: dual_core_loopback.ino driving the standalone
// analog front end (hardware/sim/stage1_breadboard.svg) instead of a jumper wire. Changes
// vs. dual_core_loopback: DAC amplitude 104 counts (x3.7 gain -> A = 5.0 V at node A),
// meta line carries the front-end A and the default Rr, and GPIO34/35 now read node A /
// node B through the return paths. Convert with: hardware/reader.py --frontend --rr <ohm>.
//
// Original header (still accurate for the timing/core design):
// Step 1 of the dual-core single-board plan (see ../../README.md "Dual-core single-board
// plan" and docs/ROADMAP.md Phase A). Same job as loopback/sine_capture.ino, but split
// across the ESP32's two cores so a slow analogRead()/Serial.printf() on the capture side
// can't stall the drive timing (and vice versa):
//
//   Core 0 — driveTask:   sine LUT -> dacWrite(GPIO25), index chosen from elapsed time
//   Core 1 — loop():      analogRead GPIO34 (V) + GPIO35 (I) -> phase from elapsed time -> CSV
//
// No sync wire: both cores read the same hardware timer (esp_timer_get_time()) against one
// shared t0us, so the capture side labels phase with the same clock the drive side used to
// pick the DAC value. Same "phase from a known reference, never from geometry" rule as
// sine_capture.ino (CLAUDE.md design decision #2).
//
// Wiring (Stage 1 breadboard, hardware/sim/stage1_breadboard.svg): GPIO25 -> a11 (drive amp
// input), GPIO34 -> e30 (node A via return path), GPIO35 -> e34 (node B via return path),
// 3V3 -> a32, VIN -> MT3608 VIN+, GND -> bottom GND rail. Connect GPIO34/35 LAST, only after
// rows 30/34 measure ~1.29 V DC — never wire node A or B (+-5 V) straight to an ADC pin.
//
// Board: ESP32 DevKit V1 (DOIT ESP32 DEVKIT V1).
// Serial output: identical frame to sine_capture.ino -> zero hardware/reader.py changes.

#include <math.h>
#include "esp_timer.h"

// ---------- Pins ----------
const int DAC_PIN   = 25;   // DAC1
const int ADC_V_PIN = 34;   // ADC1_CH6 — voltage across DUT (loopback: the driven node)
const int ADC_I_PIN = 35;   // ADC1_CH7 — sense-resistor channel (loopback: same node, separate pin)

// ---------- Drive (same values as sine_capture.ino, verified on hardware 2026-09-15) ----------
const double DRIVE_FREQ_HZ = 50.0;   // bring-up only; ~1kHz needs DMA ADC (ROADMAP Phase A)
const int LUT_SIZE = 100;
uint8_t sineLUT[LUT_SIZE];
const int DAC_CENTER = 128;
const int DAC_AMPLITUDE_COUNTS = 104;   // dacValue swings 24..232; x3.7 front-end gain -> 4.98 V at node A

const float VREF = 3.3f;
const float FRONTEND_GAIN = 3.7f;        // 1 + 27k/10k (hardware/sim/stage0_check.py)
const float A_NOMINAL_VOLTS = DAC_AMPLITUDE_COUNTS * (VREF / 255.0f) * FRONTEND_GAIN;   // nominal; reader.py measures the real A
const float RR_OHMS_PLACEHOLDER = 1000.0f;   // Stage 1 default jumper (row 46); pass --rr if you move it

const unsigned long BAUD = 921600;

// ---------- UART budget (logic-analyzer finding, 2026-10-09 — see ../../README.md) ----------
// At 921600 8N1 one byte is 10.85 us. Free-running, the core sampled every ~312 us while lines
// grew to ~34 bytes (~372 us) as index/t_us gained digits, so the TX buffer filled and ~1.6 ms
// holes appeared 2-3x per drive cycle. Fix: (1) bound the line length by wrapping index and
// t_us — nothing downstream uses them except to spot drops, which still works modulo the wrap;
// (2) sample on a fixed 333 us grid. Longest line = 4+5+6+4+4 digits + 4 commas + '\n' = 28 bytes
// = ~304 us < 333 us, so the UART never saturates and the rate no longer decays with uptime.
const int64_t SAMPLE_PERIOD_US = 333;     // ~60 samples per 50 Hz cycle
const uint32_t INDEX_WRAP = 10000;        // index printed as 0..9999
const int64_t T_US_WRAP = 100000;         // t_us printed as 0..99999 (wraps every 100 ms = 5 cycles)

// ---------- Shared state (single writer in setup(), read-only afterwards — no mutex) ----------
volatile int64_t t0us = 0;
volatile bool driveRunning = false;   // set by driveTask after its first dacWrite()

// Where each half runs. Arduino's setup()/loop() already run on core 1 (ARDUINO_RUNNING_CORE);
// the drive task is pinned to the other core explicitly rather than relying on that default.
const BaseType_t DRIVE_CORE = 0;
const BaseType_t CAPTURE_CORE = 1;   // = loop()'s core; documented here, checked in setup()

static inline double cyclePosAt(int64_t nowUs) {
  return fmod((double)(nowUs - t0us) * DRIVE_FREQ_HZ / 1e6, 1.0);   // 0..1 fraction of a cycle
}

// Busy loop on core 0: only rewrites the DAC when the LUT index changes. Never blocks on
// Serial or the ADC, so its timing is independent of the capture side. Core 0's idle-task
// watchdog is disabled in setup() because this task never yields (no WiFi/BT in this sketch).
void driveTask(void *) {
  int lastIndex = -1;
  for (;;) {
    int idx = (int)(cyclePosAt(esp_timer_get_time()) * LUT_SIZE) % LUT_SIZE;
    if (idx != lastIndex) {
      dacWrite(DAC_PIN, sineLUT[idx]);
      lastIndex = idx;
      driveRunning = true;
    }
  }
}

uint32_t sampleIndex = 0;
int64_t nextSampleUs = 0;

void setup() {
  Serial.begin(BAUD);
  delay(200);

  for (int i = 0; i < LUT_SIZE; i++) {
    float angle = 2.0f * PI * i / LUT_SIZE;
    int v = DAC_CENTER + (int)roundf(DAC_AMPLITUDE_COUNTS * sinf(angle));
    sineLUT[i] = (uint8_t)constrain(v, 0, 255);
  }

  Serial.println("# stage1_frontend ready");
  Serial.printf(
    "# drive_freq_hz=%.3f lut_size=%d dac_center=%d dac_amplitude_counts=%d "
    "A_nominal_v=%.4f Rr_ohm_placeholder=%.4f vref=%.2f dac_bits=8 adc_bits=12 baud=%lu "
    "drive_core=%d capture_core=%d sample_period_us=%d index_wrap=%lu t_us_wrap=%d\n",
    DRIVE_FREQ_HZ, LUT_SIZE, DAC_CENTER, DAC_AMPLITUDE_COUNTS,
    A_NOMINAL_VOLTS, RR_OHMS_PLACEHOLDER, VREF, BAUD,
    (int)DRIVE_CORE, (int)xPortGetCoreID(),
    (int)SAMPLE_PERIOD_US, (unsigned long)INDEX_WRAP, (int)T_US_WRAP
  );
  if (xPortGetCoreID() != CAPTURE_CORE) {
    Serial.println("# WARNING: loop() is not on the expected capture core");
  }
  Serial.println("index,t_us,phase_rad,adc_v_counts,adc_i_counts");

  t0us = esp_timer_get_time();   // written once, before driveTask exists -> no race

  disableCore0WDT();
  xTaskCreatePinnedToCore(driveTask, "driveTask", 4096, nullptr,
                          configMAX_PRIORITIES - 1, nullptr, DRIVE_CORE);

  while (!driveRunning) { delay(1); }   // skip the few ms before the first DAC value lands
  nextSampleUs = esp_timer_get_time();
}

void loop() {
  // Fixed sample grid. Phase is still labelled from the ACTUAL sample time against the shared
  // t0us (same as sine_capture.ino), so any residual jitter only makes raw spacing uneven.
  while (esp_timer_get_time() < nextSampleUs) { }
  int64_t tSample = esp_timer_get_time();
  nextSampleUs += SAMPLE_PERIOD_US;
  if (nextSampleUs <= tSample) nextSampleUs = tSample + SAMPLE_PERIOD_US;   // overran: skip a slot, don't burst

  int adcV = analogRead(ADC_V_PIN);
  int adcI = analogRead(ADC_I_PIN);

  double phaseRad = cyclePosAt(tSample) * 2.0 * PI;

  Serial.printf("%lu,%lu,%.4f,%d,%d\n", (unsigned long)(sampleIndex % INDEX_WRAP),
                (unsigned long)((tSample - t0us) % T_US_WRAP), phaseRad, adcV, adcI);
  sampleIndex++;
}

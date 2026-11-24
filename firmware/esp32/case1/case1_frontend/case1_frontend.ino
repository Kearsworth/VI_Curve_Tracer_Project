// case1_frontend.ino
//
// Case 1 front end (docs/BOM.md, wiring: docs/CASE1_WIRING.md, layout:
// hardware/sim/case1_breadboard.svg): Dr. Wathis's +-10 V drive stage on one OPA4134PA with
// +-15 V rails from a DD1718PA. Copied from stage1_frontend.ino; only the drive constants, the
// LUT sign and the meta line differ. Convert with: hardware/reader.py --frontend --rr <ohm>
// (reader picks FrontEnd.case1() from the meta line's frontend_case=1).
//
// What changed vs. stage1_frontend:
//   - Channel A is a difference amp: V_A = 6.1 * (V_REF - V_DAC), i.e. INVERTING. The LUT is
//     written as DAC_CENTER - amp*sin so node A = +A*sin(drive phase), the same sign convention
//     synth.py trains on (CLAUDE.md design decision #2: phase = drive phase).
//   - Gain 6.1 (61k/10k). DAC_AMPLITUDE_COUNTS = 63 -> A ~= 4.97 V: matches synth.py's A = 5 V
//     and keeps LEDs under their ~5 V reverse rating. 126 -> ~9.95 V, only after the A = 10
//     retrain (docs/ROADMAP.md Phase B). 1 DAC count = ~79 mV at node A.
//   - DAC_CENTER trims node A's DC offset: if docs/CASE1_WIRING.md step 4 measured node A at
//     +x V with the DAC at 128, RAISE DAC_CENTER by round(x / 0.079) (inverting stage).
//   - Meta line adds frontend_case=1 and dac_inverted=1.
//
// Wiring summary (full table in docs/CASE1_WIRING.md): GPIO25 -> e15 (R1 into pin 2),
// GPIO34 -> f30 (P1, node A via follower C), GPIO35 -> f16 (P2, node B via follower D),
// 3V3 -> j33, VIN -> a3 (1N5819 -> DD1718PA VIN), GND -> bottom GND rail. Connect GPIO34/35
// LAST, only after f30/f16 measure ~1.49 V DC.
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
// (Stage 1's wiring paragraph removed here: Case 1 wiring is in the header above.)
//
// Board: ESP32 DevKit V1 (DOIT ESP32 DEVKIT V1).
// Serial output: identical frame to sine_capture.ino; only new meta keys (frontend_case,
// dac_inverted), which reader.py uses to pick FrontEnd.case1().

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
const int DAC_AMPLITUDE_COUNTS = 63;    // dacValue swings 65..191; x6.1 front-end gain -> 4.97 V at node A

const float VREF = 3.3f;
const float FRONTEND_GAIN = 6.1f;        // (51k+10k)/10k difference amp, inverting (docs/CASE1_WIRING.md)
const float A_NOMINAL_VOLTS = DAC_AMPLITUDE_COUNTS * (VREF / 255.0f) * FRONTEND_GAIN;   // nominal; reader.py measures the real A
const float RR_OHMS_PLACEHOLDER = 1000.0f;   // Case 1 default jumper JS -> f50 (Rr1); pass --rr if you move it

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
    // minus: channel A inverts, so this puts +A*sin(angle) on node A
    int v = DAC_CENTER - (int)roundf(DAC_AMPLITUDE_COUNTS * sinf(angle));
    sineLUT[i] = (uint8_t)constrain(v, 0, 255);
  }

  Serial.println("# case1_frontend ready");
  Serial.printf(
    "# drive_freq_hz=%.3f lut_size=%d dac_center=%d dac_amplitude_counts=%d "
    "A_nominal_v=%.4f Rr_ohm_placeholder=%.4f vref=%.2f dac_bits=8 adc_bits=12 baud=%lu "
    "drive_core=%d capture_core=%d sample_period_us=%d index_wrap=%lu t_us_wrap=%d "
    "frontend_case=1 dac_inverted=1\n",
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

// signature_capture.ino  — ESP32 #2 in the two-board bring-up
//
// The CAPTURE unit that stays unchanged even after ESP32 #1 (signature_gen.ino, a synthetic
// stand-in) is replaced by Dr. Wathis's real circuit + DUT — see
// firmware/esp32/dual_board/README.md. Reads V (GPIO34) and I (GPIO35): two REAL separate
// ADC channels, unlike the single-board loopback (sine_capture.ino) where both alias the
// same physical pin. Also reads a sync pulse (GPIO27) from ESP32 #1 marking the start of
// each drive cycle.
//
// Phase comes from the MEASURED time between consecutive sync pulses, not an assumed
// frequency — this is what keeps CLAUDE.md's "phase from a known reference, never guessed
// from geometry" rule (design decision #2) intact even though this board no longer
// generates the drive itself.
//
// Frame format: the same CSV shape as DATA_CONTRACT.md section 7 (index,t_us,phase_rad,
// adc_v_counts,adc_i_counts), so hardware/reader.py needs NO changes to read this. Before
// the first sync pulse arrives (or if one is overdue), phase_rad is sent as -1 — reader.py's
// existing row validation (0 <= phase <= 2*pi) already rejects that as a malformed row and
// skips it, so "not synced yet" naturally disappears rather than showing up as a fake phase=0.

#include <math.h>

const int ADC_V_PIN = 34;   // <- ESP32 #1's DAC_V_PIN (GPIO25)
const int ADC_I_PIN = 35;   // <- ESP32 #1's DAC_I_PIN (GPIO26) — a REAL separate channel
const int SYNC_PIN  = 27;   // <- ESP32 #1's SYNC_PIN (GPIO27)

const float VREF = 3.3f;
const unsigned long BAUD = 921600;   // the data-stream link to the PC (same as sine_capture)

// Placeholders only: there's no real drive amplitude or sense resistor in this synthetic-
// signature test (see hardware/live_plot_demo.py / reader.py for what these fields mean
// once a real capture exists). Kept so the meta line still carries the fields
// DATA_CONTRACT.md section 1 requires, same convention as sine_capture.ino's Rr placeholder.
const float A_NOMINAL_PLACEHOLDER = 1.29f;
const float RR_OHM_PLACEHOLDER = 1.0f;

volatile uint32_t lastSyncUs = 0;
volatile uint32_t prevPeriodUs = 0;
volatile bool havePeriod = false;

void IRAM_ATTR onSync() {
  uint32_t now = micros();
  if (lastSyncUs != 0) {
    prevPeriodUs = now - lastSyncUs;
    havePeriod = true;
  }
  lastSyncUs = now;
}

uint32_t t0us;
uint32_t sampleIndex = 0;

void setup() {
  Serial.begin(BAUD);
  delay(200);
  pinMode(SYNC_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(SYNC_PIN), onSync, RISING);

  Serial.println("# signature_capture ready (two-board mode: phase from measured sync period)");
  Serial.printf(
    "# vref=%.2f dac_bits=8 adc_bits=12 baud=%lu A_nominal_v=%.4f Rr_ohm_placeholder=%.4f\n",
    VREF, BAUD, A_NOMINAL_PLACEHOLDER, RR_OHM_PLACEHOLDER);
  Serial.println("index,t_us,phase_rad,adc_v_counts,adc_i_counts");

  t0us = micros();
}

void loop() {
  int adcV = analogRead(ADC_V_PIN);
  int adcI = analogRead(ADC_I_PIN);
  uint32_t tSampleUs = micros() - t0us;

  double phaseRad = -1.0;                  // sentinel: "not synced yet" (see header note)
  uint32_t syncUs = lastSyncUs;             // snapshot volatiles once (good enough for a demo
  uint32_t periodUs = prevPeriodUs;         // tool, not a hard real-time system — see README)
  if (havePeriod && periodUs > 0) {
    uint32_t sinceSyncUs = micros() - syncUs;
    double cyclePos = (double)sinceSyncUs / (double)periodUs;
    if (cyclePos >= 1.0) cyclePos = fmod(cyclePos, 1.0);   // sync pulse briefly overdue
    phaseRad = cyclePos * 2.0 * PI;
  }

  Serial.printf("%lu,%lu,%.4f,%d,%d\n", (unsigned long)sampleIndex, (unsigned long)tSampleUs,
                phaseRad, adcV, adcI);
  sampleIndex++;
}

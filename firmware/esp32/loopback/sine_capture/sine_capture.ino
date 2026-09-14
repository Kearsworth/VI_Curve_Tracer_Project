// sine_capture.ino
//
// Stage 3 of the DAC->ADC loopback (see ../../README.md and docs/ROADMAP.md Phase A).
// Builds on Stage 2 (loopback_check.ino, which only proved the wire + peripherals work
// with a slow ramp). This stage adds everything Stage 2 deliberately left out: a real
// sine drive, timed sampling, a phase reference, and a serial frame close to the raw
// dict shape in docs/DATA_CONTRACT.md §1 / §7.
//
// Wiring: same as Stage 2 — one jumper wire, GPIO25 (DAC1 out) -> GPIO34 (ADC1_CH6 in).
// GND already shared on-board between the DAC and ADC circuitry.
//
// Board: ESP32 DevKit V1 (DOIT ESP32 DEVKIT V1 in Arduino IDE / arduino-cli board menu).
//
// What's still fake here (by design, not oversight): there is no real circuit + DUT yet,
// and no real sense resistor, so "V" and "I" are read from the SAME physical loopback
// point (GPIO34). ADC_I_PIN is a separate macro for exactly one reason: once the real
// circuit exists, pointing it at the real sense-resistor channel (e.g. GPIO35) is meant
// to be a one-line change, not a rewrite.

#include <math.h>

// ---------- Pins ----------
const int DAC_PIN   = 25;          // DAC1
const int ADC_V_PIN = 34;          // ADC1_CH6, input-only pin — voltage across DUT (loopback: driven point)
const int ADC_I_PIN = ADC_V_PIN;   // TODO Stage 4: point at the real sense-resistor channel (e.g. GPIO35)
                                    // once the circuit + Rr exist. Until then this reads the same node as V.

// ---------- Drive + sampling design (see firmware/esp32/README.md "Things to decide") ----------
// Drive frequency: chosen low (50 Hz, not the ~1kHz the final system targets) because this
// sketch samples both channels with plain blocking analogRead() calls, and Stage 3's job is
// to prove the sine + timing + framing mechanism works at all, not to hit production speed.
// analogRead() alone costs roughly 100us on this core; two reads plus a serial print at a
// modest frequency comfortably keeps dozens of raw samples per drive cycle, which is what
// matters — CLAUDE.md's ablation shows accuracy is flat from ~30 to 720 RESAMPLED points, so
// calibrate.py's 360-point interpolation does not need a very high raw sample count per cycle.
// Reaching 1kHz for real will need continuous/DMA ADC sampling — a Stage 4+ concern, not this one.
const double DRIVE_FREQ_HZ = 50.0;

// DAC sine lookup table resolution (how finely the OUTPUT waveform steps through one cycle).
// This is independent of how many samples we manage to READ per cycle.
const int LUT_SIZE = 100;
uint8_t sineLUT[LUT_SIZE];

// DAC is 8-bit, 0-255, centered at 128. Amplitude is deliberately kept well inside the full
// range (not 0-255) because Stage 2 measured real nonlinearity growing worse near the DAC's
// extremes (adc_counts ≈ 16.0*dac_value - 231 in the mid-range, with compression at the top
// and a knee near the bottom) — staying at 28..228 avoids driving straight into the worst of
// that curve. The exact transfer function still isn't perfectly linear even here; that's
// expected and is a calibration problem for the PC side (calibrate.py), not something to
// chase away in firmware.
const int DAC_CENTER = 128;
const int DAC_AMPLITUDE_COUNTS = 100;   // dacValue swings 28..228

// Nominal/uncalibrated drive amplitude in volts, using the textbook (not measured) DAC
// transfer function. This travels with the capture as "A" per DATA_CONTRACT.md §1, but is
// explicitly NOT the calibrated value — see firmware/esp32/README.md Stage 2 result note.
const float VREF = 3.3f;
const float A_NOMINAL_VOLTS = DAC_AMPLITUDE_COUNTS * (VREF / 255.0f);

// No real sense resistor exists yet (loopback only). Rr is a placeholder so the printed
// meta line already carries the field DATA_CONTRACT.md §1 requires; replace with the real
// value once the circuit exists.
const float RR_OHMS_PLACEHOLDER = 1.0f;   // TODO Stage 4: real sense resistor value

// Serial baud: bumped up from Stage 2's 115200. At 115200 baud, printing one CSV line takes
// long enough (~2.6ms for a ~30-byte line) that it becomes the bottleneck, not analogRead(),
// and starves samples-per-cycle at any reasonable drive frequency. 921600 was already proven
// reliable on this exact board/adapter during `arduino-cli upload` (esptool negotiates up to
// that rate for flashing), so reusing it here for the data stream is a safe choice — just
// remember to set the PC-side monitor to match.
const unsigned long BAUD = 921600;

uint32_t sampleIndex = 0;
uint32_t t0us = 0;

void setup() {
  Serial.begin(BAUD);
  delay(200);

  for (int i = 0; i < LUT_SIZE; i++) {
    float angle = 2.0f * PI * i / LUT_SIZE;
    int v = DAC_CENTER + (int)roundf(DAC_AMPLITUDE_COUNTS * sinf(angle));
    sineLUT[i] = (uint8_t)constrain(v, 0, 255);
  }

  Serial.println("# sine_capture Stage 3 ready");
  Serial.printf(
    "# drive_freq_hz=%.3f lut_size=%d dac_center=%d dac_amplitude_counts=%d "
    "A_nominal_v=%.4f Rr_ohm_placeholder=%.4f vref=%.2f dac_bits=8 adc_bits=12 baud=%lu\n",
    DRIVE_FREQ_HZ, LUT_SIZE, DAC_CENTER, DAC_AMPLITUDE_COUNTS,
    A_NOMINAL_VOLTS, RR_OHMS_PLACEHOLDER, VREF, BAUD
  );
  Serial.println("index,t_us,phase_rad,adc_v_counts,adc_i_counts");

  t0us = micros();
}

void loop() {
  // Free-running: no fixed-interval busy-wait. Phase is computed from the ACTUAL elapsed
  // time of each sample (not an assumed constant dt), so jitter from analogRead()/Serial
  // timing variance doesn't corrupt the phase label — it just shows up as slightly uneven
  // spacing in raw samples, which calibrate.py already tolerates (DATA_CONTRACT.md §1: "M
  // may vary between captures — that's fine, calibration fixes it").
  uint32_t now = micros();
  uint32_t elapsed = now - t0us;   // unsigned subtraction handles micros() rollover correctly

  double cyclePos = fmod((double)elapsed * DRIVE_FREQ_HZ / 1e6, 1.0);   // 0..1 fraction of a cycle
  int lutIndex = (int)(cyclePos * LUT_SIZE) % LUT_SIZE;

  dacWrite(DAC_PIN, sineLUT[lutIndex]);

  int adcV = analogRead(ADC_V_PIN);
  int adcI = analogRead(ADC_I_PIN);

  uint32_t tSampleUs = micros() - t0us;
  double phaseRad = cyclePos * 2.0 * PI;

  Serial.printf("%lu,%lu,%.4f,%d,%d\n", (unsigned long)sampleIndex, (unsigned long)tSampleUs, phaseRad, adcV, adcI);

  sampleIndex++;
}

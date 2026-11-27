// case1_frontend_mf.ino — Case 1 front end with a selectable drive frequency (1 kHz .. 1 Hz)
//
// Same circuit, wiring, serial frame and burst/pacing behaviour as ../case1_frontend_1k (which
// stays as the fallback); at the default 1 kHz the output is the same. Convert with
// hardware/reader.py --frontend --rr <ohm>; hardware/autorange.py picks frequency and Rr.
//
// Why (2026-11-27): one frequency can't show every capacitor. A loop is readable when |Z| is
// near Rr: 0.1 uF wants ~1 kHz with Rr 1k, 100 uF wants ~10 Hz with Rr 220, 1000 uF ~1 Hz.
// vi_ml/synth.py trains with this auto-range (TEST_FREQS_HZ x RR_OPTIONS).
//
// How:
//   - The ADC runs in continuous (DMA) mode at a FIXED 100k conversions/s, GPIO34 (V, node A)
//     and GPIO35 (I, node B) alternating = 50k (V, I) pairs/s.
//   - The drive frequency is 1000/M Hz (M = 1..1000) and every output point averages M pairs,
//     so every frequency gives exactly 50 points per cycle, phase-locked (same 50 phases every
//     cycle), and low frequencies average more (noise down ~sqrt(M)).
//   - V is averaged with half weights on the first and last sample (V0/2 + V1 + .. + V(M-1) +
//     VM/2), so its mean sample time equals the I samples' mean time: the 10 us V->I gap cancels
//     at every M (M = 1 is the old "V interpolated to the I sample" of case1_frontend_1k).
//   - Each point is labelled with the phase of that mean time on the shared esp_timer clock
//     (CLAUDE.md design decision #2); reader.frontend_to_raw then aligns the labels to node A.
//   - The drive task (core 0) reads the period from one 32-bit variable, so a frequency change
//     is atomic; the first SETTLE_CYCLES cycles after a change (and after boot) aren't captured,
//     so the circuit (e.g. a big C charging through Rr) can settle.
//
// Offset reference (added 2026-11-27): the node offsets wander by up to ~0.25 V within minutes,
// both channels alike (likely the ESP32 3V3 feeding the dividers; the ADC reads against its own
// reference). A third divider, identical to the return-path ones but with its input at GND,
// sits on GPIO32 (ADC1_CH4). After every burst the ADC is switched to that one channel for
// REF_SAMPLES conversions (~20 ms), then back to V/I — the V/I pattern and timing are
// untouched. The mean goes out as `ref_counts=` on the `# burst=` line; reader.py subtracts its
// move since the zero capture from both channels' offsets (reader.ref_corrected).
//
// Serial commands (send a line, e.g. from autorange.py; Arduino serial monitor works too):
//   f <hz>      drive frequency; snapped to 1000/M Hz, M = round(1000/hz) in 1..1000
//   n <cycles>  whole cycles printed per burst (1..32)
// Each command is answered with "# ok ..."; the next burst's meta line carries the new
// drive_freq_hz / decim / burst_cycles. A reset returns to 1 kHz, 32 cycles.
//
// Board: ESP32 DevKit V1 (DOIT ESP32 DEVKIT V1), arduino-esp32 core 3.x (ESP-IDF 5 drivers).

#include <math.h>
#include "esp_timer.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"

// ---------- Pins ----------
const int DAC_PIN = 25;                         // DAC1
const adc_channel_t ADC_V_CH = ADC_CHANNEL_6;   // GPIO34 — P1, node A via follower C
const adc_channel_t ADC_I_CH = ADC_CHANNEL_7;   // GPIO35 — P2, node B via follower D
const adc_channel_t ADC_REF_CH = ADC_CHANNEL_4; // GPIO32 — reference divider, input at GND
const int REF_SAMPLES = 2000;                   // ~20 ms of the reference after every burst

// ---------- Drive ----------
const int LUT_SIZE = 100;
uint8_t sineLUT[LUT_SIZE];
const int DAC_CENTER = 132;                     // same trim as the other Case 1 sketches
const int DAC_AMPLITUDE_COUNTS = 63;            // measured A ~4.66 V at node A
const float VREF = 3.3f;
const float FRONTEND_GAIN = 5.92f;              // measured, docs/CASE1_WIRING.md step 4
const float A_NOMINAL_VOLTS = DAC_AMPLITUDE_COUNTS * (VREF / 255.0f) * FRONTEND_GAIN;   // reader.py measures the real A
const float RR_OHMS_PLACEHOLDER = 1000.0f;      // pass --rr for the Rr actually connected
const unsigned long BAUD = 921600;
const float MV_TO_COUNTS = 4095.0f / 3300.0f;

// ---------- Frequency / capture ----------
const uint32_t ADC_SAMPLE_HZ = 100000;          // fixed: 50k (V, I) pairs/s
const int POINTS_PER_CYCLE = 50;
const int M_MAX = 1000;                         // 1 Hz
const int MAX_CYCLES = 32;
const int SETTLE_CYCLES = 2;
const uint32_t BURST_GAP_MS = 500;              // idle line between bursts (serial pacing, see _1k)
const uint32_t FRAME_BYTES = 1024;
const int ENTRIES_PER_FRAME = FRAME_BYTES / SOC_ADC_DIGI_RESULT_BYTES;
const int MAX_POINTS = (MAX_CYCLES + 2) * POINTS_PER_CYCLE + 1;
const int MAX_FRAMES = 256;
const int T0_FRAMES = 64;                       // frames averaged for the burst's time offset

volatile int32_t periodUs = 1000;               // 1000 * M; read by the drive task (atomic 32-bit)
int decim = 1;                                  // M
int burstCycles = 32;
bool settlePending = true;

adc_continuous_handle_t adcHandle = nullptr;
static adc_digi_pattern_config_t patVI[2], patRef[1];     // kept alive: the driver may point at them
static adc_continuous_config_t cfgVI = {}, cfgRef = {};
adc_cali_handle_t caliHandle = nullptr;
bool caliOk = false;
// raw -> mV for every raw value. The eFuse calibration is NOT a straight line at 12 dB on the
// ESP32 (a two-point line read node A ~7 % low, 2026-11-27), so tabulate it once and
// interpolate the averaged (sub-count) raw values.
static uint16_t mvTable[4096];

static uint8_t rawBuf[FRAME_BYTES];
static adc_continuous_data_t parsed[ENTRIES_PER_FRAME];
static float vAvg[MAX_POINTS], iAvg[MAX_POINTS];          // raw counts, averaged per point

volatile int frameCount = 0;
volatile int64_t frameT[MAX_FRAMES];
volatile bool poolOverflow = false;

double usPerConv = 1e6 / ADC_SAMPLE_HZ;         // measured in setup()
int convPerFrame = ENTRIES_PER_FRAME;

volatile int64_t t0us = 0;                      // written once in setup(), before the drive task
volatile bool driveRunning = false;
const BaseType_t DRIVE_CORE = 0;

void driveTask(void *) {
  int lastIndex = -1;
  for (;;) {
    int32_t p = periodUs;                       // one atomic read per pass
    int64_t e = (esp_timer_get_time() - t0us) % p;
    int idx = (int)(e * LUT_SIZE / p);
    if (idx != lastIndex) {
      dacWrite(DAC_PIN, sineLUT[idx]);
      lastIndex = idx;
      driveRunning = true;
    }
  }
}

static bool IRAM_ATTR onFrameDone(adc_continuous_handle_t, const adc_continuous_evt_data_t *, void *) {
  int k = frameCount;
  if (k < MAX_FRAMES) frameT[k] = esp_timer_get_time();
  frameCount = k + 1;
  return false;
}

static bool IRAM_ATTR onPoolOvf(adc_continuous_handle_t, const adc_continuous_evt_data_t *, void *) {
  poolOverflow = true;
  return false;
}

static void adcSetup() {
  adc_continuous_handle_cfg_t hcfg = {};
  hcfg.max_store_buf_size = 16384;
  hcfg.conv_frame_size = FRAME_BYTES;
  ESP_ERROR_CHECK(adc_continuous_new_handle(&hcfg, &adcHandle));

  const adc_channel_t viCh[2] = {ADC_V_CH, ADC_I_CH};
  for (int k = 0; k < 2; k++) {
    patVI[k].atten = ADC_ATTEN_DB_12; patVI[k].channel = viCh[k]; patVI[k].unit = ADC_UNIT_1; patVI[k].bit_width = ADC_BITWIDTH_12;
  }
  patRef[0] = patVI[0];
  patRef[0].channel = ADC_REF_CH;
  cfgVI.pattern_num = 2;
  cfgVI.adc_pattern = patVI;
  cfgVI.sample_freq_hz = ADC_SAMPLE_HZ;
  cfgVI.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  cfgVI.format = ADC_DIGI_OUTPUT_FORMAT_TYPE1;
  cfgRef = cfgVI;
  cfgRef.pattern_num = 1;
  cfgRef.adc_pattern = patRef;
  ESP_ERROR_CHECK(adc_continuous_config(adcHandle, &cfgVI));

  adc_continuous_evt_cbs_t cbs = {};
  cbs.on_conv_done = onFrameDone;
  cbs.on_pool_ovf = onPoolOvf;
  ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(adcHandle, &cbs, nullptr));

  adc_cali_line_fitting_config_t ccfg = {};
  ccfg.unit_id = ADC_UNIT_1;
  ccfg.atten = ADC_ATTEN_DB_12;
  ccfg.bitwidth = ADC_BITWIDTH_12;
  ccfg.default_vref = 1100;
  caliOk = adc_cali_create_scheme_line_fitting(&ccfg, &caliHandle) == ESP_OK;
  for (int r = 0; r < 4096; r++) {
    int mv = 0;
    if (!(caliOk && adc_cali_raw_to_voltage(caliHandle, r, &mv) == ESP_OK)) mv = (int)lroundf(r * 3300.0f / 4095.0f);
    mvTable[r] = (uint16_t)constrain(mv, 0, 65535);
  }
}

static inline float countsF(float raw) {           // calibrated, on the ideal 3.3 V / 4095 scale
  raw = constrain(raw, 0.0f, 4095.0f);
  int r0 = min((int)raw, 4094);
  float mv = mvTable[r0] + (raw - r0) * (mvTable[r0 + 1] - mvTable[r0]);
  return mv * MV_TO_COUNTS;
}

static inline int countsFromRaw(float raw) {
  return constrain((int)lroundf(countsF(raw)), 0, 4095);
}

// Mean raw reading of the reference divider: a short DMA run on GPIO32 alone, then the V/I
// pattern is restored. Returns -1 if no valid sample came back (e.g. the pattern switch failed).
static float readRefRaw() {
  if (adc_continuous_config(adcHandle, &cfgRef) != ESP_OK) return -1.0f;
  adc_continuous_flush_pool(adcHandle);
  float result = -1.0f;
  if (adc_continuous_start(adcHandle) == ESP_OK) {
    int64_t sum = 0;
    int n = 0, tries = 0;
    while (n < REF_SAMPLES && tries < 20) {
      uint32_t got = 0, cnt = 0;
      if (adc_continuous_read(adcHandle, rawBuf, FRAME_BYTES, &got, 200) != ESP_OK) { tries++; continue; }
      if (adc_continuous_parse_data(adcHandle, rawBuf, got, parsed, &cnt) != ESP_OK) { tries++; continue; }
      for (uint32_t e = 0; e < cnt && n < REF_SAMPLES; e++)
        if (parsed[e].valid && parsed[e].channel == ADC_REF_CH) { sum += parsed[e].raw_data; n++; }
    }
    adc_continuous_stop(adcHandle);
    if (n) result = (float)sum / n;
  }
  ESP_ERROR_CHECK(adc_continuous_config(adcHandle, &cfgVI));
  return result;
}

// setup(): the real conversion period, from ISR timestamps over MAX_FRAMES frames (~1.3 s).
static void measureAdcTiming() {
  frameCount = 0;
  adc_continuous_flush_pool(adcHandle);
  ESP_ERROR_CHECK(adc_continuous_start(adcHandle));
  int64_t tEnd = esp_timer_get_time() + 5000000;
  while (frameCount < MAX_FRAMES && esp_timer_get_time() < tEnd) {
    uint32_t n = 0;
    adc_continuous_read(adcHandle, rawBuf, FRAME_BYTES, &n, 200);
  }
  adc_continuous_stop(adcHandle);
  int k1 = min((int)frameCount, MAX_FRAMES) - 1;
  if (k1 >= 2) usPerConv = (double)(frameT[k1] - frameT[1]) / ((double)(k1 - 1) * convPerFrame);
}

// One burst: average M pairs per point (trapezoid on V) until `need` points are stored.
// Returns the point count; tConv0 = time of conversion 0 of the burst.
static int capturePoints(int need, double &tConv0, int &resyncs, int &timeouts) {
  const int M = decim;
  frameCount = 0;
  poolOverflow = false;
  resyncs = timeouts = 0;
  adc_continuous_flush_pool(adcHandle);
  ESP_ERROR_CHECK(adc_continuous_start(adcHandle));

  int nPoints = 0, k = 0;
  int32_t sum2V = 0, sumI = 0;                  // 2 x trapezoid sum of V, plain sum of I
  long pairs = 0;
  bool havePending = false;
  adc_continuous_data_t pending = {};
  while (nPoints < need && timeouts < 5) {
    uint32_t n = 0, got = 0;
    if (adc_continuous_read(adcHandle, rawBuf, FRAME_BYTES, &n, 1000) != ESP_OK) { timeouts++; continue; }
    if (adc_continuous_parse_data(adcHandle, rawBuf, n, parsed, &got) != ESP_OK) continue;
    for (uint32_t e = 0; e < got && nPoints < need; e++) {
      if (!parsed[e].valid) continue;
      if (!havePending) { pending = parsed[e]; havePending = true; continue; }
      const adc_continuous_data_t &a = pending, &b = parsed[e];
      int v, i;
      // The pattern converts V then I; the DMA may hand each pair over swapped, so go by channel.
      if (a.channel == ADC_V_CH && b.channel == ADC_I_CH) { v = a.raw_data; i = b.raw_data; }
      else if (a.channel == ADC_I_CH && b.channel == ADC_V_CH) { v = b.raw_data; i = a.raw_data; }
      else { pending = b; resyncs++; continue; }          // out of step: drop one entry
      havePending = false;

      if (pairs == 0) { sum2V = v; sumI = i; k = 1; }
      else if (k == M) {                                  // this pair opens the next point
        sum2V += v;                                       // closing half-weight V
        vAvg[nPoints] = sum2V / (2.0f * M);
        iAvg[nPoints] = sumI / (float)M;
        nPoints++;
        sum2V = v; sumI = i; k = 1;
      } else { sum2V += 2 * v; sumI += i; k++; }
      pairs++;
    }
  }
  adc_continuous_stop(adcHandle);

  int nf = min(min((int)frameCount, MAX_FRAMES), T0_FRAMES);
  double sumA = 0;
  for (int f = 0; f < nf; f++) sumA += (double)frameT[f] - usPerConv * ((double)(f + 1) * convPerFrame - 1);
  tConv0 = nf ? sumA / nf : (double)esp_timer_get_time();
  return nPoints;
}

static uint32_t lineIndex = 0;
static uint32_t burstNo = 0;

static double driveFreqHz() { return 1e6 / (double)periodUs; }

static void printMeta() {
  Serial.printf(
    "# drive_freq_hz=%.4f lut_size=%d dac_center=%d dac_amplitude_counts=%d "
    "A_nominal_v=%.4f Rr_ohm_placeholder=%.4f vref=%.2f dac_bits=8 adc_bits=12 baud=%lu "
    "drive_core=%d capture_core=%d frontend_case=1 dac_inverted=1 adc_read=dma_cali%d "
    "adc_sample_hz=%lu adc_us_per_conv=%.4f decim=%d points_per_cycle=%d burst_cycles=%d "
    "vi_align=trapezoid lut_mid_step=1 ref_gpio=32 index_wrap=10000 t_us_wrap=100000\n",
    driveFreqHz(), LUT_SIZE, DAC_CENTER, DAC_AMPLITUDE_COUNTS,
    A_NOMINAL_VOLTS, RR_OHMS_PLACEHOLDER, VREF, BAUD,
    (int)DRIVE_CORE, (int)xPortGetCoreID(), caliOk ? 1 : 0,
    (unsigned long)ADC_SAMPLE_HZ, usPerConv, decim, POINTS_PER_CYCLE, burstCycles);
}

static void runCommand(char *s) {
  while (*s == ' ') s++;
  if (s[0] == 'f') {
    double hz = atof(s + 1);
    if (hz > 0) {
      decim = constrain((int)lround(1000.0 / hz), 1, M_MAX);
      periodUs = 1000 * decim;                  // atomic for the drive task
      settlePending = true;
    }
  } else if (s[0] == 'n') {
    int n = atoi(s + 1);
    if (n > 0) burstCycles = constrain(n, 1, MAX_CYCLES);
  } else if (s[0] != '?') {
    Serial.printf("# error unknown command '%s' (use: f <hz> | n <cycles> | ?)\n", s);
    return;
  }
  Serial.printf("# ok cmd='%s' freq_hz=%.4f decim=%d burst_cycles=%d\n", s, driveFreqHz(), decim, burstCycles);
}

static void pollCommands() {
  static char buf[40];
  static int len = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (len) { buf[len] = 0; runCommand(buf); len = 0; }
    } else if (c >= 0x20 && c < 0x7f && len < (int)sizeof(buf) - 1) {   // drop line noise (0xFF at boot)
      buf[len++] = c;
    }
  }
}

void setup() {
  Serial.setTxBufferSize(4096);
  Serial.begin(BAUD);
  delay(200);

  for (int i = 0; i < LUT_SIZE; i++) {
    float angle = 2.0f * PI * (i + 0.5f) / LUT_SIZE;   // value at the step's middle
    int v = DAC_CENTER - (int)roundf(DAC_AMPLITUDE_COUNTS * sinf(angle));   // minus: channel A inverts
    sineLUT[i] = (uint8_t)constrain(v, 0, 255);
  }

  adcSetup();
  measureAdcTiming();

  t0us = esp_timer_get_time();
  disableCore0WDT();
  xTaskCreatePinnedToCore(driveTask, "driveTask", 4096, nullptr, configMAX_PRIORITIES - 1, nullptr, DRIVE_CORE);
  while (!driveRunning) { delay(1); }

  Serial.println("# case1_frontend_mf ready");
  printMeta();
  Serial.println("index,t_us,phase_rad,adc_v_counts,adc_i_counts");
}

void loop() {
  pollCommands();
  if (settlePending) {                          // let the circuit settle at the new frequency
    uint32_t ms = (uint32_t)((int64_t)SETTLE_CYCLES * periodUs / 1000);
    delay(max(ms, (uint32_t)50));
    settlePending = false;
    pollCommands();
    if (settlePending) return;                  // changed again meanwhile: settle again
  }

  const int need = (burstCycles + 2) * POINTS_PER_CYCLE + 1;   // margin to trim to whole cycles
  double tConv0 = 0;
  int resyncs = 0, timeouts = 0;
  int n = capturePoints(need, tConv0, resyncs, timeouts);
  float refRaw = readRefRaw();                  // right after the burst, before the slow printing

  printMeta();                                  // meta BEFORE the data (readers start here)
  const int M = decim;
  const double period = (double)periodUs;
  int printed = 0, wraps = 0;
  double lastPhase = -1;
  bool started = false;
  for (int j = 0; j < n; j++) {
    double tUs = tConv0 + usPerConv * (2.0 * j * M + M);       // mean time of point j's samples
    double rel = tUs - (double)t0us;
    double phase = fmod(rel, period) / period * 2.0 * PI;
    if (lastPhase >= 0 && lastPhase - phase > PI) {
      wraps++;
      if (!started) started = true;
      else if (wraps > burstCycles) break;
    }
    lastPhase = phase;
    if (!started) continue;

    uint32_t ph4 = (uint32_t)lround(phase * 10000.0);
    char buf[40];
    int len = snprintf(buf, sizeof buf, "%lu,%lu,%lu.%04lu,%d,%d\n",
                       (unsigned long)(lineIndex % 10000), (unsigned long)fmod(rel, 100000.0),
                       (unsigned long)(ph4 / 10000), (unsigned long)(ph4 % 10000),
                       countsFromRaw(vAvg[j]), countsFromRaw(iAvg[j]));
    Serial.write((const uint8_t *)buf, len);
    lineIndex++;
    printed++;
  }
  Serial.printf("# burst=%lu lines=%d cycles=%d points=%d decim=%d resyncs=%d timeouts=%d ovf=%d",
                (unsigned long)burstNo++, printed, wraps > 0 ? wraps - 1 : 0, n, M,
                resyncs, timeouts, poolOverflow ? 1 : 0);
  if (refRaw >= 0) Serial.printf(" ref_counts=%.2f", countsF(refRaw));
  Serial.print("\n");
  uint32_t t = millis();
  while (millis() - t < BURST_GAP_MS) { pollCommands(); delay(5); }
}

// case1_frontend_1k.ino
//
// Case 1 front end at a 1 kHz drive (the frequency vi_ml/synth.py trains at, F = 1000 Hz).
// Same circuit, wiring and serial frame as ../case1_frontend (50 Hz); that sketch stays as the
// known-good fallback. Convert with: hardware/reader.py --frontend --rr <ohm> (unchanged).
//
// Why a new sketch (2026-11-27): at 50 Hz a 100 nF cap reads almost open and a 100 mH coil
// almost short (X = 31.8 kOhm / 31 Ohm vs Rr ~1k), so real C/L loops look nothing like synth's
// 1 kHz ones; and 50 Hz is the mains frequency, so hum lands on the drive bin and never
// averages out. analogRead() (~42 us/read) gives only ~5 points per 1 kHz cycle, hence:
//
//   Core 0 — driveTask: sine LUT -> dacWrite(GPIO25), index from the shared esp_timer clock
//            (integer microseconds: 1 kHz = 1000 us per cycle, 10 us per LUT step).
//   Core 1 — loop(): BURST capture with the ADC in continuous (DMA) mode, GPIO34/35
//            alternating at ADC_SAMPLE_HZ conversions/s, then print the burst as the usual CSV.
//            The UART (921600) can't stream 50k lines/s, so capture first, send after.
//
// Timing / phase (same principle as the 50 Hz sketch: phase from the shared hardware clock,
// never from geometry, CLAUDE.md design decision #2):
//   - setup() measures the real conversion period (us/conversion) over ~0.5 s from the DMA
//     "frame done" interrupt timestamps.
//   - each burst records an esp_timer timestamp per DMA frame (in the ISR); sample n's time is
//     offset + period * n, with the offset averaged over the burst's frames.
//   - V and I are converted alternately, 1/ADC_SAMPLE_HZ apart (10 us = 3.6 deg at 1 kHz). Each
//     output line is labelled at the I sample's time and carries V linearly interpolated to that
//     same time, so this skew cancels (the DMA version of the 50 Hz sketch's V-I-V trick).
//   - Any remaining constant delay (ISR latency, RC filter mismatch between C5/C6) shows up as
//     a small V-I phase on a plain resistor; measure it and correct (phase-cal), don't guess.
//   - The LUT holds sin() at each 10 us step's MIDDLE, so the zero-order-hold DAC output is not
//     half a step (1.8 deg) late against the phase label.
//
// ADC values: raw -> mV with the chip's eFuse line-fitting calibration, then printed as counts
// on the ideal vref/4095 scale (round(mV * 4095 / 3300)), same convention as the 50 Hz sketch,
// so reader.py and zero-cal work unchanged. Zero-cal must be redone for this sketch.
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

// ---------- Drive ----------
const int64_t DRIVE_PERIOD_US = 1000;           // 1 kHz exactly on the esp_timer clock
const double DRIVE_FREQ_HZ = 1e6 / DRIVE_PERIOD_US;
const int LUT_SIZE = 100;                       // 10 us per step
uint8_t sineLUT[LUT_SIZE];
const int DAC_CENTER = 132;                     // same trim as the 50 Hz sketch (2026-11-26)
const int DAC_AMPLITUDE_COUNTS = 63;            // same as the 50 Hz sketch: measured A ~4.5 V

const float VREF = 3.3f;
const float FRONTEND_GAIN = 5.92f;              // measured, docs/CASE1_WIRING.md step 4
const float A_NOMINAL_VOLTS = DAC_AMPLITUDE_COUNTS * (VREF / 255.0f) * FRONTEND_GAIN;   // reader.py measures the real A
const float RR_OHMS_PLACEHOLDER = 1000.0f;      // pass --rr for the Rr actually connected
const unsigned long BAUD = 921600;
const float MV_TO_COUNTS = 4095.0f / 3300.0f;

// ---------- ADC continuous (DMA) ----------
const uint32_t ADC_SAMPLE_HZ = 100000;          // conversions/s over both channels -> 50 per channel per cycle
const int BURST_CYCLES = 32;                    // whole drive cycles printed per burst
const uint32_t FRAME_BYTES = 1024;              // DMA frame (multiple of SOC_ADC_DIGI_DATA_BYTES_PER_CONV)
const int CONV_PER_CYCLE = (int)(ADC_SAMPLE_HZ / DRIVE_FREQ_HZ);       // 100 (V+I)
const int NEED_CONV = (BURST_CYCLES + 3) * CONV_PER_CYCLE;             // margin to trim to whole cycles
const int MAX_FRAMES = 256;                     // ISR timestamp slots (setup() uses all; a burst ~8)

adc_continuous_handle_t adcHandle = nullptr;
adc_cali_handle_t caliHandle = nullptr;
bool caliOk = false;

static uint8_t rawBuf[16384];                   // one burst of DMA bytes
static uint8_t sampleCh[8192];                  // parsed: channel per conversion
static uint16_t sampleRaw[8192];                // parsed: 12-bit raw per conversion
static_assert(NEED_CONV <= 8192, "burst too long for the parse buffers");

volatile int frameCount = 0;
volatile int64_t frameT[MAX_FRAMES];
volatile bool poolOverflow = false;

double usPerConv = 1e6 / ADC_SAMPLE_HZ;         // measured in setup()
int convPerFrame = 0;                           // measured in setup()
int bytesPerConv = 0;

// ---------- Shared state ----------
volatile int64_t t0us = 0;
volatile bool driveRunning = false;
const BaseType_t DRIVE_CORE = 0;

void driveTask(void *) {
  int lastIndex = -1;
  for (;;) {
    int64_t e = (esp_timer_get_time() - t0us) % DRIVE_PERIOD_US;
    int idx = (int)(e * LUT_SIZE / DRIVE_PERIOD_US);
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

  adc_digi_pattern_config_t pat[2] = {};
  pat[0].atten = ADC_ATTEN_DB_12; pat[0].channel = ADC_V_CH; pat[0].unit = ADC_UNIT_1; pat[0].bit_width = ADC_BITWIDTH_12;
  pat[1].atten = ADC_ATTEN_DB_12; pat[1].channel = ADC_I_CH; pat[1].unit = ADC_UNIT_1; pat[1].bit_width = ADC_BITWIDTH_12;
  adc_continuous_config_t cfg = {};
  cfg.pattern_num = 2;
  cfg.adc_pattern = pat;
  cfg.sample_freq_hz = ADC_SAMPLE_HZ;
  cfg.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  cfg.format = ADC_DIGI_OUTPUT_FORMAT_TYPE1;
  ESP_ERROR_CHECK(adc_continuous_config(adcHandle, &cfg));

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
}

// Parse DMA bytes into (channel, raw) per conversion, in buffer order. Returns the count.
static int parseBurst(const uint8_t *buf, uint32_t len, int maxOut) {
  int n = 0;
  adc_continuous_data_t tmp[64];
  const uint32_t step = 64 * SOC_ADC_DIGI_RESULT_BYTES;
  for (uint32_t off = 0; off < len && n < maxOut; off += step) {
    uint32_t chunk = min(step, len - off), got = 0;
    if (adc_continuous_parse_data(adcHandle, buf + off, chunk, tmp, &got) != ESP_OK) break;
    for (uint32_t k = 0; k < got && n < maxOut; k++) {
      if (!tmp[k].valid) continue;
      sampleCh[n] = (uint8_t)tmp[k].channel;
      sampleRaw[n] = (uint16_t)tmp[k].raw_data;
      n++;
    }
  }
  return n;
}

// Read DMA bytes until `needBytes` arrived. Frame timestamps land in frameT[] via the ISR.
static uint32_t captureBytes(uint32_t needBytes) {
  frameCount = 0;
  poolOverflow = false;
  adc_continuous_flush_pool(adcHandle);
  ESP_ERROR_CHECK(adc_continuous_start(adcHandle));
  uint32_t got = 0;
  while (got < needBytes) {
    uint32_t n = 0;
    uint32_t want = min((uint32_t)FRAME_BYTES, (uint32_t)sizeof(rawBuf) - got);
    if (want == 0) break;
    if (adc_continuous_read(adcHandle, rawBuf + got, want, &n, 200) == ESP_OK) got += n;
  }
  adc_continuous_stop(adcHandle);
  return got;
}

static int rawToMv(int raw) {
  int mv = 0;
  if (caliOk && adc_cali_raw_to_voltage(caliHandle, raw, &mv) == ESP_OK) return mv;
  return (int)lroundf(raw * 3300.0f / 4095.0f);
}

static inline int mvToCounts(float mv) {
  return constrain((int)lroundf(mv * MV_TO_COUNTS), 0, 4095);
}

// setup(): bytes per conversion, conversions per frame, and the real conversion period.
static void measureAdcTiming() {
  uint32_t got = captureBytes(4 * FRAME_BYTES);
  int nConv = parseBurst(rawBuf, got, 8192);
  bytesPerConv = nConv > 0 ? (int)lroundf((float)got / nConv) : SOC_ADC_DIGI_RESULT_BYTES;
  convPerFrame = FRAME_BYTES / bytesPerConv;

  // MAX_FRAMES frames (~1.3 s), data thrown away; period from the first/last ISR stamps.
  frameCount = 0;
  poolOverflow = false;
  adc_continuous_flush_pool(adcHandle);
  ESP_ERROR_CHECK(adc_continuous_start(adcHandle));
  int64_t tEnd = esp_timer_get_time() + 5000000;
  while (frameCount < MAX_FRAMES && esp_timer_get_time() < tEnd) {
    uint32_t n = 0;
    adc_continuous_read(adcHandle, rawBuf, FRAME_BYTES, &n, 200);
  }
  adc_continuous_stop(adcHandle);
  int k1 = min((int)frameCount, MAX_FRAMES) - 1;
  if (k1 >= 2 && convPerFrame > 0) {
    usPerConv = (double)(frameT[k1] - frameT[1]) / ((double)(k1 - 1) * convPerFrame);
  }
}

static uint32_t lineIndex = 0;
static uint32_t burstNo = 0;

static void printMeta() {
  Serial.printf(
    "# drive_freq_hz=%.3f lut_size=%d dac_center=%d dac_amplitude_counts=%d "
    "A_nominal_v=%.4f Rr_ohm_placeholder=%.4f vref=%.2f dac_bits=8 adc_bits=12 baud=%lu "
    "drive_core=%d capture_core=%d frontend_case=1 dac_inverted=1 adc_read=dma_cali%d "
    "adc_sample_hz=%lu adc_us_per_conv=%.4f conv_per_frame=%d bytes_per_conv=%d "
    "burst_cycles=%d vi_align=interp lut_mid_step=1 index_wrap=10000 t_us_wrap=100000\n",
    DRIVE_FREQ_HZ, LUT_SIZE, DAC_CENTER, DAC_AMPLITUDE_COUNTS,
    A_NOMINAL_VOLTS, RR_OHMS_PLACEHOLDER, VREF, BAUD,
    (int)DRIVE_CORE, (int)xPortGetCoreID(), caliOk ? 1 : 0,
    (unsigned long)ADC_SAMPLE_HZ, usPerConv, convPerFrame, bytesPerConv, BURST_CYCLES);
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
  delay(20);   // let the drive settle a few cycles

  Serial.println("# case1_frontend_1k ready");
  printMeta();
  Serial.println("index,t_us,phase_rad,adc_v_counts,adc_i_counts");
}

void loop() {
  uint32_t needBytes = (uint32_t)NEED_CONV * bytesPerConv;
  needBytes = min(needBytes, (uint32_t)sizeof(rawBuf));
  uint32_t got = captureBytes(needBytes);
  int nFrames = min((int)frameCount, MAX_FRAMES);
  int n = parseBurst(rawBuf, got, 8192);

  // Frame timestamps -> offset of conversion 0 (period fixed from setup()).
  int framesInData = min(nFrames, (int)(got / FRAME_BYTES));
  double sumA = 0, sumA2 = 0; int nA = 0;
  for (int k = 0; k < framesInData; k++) {
    double a = (double)frameT[k] - usPerConv * ((double)(k + 1) * convPerFrame - 1);
    sumA += a; sumA2 += a * a; nA++;
  }
  if (nA == 0 || n < 4) {
    Serial.printf("# burst_error frames=%d conv=%d bytes=%lu\n", nFrames, n, (unsigned long)got);
    delay(100);
    return;
  }
  double tConv0 = sumA / nA;
  double jitter = nA > 1 ? sqrt(fmax(0.0, sumA2 / nA - tConv0 * tConv0)) : 0.0;

  // The pattern converts V then I. If the buffer starts with I, DMA swapped each pair.
  bool swapped = sampleCh[0] == (uint8_t)ADC_I_CH;

  // Walk I samples; V at the I sample's time by linear interpolation between neighbouring Vs.
  // Conversion n (true order) happens at tConv0 + usPerConv * n.
  int printed = 0, wraps = 0;
  double lastPhase = -1;
  bool started = false;
  int prevV = -1;                // true index of the previous V conversion
  for (int t = 0; t < n; t++) {               // t = true conversion index
    int slot = swapped ? (t ^ 1) : t;         // buffer slot holding conversion t
    if (slot >= n) continue;
    if (sampleCh[slot] == (uint8_t)ADC_V_CH) { prevV = t; continue; }
    if (sampleCh[slot] != (uint8_t)ADC_I_CH || prevV < 0) continue;
    int nextV = t + 1;                        // pattern alternates, so the next V follows
    int nextSlot = swapped ? (nextV ^ 1) : nextV;
    if (nextSlot >= n) break;
    if (sampleCh[nextSlot] != (uint8_t)ADC_V_CH) continue;
    int prevSlot = swapped ? (prevV ^ 1) : prevV;

    float vPrev = rawToMv(sampleRaw[prevSlot]);
    float vNext = rawToMv(sampleRaw[nextSlot]);
    float w = (float)(t - prevV) / (float)(nextV - prevV);
    float vMv = vPrev + (vNext - vPrev) * w;
    float iMv = rawToMv(sampleRaw[slot]);

    double tUs = tConv0 + usPerConv * t;
    double rel = tUs - (double)t0us;
    double phase = fmod(rel, (double)DRIVE_PERIOD_US) / (double)DRIVE_PERIOD_US * 2.0 * PI;
    if (lastPhase >= 0 && lastPhase - phase > PI) {
      wraps++;
      if (!started) started = true;
      else if (wraps > BURST_CYCLES) break;
    }
    lastPhase = phase;
    if (!started) continue;

    uint32_t ph4 = (uint32_t)lround(phase * 10000.0);
    char buf[40];
    int len = snprintf(buf, sizeof buf, "%lu,%lu,%lu.%04lu,%d,%d\n",
                       (unsigned long)(lineIndex % 10000), (unsigned long)fmod(rel, 100000.0),
                       (unsigned long)(ph4 / 10000), (unsigned long)(ph4 % 10000),
                       mvToCounts(vMv), mvToCounts(iMv));
    Serial.write((const uint8_t *)buf, len);
    lineIndex++;
    printed++;
  }
  Serial.printf("# burst=%lu lines=%d cycles=%d frames=%d conv=%d swapped=%d ovf=%d t_jitter_us=%.2f\n",
                (unsigned long)burstNo++, printed, wraps > 0 ? wraps - 1 : 0, nFrames, n,
                swapped ? 1 : 0, poolOverflow ? 1 : 0, jitter);
  printMeta();
}

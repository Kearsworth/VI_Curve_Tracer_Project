// signature_gen.ino  — ESP32 #1 in the two-board bring-up
//
// A synthetic V-I SIGNATURE GENERATOR that stands in for the real circuit + DUT until
// Dr. Wathis's hardware is ready (see firmware/esp32/dual_board/README.md). Outputs V on
// DAC1 (GPIO25) and I on DAC2 (GPIO26), plus a sync pulse (GPIO27) once per cycle so ESP32 #2
// (signature_capture.ino) can derive phase from real elapsed time without generating the
// drive itself — see that sketch and docs/DATA_CONTRACT.md for why phase must come from a
// known reference, never be guessed from the waveform's shape (CLAUDE.md design decision #2).
//
// Shape select: send a single character over THIS board's own USB serial ('R', 'C'/'L', or
// 'D') to switch which signature is generated live, no reflash needed. Defaults to 'R' (a
// straight line) at boot.
//
// This does NOT reproduce real component physics — see vi_ml/synth.py for that (in Python,
// used to train the models). It only needs to trace a recognizable LINE / ELLIPSE / KNEE
// shape in the V-I plane, so the *hardware capture path* (two real, non-aliased ADC channels,
// inter-board sync, serial framing, hardware/reader.py, calibrate.py, features.py) can be
// exercised on real bytes over real USB — something today's simulated-frame tests can't do.

#include <math.h>

const int DAC_V_PIN = 25;   // DAC1 -> ESP32 #2's ADC_V_PIN (GPIO34)
const int DAC_I_PIN = 26;   // DAC2 -> ESP32 #2's ADC_I_PIN (GPIO35)
const int SYNC_PIN  = 27;   // pulses HIGH once per cycle -> ESP32 #2's SYNC_PIN (GPIO27)

// Same bring-up rate as sine_capture.ino's Stage 3, for the same reason (plain blocking
// dacWrite()/analogRead(), no DMA yet — see firmware/esp32/README.md).
const double FREQ_HZ = 50.0;
const int LUT_SIZE = 100;
const int CENTER = 128, AMPL = 100;        // DAC swings 28..228, same reasoning as sine_capture
const unsigned long SYNC_PULSE_US = 200;   // sync pulse width

uint8_t lutV[LUT_SIZE], lutI[LUT_SIZE];
char shape = 'R';

// Fills lutV/lutI for one full cycle (index 0..LUT_SIZE-1 = phase 0..2*pi) with a shape
// that traces the requested figure in the V-I plane. Not physically accurate — just
// recognizably a line / ellipse / knee, per the three shapes sketched for this plan.
void buildLUT(char s) {
  for (int i = 0; i < LUT_SIZE; i++) {
    float th = 2.0f * PI * i / LUT_SIZE;
    float v, ii;
    switch (s) {
      case 'C':
      case 'L':                              // ellipse: I is V's sine shifted 90 deg (Lissajous)
        v  = sinf(th);
        ii = sinf(th + PI / 2.0f);
        break;
      case 'D':                              // diode-like knee: sharp rise one half, flat other
        v  = sinf(th);
        ii = (v > 0) ? (expf(2.5f * v) - 1.0f) / (expf(2.5f) - 1.0f) : -0.05f;
        break;
      default:                               // 'R': straight line, I in phase with V
        v  = sinf(th);
        ii = 0.6f * v;
        break;
    }
    lutV[i] = (uint8_t)constrain((int)roundf(CENTER + AMPL * v), 0, 255);
    lutI[i] = (uint8_t)constrain((int)roundf(CENTER + AMPL * ii), 0, 255);
  }
}

uint32_t t0us;
bool syncHigh = false;
uint32_t syncStartUs = 0;
int lastIdx = -1;

void setup() {
  Serial.begin(115200);   // THIS board's own link: shape-select commands only, not the data
                          // stream — plain 115200 is plenty for occasional single characters.
  pinMode(SYNC_PIN, OUTPUT);
  digitalWrite(SYNC_PIN, LOW);
  buildLUT(shape);
  Serial.println("# signature_gen ready: send R, C, L, or D to switch shape");
  t0us = micros();
}

void loop() {
  if (Serial.available()) {
    char c = toupper(Serial.read());
    if (c == 'R' || c == 'C' || c == 'L' || c == 'D') {
      shape = c;
      buildLUT(shape);
      Serial.printf("# shape -> %c\n", shape);
    }
  }

  uint32_t now = micros();
  uint32_t elapsed = now - t0us;
  double cyclePos = fmod((double)elapsed * FREQ_HZ / 1e6, 1.0);
  int idx = (int)(cyclePos * LUT_SIZE) % LUT_SIZE;

  if (idx == 0 && lastIdx != 0) {          // just wrapped -> start of a new cycle, once
    digitalWrite(SYNC_PIN, HIGH);
    syncHigh = true;
    syncStartUs = now;
  }
  lastIdx = idx;
  if (syncHigh && (now - syncStartUs) > SYNC_PULSE_US) {
    digitalWrite(SYNC_PIN, LOW);
    syncHigh = false;
  }

  dacWrite(DAC_V_PIN, lutV[idx]);
  dacWrite(DAC_I_PIN, lutI[idx]);
}

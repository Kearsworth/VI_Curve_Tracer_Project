// adc_step.ino
//
// Experiment sketch for the internal-vs-external ADC decision: is the internal ESP32
// ADC's NOISE and NONLINEARITY small enough for our error budget? See hardware/adc_check.py.
//
// The DAC is used only as a convenient adjustable voltage source: the PC (adc_check.py) asks
// for a DAC code, this sketch holds it and streams raw ADC counts, and the person running the
// test reads the TRUE voltage at GPIO34 with a multimeter. Comparing counts to the multimeter
// isolates the ADC's own error (the DAC's nonlinearity doesn't matter, since we don't trust it).
//
// Wiring: same as Stage 2/3 — GPIO25 (DAC1) -> GPIO34 (ADC1_CH6). Put the multimeter across
// GPIO34 and GND.
//
// Protocol (921600 baud): send "d <code>\n" (0..255). Reply is CSV rows
//     dac_code,index,adc_counts
// followed by a "# done" line.

const int DAC_PIN = 25;
const int ADC_PIN = 34;
const unsigned long BAUD = 921600;
const int N_SAMPLES = 2000;
const int SETTLE_MS = 300;

void setup() {
  Serial.begin(BAUD);
  delay(200);
  dacWrite(DAC_PIN, 128);
  Serial.println("# adc_step ready: send 'd <code>' (0-255)");
  Serial.println("dac_code,index,adc_counts");
}

void loop() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (!line.startsWith("d ")) return;

  int code = constrain(line.substring(2).toInt(), 0, 255);
  dacWrite(DAC_PIN, code);
  delay(SETTLE_MS);
  for (int i = 0; i < N_SAMPLES; i++) {
    Serial.printf("%d,%d,%d\n", code, i, analogRead(ADC_PIN));
  }
  Serial.println("# done");
}

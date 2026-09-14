// loopback_check.ino
//
// Stage 2 sanity check for the DAC->ADC loopback (see ../../README.md and
// docs/ROADMAP.md Phase A). Purpose: prove the physical wire + both peripherals
// work, BEFORE adding sine waves, timing, or serial framing (that's Stage 3).
//
// Wiring: one jumper wire, GPIO25 (DAC1 out) -> GPIO34 (ADC1_CH6 in).
// GND is already shared on-board between the DAC and ADC circuitry.
//
// Board: ESP32 DevKit V1 (DOIT ESP32 DEVKIT V1 in Arduino IDE board menu).

const int DAC_PIN = 25;   // DAC1
const int ADC_PIN = 34;   // ADC1_CH6, input-only pin

uint8_t dacValue = 0;

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("loopback_check ready. Writing a ramp to DAC(25), reading ADC(34).");
  Serial.println("dac_value,adc_counts,expected_adc_approx");
}

void loop() {
  dacWrite(DAC_PIN, dacValue);
  delay(5); // let the DAC output settle before reading it back
  int adcCounts = analogRead(ADC_PIN);

  // DAC is 8-bit (0-255) over 0-3.3V; ADC is 12-bit (0-4095) over 0-3.3V.
  // So a perfect wire should read back roughly dacValue * 16.
  int expected = dacValue * 16;

  Serial.print(dacValue);
  Serial.print(",");
  Serial.print(adcCounts);
  Serial.print(",");
  Serial.println(expected);

  dacValue += 5; // slow ramp 0 -> 255 -> wraps back to 0
  delay(100);
}

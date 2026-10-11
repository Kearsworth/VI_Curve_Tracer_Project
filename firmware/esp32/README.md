# ESP32 firmware (plan / spec) — not implemented yet

Goal: the ESP32 becomes the whole front-end — it *generates* the drive signal and *reads*
the response, then streams samples to the PC. See `../../docs/DATA_CONTRACT.md` §7.

## Responsibilities
1. **Drive (DAC):** output a sine wave (start ~1 kHz) as the source signal.
2. **Capture (ADC):** read two channels at a fixed, known sample rate:
   - CH_V  = voltage across the DUT
   - CH_I  = voltage across the sense resistor (∝ current)
3. **Stream (USB serial):** send samples to the PC (CSV line per sample, or a binary block).
4. **Phase reference:** because the ESP32 generates the drive itself, it knows the phase of
   every sample exactly — include a sample index or timestamp so the PC can compute phase.

## Current milestone: LOOPBACK
Wire DAC output directly to an ADC input (bypass the circuit + DUT). Send a known waveform,
read it back, and confirm the round-trip matches. This validates the send/receive path and
the counts→volts conversion before the real circuit is available.

**Why the sketch prints `expected_adc_approx`:** it's not measured — it's just
`dacValue * 16` computed in software (12-bit ADC / 8-bit DAC = 16×) and printed next to the
real `adc_counts` reading, purely as an eyeball reference for "how far off from ideal is
this row." It's a debugging aid baked into the print line, not a third sensor.

**Stage 2 (`loopback/loopback_check`) result — confirmed on real hardware, 2026-09-14:**
DAC(25)→ADC(34) ramp test passed: `adc_counts` rises smoothly and monotonically with
`dac_value`, wraps cleanly at 255→0, no stuck/flat/noisy readings. Physical wire + both
peripherals are good.

However, the raw counts do **not** match the naive `dac_value * 16` prediction — there's a
real offset and mild nonlinearity, e.g. mid-range fit gives `adc ≈ 16.0*dac_value - 231`
(not `16*dac_value + 0`), and the top/bottom of the range compress slightly (DAC doesn't
swing the full 0–3.3V cleanly). This is expected ESP32 DAC/ADC real-world behavior, not a
wiring fault — it's exactly the kind of offset the **biasing** point above already
anticipated. Confirms: Stage 3 (and `calibrate.py` later) must not assume an ideal
DAC→volts / ADC→volts conversion — it needs a per-channel offset+gain correction (a simple
calibration sweep like this one, fit once, reused at runtime), not just the textbook
`counts * 3.3/4095` formula.

**Stage 3 (`loopback/sine_capture`) — written 2026-09-15, verified on real hardware 2026-09-15:**
Flashed and captured live: `adc_v_counts`/`adc_i_counts` trace a clean sine — peak (~3400 counts)
near `phase_rad ≈ 1.35`, trough (~337 counts) near `phase_rad ≈ 4.77`, consistent with a sine's
peak/trough sitting near π/2 and 3π/2. The two channels track each other almost exactly, as
expected since they currently read the same physical pin (no real sense resistor yet). Free-running
timing does show occasional larger gaps between samples (Serial buffer stalls) — exactly the jitter
the design already tolerates by carrying real elapsed time per sample rather than assuming a fixed
`dt`.
Upgrades the Stage 2 ramp into a real sine drive + timed 2-channel sampling + serial framing.
Concrete decisions made (previously open below):
- **Drive frequency: 50 Hz** for this stage, not the ~1kHz target above — chosen because the
  sketch samples with plain blocking `analogRead()` (not DMA/continuous mode yet), and 50 Hz
  leaves comfortable headroom for dozens of raw samples per cycle at that read cost. Reaching
  1kHz for real will need continuous/DMA ADC sampling — left for a later stage, not blocking
  this one, since `calibrate.py`'s 360-point resampling doesn't need a high raw sample count
  (CLAUDE.md: accuracy flat from ~30 to 720 resampled points).
- **DAC swings 28–228** (not the full 0–255) — Stage 2 measured nonlinearity worsening near
  the DAC's extremes, so the drive amplitude stays inside the better-behaved middle of the
  range on purpose.
- **Baud raised to 921600** (from Stage 2's 115200) — at 115200, printing one CSV line was
  the actual bottleneck (~2.6ms/line), not the ADC reads, which starved samples-per-cycle.
  921600 is already proven reliable on this board (esptool negotiates it for flashing).
- **Timing: free-running, no fixed-interval busy-wait.** Each sample's phase is computed from
  its *actual* elapsed time (`micros()` since start), not an assumed constant `dt` — so
  analogRead/Serial jitter shows up as uneven sample spacing, not a wrong phase label. This is
  explicitly fine per `docs/DATA_CONTRACT.md` §1 ("M may vary between captures — calibration
  fixes it").
- **Frame format extends `DATA_CONTRACT.md` §7's proposal** — see that file for the exact
  format and why a `t_us` column was added. Two ADC channels are read, but `ADC_I_PIN` is
  currently aliased to the same pin as `ADC_V_PIN` (no real sense resistor exists yet); wiring
  it to a real second channel is meant to be a one-line change once the circuit exists.

## Two-board bring-up — RETIRED 2026-10-04

See `dual_board/README.md` — a bring-up path, alongside the loopback above, that split
signature generation and capture across two ESP32 boards while the drive was planned as an
external voltage source. **Superseded**: per Dr. Wathis the drive goes back to the ESP32's own
DAC, so there's one board again — see "Dual-core single-board plan" below. Kept for the
record; the capture-unit code and the phase-from-known-reference reasoning both carry over.

## Dual-core single-board plan (current plan, replaces the two-board/external-generator path)

**Why:** the drive is the ESP32's own DAC again (through the confirmed 0–3.3V→±10V drive
stage below), not an external source — so the inter-board sync-pulse problem from
`dual_board/` doesn't exist to begin with. Per Dr. Wathis: split the one ESP32's two cores so
drive and capture don't block each other — one core generates the sine, the other reads the
ADC and streams. Not yet implemented or tested; this section is the design to build against.

```
                     ESP32 (single chip, two FreeRTOS tasks, one per core)
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Core A — driveTask                     Core B — captureTask          │
   │  - LUT sine, same approach as           - analogRead() GPIO34 (V)     │
   │    loopback/sine_capture.ino            - analogRead() GPIO35 (I)     │
   │  - dacWrite(DAC_PIN, ...) on a          - phase_rad from elapsed      │
   │    fixed cadence                          time since shared t0us      │
   │  - writes t0us ONCE at the start,       - Serial.printf CSV line      │
   │    before captureTask reads it            (same frame as today)      │
   └───────────────────┬──────────────────────────────┬───────────────────┘
                        │ DAC (GPIO25)                 │ ADC (GPIO34/35)
                        ▼                               ▲
                 drive stage (confirmed)          return path (UNCONFIRMED)
                 0–3.3V → ±10V                     ±10V → 0–3.3V
                        │                               │
                        └──────────► DUT + Rr ──────────┘
```

**No sync wire, on purpose.** `micros()`/`esp_timer_get_time()` on the ESP32 is one hardware
timer shared by both cores, not a per-core counter — so Core B can compute
`phase_rad = 2π · f · (t − t0us)` from the *same* clock Core A used to generate the sine,
without either core sending the other anything mid-run. This is the same "phase from a known
reference, never from geometry" rule (CLAUDE.md design decision #2) the single-board loopback
already relies on — splitting onto two cores doesn't change that, it only stops a slow
`analogRead()`/`Serial.printf()` on the capture side from stalling the drive task's timing
(and vice versa), which is the actual reason to split cores here, not phase derivation.

**Shared state, kept deliberately tiny:**
- `t0us` (`volatile uint32_t` or `esp_timer_get_time()`-based): written once by whichever task
  starts first, read-only after — no mutex needed for a single-writer-then-many-readers value.
- `DRIVE_FREQ_HZ`: a compile-time constant, not shared state at all.
- Optionally a boolean/semaphore `driveRunning` so captureTask doesn't log the first few
  samples before driveTask's first `dacWrite()` actually lands — a few ms of skip, not a
  correctness issue, but worth doing cleanly rather than ignoring.

**Build on top of what's proven, don't rewrite it:**
- Reuse `loopback/sine_capture.ino`'s LUT + `DAC_CENTER`/`DAC_AMPLITUDE_COUNTS` constants for
  driveTask — that sine generation is already verified on hardware (Stage 3 above).
- Reuse the same CSV frame (`index,t_us,phase_rad,adc_v_counts,adc_i_counts`) and meta line for
  captureTask — zero `hardware/reader.py` changes, same golden rule as every capture path so far.
- `xTaskCreatePinnedToCore()` for both tasks (Arduino's own `setup()/loop()` already runs
  pinned to core 1 by default on this board; put driveTask on the other core explicitly rather
  than relying on that default).

**Rollout order (mirrors the existing Stage 1/2/3 bring-up style):**
1. **Dual-core loopback first:** same jumper wire as Stage 2/3 (DAC25→ADC34 directly, no real
   circuit), just split across the two tasks/cores. Confirms the core split itself doesn't
   break anything, against the already-known-good single-core result, before any new circuit
   variable is introduced.
   — **Written and verified on hardware 2026-10-09:** `dual_core/dual_core_loopback/`.
   Boot meta shows `drive_core=0 capture_core=1`; ~65 samples/cycle at 50 Hz (dt median
   307 µs, p99 327 µs, one 1.6 ms outlier in 8.4k samples); V vs I correlation 0.9993 on two
   real pins; V fits `sin(phase)` with a ~1.7° lag (≈ half a 200 µs LUT step — expected
   quantisation, not clock drift). The `--verify` verdict (`D`/FAULTY) is meaningless for a
   loopback line (no DUT; DAC/ADC nonlinearity bends it) and is not a pass criterion.
   **Logic-analyzer check (same day, WeAct FX2 LA on TX0, sigrok-cli 24 MHz, UART decode
   clean):** the UART is the bottleneck, not `analogRead()` — the TX line is busy **98%** of
   the time. After ~15 min uptime a line is ~34 bytes (`index`/`t_us` have grown to 7 and 9
   digits) = ~372 µs on the wire, but the core samples every ~312 µs, so the TX buffer fills
   → **~1.6 ms holes in `t_us`, ~2–3 per drive cycle** (11 in 83 ms). Every hole lines up
   with a ~150–205 µs *idle* gap on the wire, so the writer isn't just blocked per-byte: it
   looks like it's only woken once the buffer is drained, the 128-byte HW FIFO then takes
   ~1.39 ms to empty + ~0.2 ms to sample/format = 1.6 ms (fits, not proven). Compare
   1 in 8.4k samples right after boot when lines were ~29 bytes. Phase labels stay correct
   (time-based), so calibrate.py just interpolates over the holes — fine for bring-up, but the
   sample rate silently degrades with uptime. Fix later with shorter/binary frames or
   decimation (CP2102 tops out at 921600); folds into the 1 kHz / DMA ROADMAP item.
   **Fixed same day:** `index` now wraps at 10000 and `t_us` at 100000 (both bounded → max
   line 28 bytes ≈ 304 µs), and capture runs on a fixed 333 µs grid (≈60 samples/cycle, UART
   ≤ ~91% busy). Re-measured over USB serial: 15,595 lines in 5 s, **0 dropped samples**,
   `t_us` step median 333 / max 339 µs; `reader.py --verify` unchanged. **Logic analyzer
   re-check:** 248 lines in 83 ms, 0 dropped, max line 28 bytes, TX busy 89% (was 98%), longest
   idle on the wire 68 µs (was ~200 µs at every hole), wire line period median 333 µs.
   Jumper GPIO25 → both GPIO34 and GPIO35 (two real ADC pins, same node). Drive task busy-loops
   on core 0 with the core-0 idle watchdog disabled (no WiFi/BT used); capture stays in
   `loop()` on core 1. Pass check: `python3 hardware/reader.py --port <port> --loopback`
   gives the same clean sine/line as `sine_capture` did.
2. **Wire in the confirmed drive stage** (0–3.3V→±10V) between DAC and DUT.
3. **Build/confirm the return path** (±10V→0–3.3V) — this is the actual blocking item now,
   not sync. Nothing past step 1 is safe to run on real ±10V without it (ADC absolute max is
   3.3V).
4. Re-run `hardware/dual_board_signature_check.py`-style validation (correlation/aspect ratio
   checks) against a real DUT once steps 2–3 are done, then fold into
   `hardware/live_pipeline_demo.py`.

**Carries over unchanged from the single-board loopback section above:** the DAC/ADC
nonlinearity-needs-calibration finding, the "measured `A`" distinction (§ ROADMAP "Measured A
+ amplitude leveling" — now sourced from the return-path-converted drive-node voltage, not the
DAC's nominal volts), and the 1kHz-drive / DMA-ADC roadmap item (still open, independent of
this core split).

## Confirmed analog front-end: 0–3.3V ↔ ±10V level shifter
*Confirmed with Dr. Wathis's circuit, 2026-09-15 — drive side only, see caveat below.*

The DAC's native 0–3.3V sine can't drive a real DUT through its full bipolar range, so the
advisor's circuit sits between the ESP32 DAC and the DUT: a **matched difference amplifier**
(TL071 op-amp, ±15V rails) that converts 0–3.3V → −10V…+10V.

```
          Rf = VR1 (60.4kΩ, trim)
        ┌──────────────────────┐
        │                      │
VREF ───┴─R1(10k)──┐        ┌──┴── Vo (−10V…+10V) ──► DUT
(1.65V)             ├──(−)  │
                     │ TL071├──►
Vin ────R2(10k)──┬──(+)     
(0–3.3V, from DAC) │
                    R3 = VR2 (60.4kΩ) 
                    │
                   GND
```

R1=R2=10kΩ and Rf=R3=60.4kΩ are matched, so the standard difference-amp result applies:

**Vo = (Rf/R1) × (Vin − VREF) = 6.04 × (Vin − 1.65V)**

Checked against the labeled endpoints: Vin=0V → Vo≈−9.97V, Vin=3.3V → Vo≈+9.97V. Matches.
`VREF = 1.65V` is exactly the DAC's own mid-rail center, so this is the same "center + swing"
biasing idea from Stage 2/3 — just implemented in analog hardware instead of firmware.

**⚠ Not yet confirmed: the return path.** The ESP32 ADC pins tolerate **0–3.3V only** —
feeding ±10V from the DUT's response straight into GPIO34/35 would exceed the absolute max
rating. Whatever comes back from the DUT (V, and I via the sense resistor) needs a matching
**down-conversion** stage (±10V → 0–3.3V) before the ADC reads it. This hasn't been shown or
confirmed yet — treat it as an open item, not a given, until it's verified with Dr. Wathis.

**Also affects `calibrate.py` later:** once this circuit is in the loop, the DAC's raw
amplitude (`A_nominal_v` in the Stage 3 sketch) is no longer the same as the amplitude
actually driving the DUT (`~10V`, after the ×6.04 gain) — normalization needs to account for
this conversion, not just the DAC-side offset/gain already tracked above.

## Things to decide when implementing
- ~~Sample rate and samples-per-cycle~~ — resolved above for Stage 3's loopback test; revisit
  once continuous/DMA sampling is needed to hit the ~1kHz production target.
- ADC input range vs the ±signal: **drive side confirmed** (see level-shifter above); **return
  side (attenuating the DUT's ±10V response back to 0–3.3V) still open** — needs a circuit and
  confirmation before real (non-loopback) capture is safe to attempt.
- ~~Serial baud / framing~~ — resolved above for Stage 3 (921600 baud, CSV with `t_us` +
  `phase_rad`); may still need to move to a binary block once real capture rates go up.

## Suggested language
Arduino C++ (or MicroPython). Keep the decoded output on the PC identical to the raw dict
in DATA_CONTRACT.md §1 so the ML pipeline never changes.

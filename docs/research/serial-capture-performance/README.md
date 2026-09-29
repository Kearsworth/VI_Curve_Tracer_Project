# Research: real-time serial capture performance

Opened 2026-09-30, from live-testing `hardware/live_pipeline_demo.py` against the real
two-board setup (`firmware/esp32/dual_board/`). Not a roadmap task — a side topic to study
further, parked here so the investigation already done isn't lost. See
`docs/ROADMAP.md` for what's actually scheduled.

## The observation that started this

`live_pipeline_demo.py` pegged a CPU core near 100% while running. First fix attempt
(throttling the matplotlib redraw to ~20Hz) helped some (97% → 64%) but CPU still spiked
back to ~99% — the redraw was never the real bottleneck.

## The two rates involved

1. **Capture rate** (CAP board → PC over serial): **not controllable from Python** — it's
   however fast the ESP32's `loop()` runs (`analogRead()` ×2 + `Serial.printf()`, no delay).
   Measured from real data: a 4-cycle capture at 50Hz drive (= 80ms window) returned 206
   samples → `206 / 0.08s ≈ 2,575 samples/sec`.
2. **Display rate**: throttled to ~20Hz in the current fix (`MIN_DRAW_INTERVAL = 0.05s` in
   `hardware/live_pipeline_demo.py`).

## Why throttling the display alone didn't fix it

Throttling *drawing* doesn't throttle *reading*. Even at 20Hz display, the script still
calls `cap.readline()` and parses **every one of the ~2,575 lines/sec** — decode bytes,
split on commas, parse ints, push onto deques — because:
- the OS serial buffer will back up (and eventually drop/corrupt data) if not drained at
  the rate data arrives;
- `calibrate.py` needs every sample to correctly reconstruct whole drive cycles — skipping
  samples between redraws would silently corrupt the signature.

So there are two independent costs: **drawing** (now cheap, throttled) and **reading +
parsing** (never throttled, running at the full ~2.5kHz capture rate in plain Python). The
second one was the actual bottleneck the whole time — pure-Python per-line parsing at
~2,500 iterations/sec is genuinely expensive on one core.

## Proposed next step (not yet implemented — this is the research starting point)

**Batch-read instead of line-at-a-time:** each loop iteration, read whatever's sitting in
the OS buffer in one chunk (`cap.in_waiting`) and split it locally, instead of one Python
function call per sample (~2,500 calls/sec → far fewer, larger reads). Should cut per-call
overhead substantially for the same data volume.

## Open questions worth digging into later

- How much does batch-reading actually save in practice? Worth profiling before/after
  (`cProfile` or just wall-clock CPU%) rather than assuming.
- Is pure-Python parsing (`str.split` + `int()`) the real floor, or would `numpy`/`struct`
  vectorized parsing meaningfully beat it? The firmware's format is plain CSV text right
  now — `firmware/esp32/README.md` already floats "Firmware may move to a compact binary
  block for speed once real capture rates go up," which is the firmware-side version of
  the same problem.
- Should serial reading move to its own thread (or `asyncio`), decoupled entirely from the
  matplotlib main loop, with only the periodic pipeline results crossing the thread
  boundary? Would remove the coupling between "read fast enough" and "keep the GUI
  responsive" entirely, at the cost of real threading complexity (GIL, queue handoff).
- At the ~1kHz production drive frequency (vs today's 50Hz bring-up rate, per
  `docs/ROADMAP.md`), the raw sample rate could climb well past today's ~2.5kHz if the
  firmware keeps sampling as fast as `analogRead()` allows — worth knowing whether this
  Python-side bottleneck would matter for a real (non-demo) capture path, or whether that
  path only ever needs to save-then-process rather than live-plot.
- Is this even a problem worth solving? `live_pipeline_demo.py` is a demo/debugging tool,
  not the production capture path (`hardware/reader.py` runs standalone captures, not
  continuous live ones). Worth deciding whether the payoff justifies the effort before
  spending real time on it.

## Relevant files

- `hardware/live_pipeline_demo.py` — where this was observed and partially fixed
- `hardware/reader.py` — the actual production-path reader (batch capture, not continuous)
- `firmware/esp32/dual_board/signature_capture/signature_capture.ino` — the data source
- `firmware/esp32/README.md` — already notes the CSV→binary tradeoff at the firmware level

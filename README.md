# AI Electronic Components Tester (COE2026-15)

Decide whether an electronic component is **good or faulty** from its **V-I signature**,
using a machine-learning pipeline. A V-I curve tracer (ESP32-based) captures the signature;
the software calibrates it, extracts features, and classifies it.

> **New here (human or AI)?** Read `CLAUDE.md` first for the full picture, then `docs/`.

## Quick start

```bash
pip install -r requirements.txt
cd vi_ml
python3 demo.py         # train + test end-to-end, prints accuracy
```

Run the tests (from repo root):

```bash
pytest -q
```

## Layout

- `vi_ml/` — the ML pipeline: `synth`, `calibrate`, `features`, `train`, `verify`, `demo`.
- `tests/` — invariant tests (run after any change to the pipeline).
- `hardware/` — how serial data becomes the pipeline's input (`reader_stub.py`).
- `firmware/esp32/` — plan for the ESP32 firmware (DAC out / ADC in / serial / loopback).
- `docs/` — `DESIGN.md` (why), `DATA_CONTRACT.md` (formats), `ROADMAP.md` (tasks),
  `WORKING_WITH_CLAUDE.md` (how to use Claude Code here).

## Status

ML pipeline works on synthetic data (~97.8% good/faulty). Hardware is in progress; we
currently test the data path with an ADC/DAC loopback. See `CLAUDE.md` §2.

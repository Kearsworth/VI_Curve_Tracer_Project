# Real captures (labelled)

Captures from the real Case 1 board, each with what the part really is, so the model can be
checked on real data and not only on synth (`docs/ROADMAP.md` Phase B).

- `*.txt` — the text the board prints (meta line, CSV header, rows), replayable with
  `python3 hardware/reader.py --file <capture> --frontend --rr <ohm> --zero <zero-cal> --verify`.
- `labels.csv` — one row per capture: drive frequency, firmware, front end, Rr actually
  connected, zero-cal file, component, health (`good` / `faulty` / `zero`), fault, reference
  value (multimeter / marking) and notes. `zero` rows are zero-cal captures (no DUT): used by
  other rows, not scored.

Check the current model on all of them:

```bash
python3 hardware/eval_real.py          # table + "n/n verdicts correct"; exit 1 if any is wrong
```

`tests/test_real_captures.py` runs the same rows in `pytest` (pipeline invariants, the 988 Ω
and 0.1 µF values, and every verdict), so a synth/feature/reader change that breaks a real
verdict fails the tests.

## Adding a capture

1. Capture in the board pane (Enter). With the 1 kHz firmware the capture starts at the
   board's settings line and is clean (`tools/board_page.py`).
2. `cp tools/last_capture.txt hardware/captures/<date>_<freq>_<part>.txt`
3. Add a row to `labels.csv`. Use the Rr really connected and the zero-cal taken with the
   same firmware. Redo the zero-cal (no DUT) whenever the board or firmware changes.

## What's here (2026-11-27)

12 captures, all on the Case 1 board with C5/C6 = 100 pF and Rr 1k: zero-cal; good parts
(988 Ω, 2k‖2k at 1 kHz and 50 Hz, 0.1 µF ceramic, 1N4148); hard faults (open socket, jumper
short, 1N4148 reversed); and soft faults built from good parts — leaky C (0.1 µF ‖ 2 kΩ),
high-ESR C (0.1 µF + 988 Ω in series), degraded diode (1N4148 + 988 Ω in series). All 11
scored verdicts are correct. Still small, the soft faults are strong versions (ESR/X 0.63,
Rleak/X 1.1, series R ≈ Rr), and there's no L, LED or real Zener yet.

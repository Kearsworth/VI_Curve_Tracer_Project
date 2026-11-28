# Real captures (labelled)

Captures from the real Case 1 board, each with what the part really is, so the model can be
checked on real data and not only on synth (`docs/ROADMAP.md` Phase B).

- `*.txt` — the text the board prints (meta line, CSV header, rows), replayable with
  `python3 hardware/reader.py --file <capture> --frontend --rr <ohm> --zero <zero-cal> --verify`.
- `labels.csv` — one row per capture: drive frequency, firmware, front end, Rr actually
  connected, zero-cal file, component, health (`good` / `faulty` / `zero` / `boundary`), fault,
  reference value (multimeter / marking) and notes. `zero` rows are zero-cal captures (no DUT):
  used by other rows, not scored. `boundary` rows are kept but not scored: a part outside
  synth's trained range, a fault severity between synth's good and faulty ranges, or a capture
  taken at the wrong Rr (`2026-11-27_mf1k_R1k_at_Rr10k.txt`).

Check the current model on all of them:

```bash
python3 hardware/eval_real.py          # table + "n/n verdicts correct"; exit 1 if any is wrong
```

`tests/test_real_captures.py` runs the same rows in `pytest` (pipeline invariants, the 988 Ω
and 0.1 µF values, and every verdict), so a synth/feature/reader change that breaks a real
verdict fails the tests.

## Adding a capture

Batches: `python3 hardware/collect.py <plan>` (plans: `--list`) tells you which part to plug in
and when to move the Rr jumper, captures one 1 kHz burst per part, prints the value and the
verdict, saves the capture here and appends its labels.csv row. Run it in a terminal; it
reads the keyboard.

By hand:

1. Capture in the board pane (Enter). With the burst firmware (`case1_frontend_1k` / `_mf`) the
   capture starts at the board's settings line and is clean (`tools/board_page.py`; `tools/` is
   the local workspace, not in the repo).
2. `cp tools/last_capture.txt hardware/captures/<date>_<freq>_<part>.txt`
3. Add a row to `labels.csv`. Use the Rr really connected and the zero-cal taken with the
   same firmware. Redo the zero-cal (no DUT) whenever the board or firmware changes.

## What's here (2026-11-28)

66 captures, all on the Case 1 board with C5/C6 = 100 pF, all at 1 kHz but one (50 Hz):

| health | n | what |
|---|---|---|
| `zero` | 3 | zero-cal captures (no DUT): `case1_frontend_1k`, `case1_frontend_mf`, and `_mf` with the GPIO32 reference |
| `good` | 33 | 24 kit resistors 100 Ω – 300 kΩ (multimeter values in `reference`); 988 Ω and 2k‖2k (4 captures, one at 50 Hz); 0.1 µF ceramic (2); 1N4148 (1); LED (2) |
| `faulty` | 19 | open (1), short (2), reversed 1N4148 (1), reversed LED (1); soft faults built from good parts: leaky C (4), high-ESR C (4), degraded diode (4), degraded LED (2) |
| `boundary` | 11 | not scored: soft faults between synth's good and faulty ranges (6); resistors outside the trained range, 10 Ω / 47 Ω / 470 kΩ / 1 MΩ (4); a 1 kΩ taken at Rr 10k (1) |

All 52 scored verdicts are correct. The values and the soft-fault boundaries are tabled in
`docs/CASE1_WIRING.md` ADC step 3. Still missing: inductors, Zeners and electrolytic capacitors.

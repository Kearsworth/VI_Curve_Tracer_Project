# WORKING_WITH_CLAUDE.md — How to drive Claude Code well on this project

Practical habits that make Claude Code far more useful. Written for this repo specifically.

## The mindset

Claude Code is strongest when it can (1) read the context it needs, (2) make a small change,
and (3) **verify it with a command**. Your job is to give it that loop. The three biggest
levers are: a good `CLAUDE.md` (done), **tests it can run**, and **clear, scoped tasks**.

## 1. Let the tests be its safety net

This repo ships with `tests/`. After Claude changes anything in the pipeline, ask it to run:

```
pytest -q
```

The tests encode the invariants (calibrate output is 360×2, no NaN, capacitor and inductor
have opposite rotation sign, health accuracy stays above a floor, results are reproducible).
If Claude breaks an intentional behavior, a test fails and it will notice. **Tell Claude:
"make the change, then run pytest and fix anything that breaks."** Add a new test whenever
you add a feature — it becomes permanent protection.

## 2. Give scoped tasks, not vague ones

- Weak: "improve the model."
- Strong: "In `features.py`, add a `reverse_leakage_slope` feature for diodes/Zeners,
  append it to `FEATURE_NAMES`, retrain via `train.py`, and report the new per-fault recall
  from `check_demo`-style evaluation. Run pytest."

Point it at the file, say what to change, and say how to verify. One task at a time.

## 3. Make it read before it writes

At the start of a session: **"Read CLAUDE.md and docs/DESIGN.md before changing anything."**
DESIGN.md lists decisions that look like bugs but are intentional (360 points, common-factor
normalization, type-only-meaningful-when-good). This stops Claude from "helpfully" undoing them.

## 4. Plan first for anything non-trivial

For a bigger change (e.g. hardware integration), ask Claude to **write a short plan first**
and wait for your OK before coding. "Propose a plan for `hardware/reader.py` that turns
serial data into the raw dict; don't write code yet." Review, then say "go."

## 5. Keep changes small and reviewable

Ask for **surgical diffs**, not rewrites: "change only what's needed; don't refactor the
pipeline." Small commits are easier to review and to undo. Use git and commit after each
green (passing-tests) step so you can always roll back.

## 6. Use the docs as living memory

- Update `docs/ROADMAP.md` as tasks complete ("mark the loopback task done").
- When a new decision is made, ask Claude to add it to `docs/DESIGN.md`. Next session it
  will remember *why*, not just *what*.
- Keep `CLAUDE.md` short; push detail into `docs/`. If `CLAUDE.md` grows huge, Claude wastes
  context re-reading it.

## 7. Verify claims — don't trust numbers blindly

If Claude says "accuracy improved," ask it to **show the command and its output**. Prefer
"run it and paste the result" over "it should work." The included eval scripts print real
numbers; make Claude use them.

## 8. Good first prompts for this repo

- "Read CLAUDE.md and docs/. Then run `python vi_ml/demo.py` and confirm the pipeline works,
  and summarize the current accuracy."
- "Read the ESP32 spec in firmware/esp32/README.md and propose the serial protocol and a
  loopback test plan. Plan only, no code yet."
- "Implement `hardware/reader.py` from `reader_stub.py` per docs/DATA_CONTRACT.md section 7.
  Add a test that feeds a fake serial line and checks the raw dict shape. Run pytest."
- "Add a soft-fault feature (knee sharpness) in features.py, retrain, and report per-fault
  recall before/after. Keep other features unchanged. Run pytest."

## 9. Housekeeping that pays off

- Use **git** from day one; commit the initial skeleton first.
- Keep `models/` out of git (already in `.gitignore`) — regenerate with `train.py`.
- If you add real captured data, keep it in a `data/` folder and git-ignore large/raw files.
- Re-run `pytest` before you consider any task "done".

## 10. When Claude is unsure

Encourage it to **ask instead of guessing**, and to **state assumptions**. A one-line
clarifying question up front saves a wrong implementation. If a task touches an intentional
decision in DESIGN.md, it should flag the conflict rather than silently changing it.

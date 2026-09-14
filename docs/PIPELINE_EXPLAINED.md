# Why DAC *and* ADC — and how the whole pipeline fits together

This file exists to answer one question in depth: **why does the ESP32 need to
both drive a signal (DAC) and read one back (ADC)? Why not just measure the
part with a multimeter/ADC alone?** Then it walks the full pipeline so that
question sits in context.

## 1. The core idea: a component is identified by how it *responds*, not by a
   single number

A multimeter gives you one static number: 10kΩ, 3.3V, whatever. That's enough
to check a resistor, but it can't tell good-diode from bad-diode, or
capacitor from resistor, because many different things can produce the same
single reading at one instant.

What actually distinguishes a resistor from a capacitor from a diode from a
Zener is **how its current responds as the voltage across it changes over
time.** A resistor's I is proportional to V at every instant (Ohm's law) — a
straight line. A capacitor's I depends on how fast V is *changing*, so I
leads V — the plot becomes an ellipse. A diode only conducts one direction
and has a sharp knee — the plot becomes a lopsided loop with a corner. A
shorted or open part collapses that shape into a degenerate line or a flat
zero.

So the *shape* of the V-I curve, traced over one full cycle of a changing
signal, is the fingerprint. That's the "V-I signature" this whole project is
built around (see `docs/DESIGN.md` for the deeper reasoning, and
`vi_ml/plot_signatures.py` for what these shapes actually look like for the
6 component types).

## 2. Why you need to *actively drive* the part to see that shape

A V-I curve only exists if voltage is changing. If you just probe a
component sitting there with no excitation, there's no V-I loop — just one
point (0V, 0A) or whatever DC bias happens to be present.

To trace the loop, something has to actively push voltage across the part
across a full sweep of values — up, down, through zero, negative — while
you watch how current responds at each point. That "something" is the DAC:
it outputs a sine wave (a smooth sweep of every voltage between -A and +A),
which becomes the **drive signal**.

## 3. Why you need the ADC — actually, why you need to measure *two* things

Once the DAC is driving the part, you need to record, at many points across
that sine cycle:
- **V** — the voltage actually appearing across the component (not
  necessarily identical to what the DAC commanded, because the circuit
  loads it)
- **I** — the current flowing through the component at that same instant

You can't get current directly from a microcontroller pin — ADCs measure
voltage. So the hardware puts a small known **sense resistor (Rr)** in
series with the DUT (device under test) and measures the voltage across
*that* resistor. By Ohm's law, `I = V_sense / Rr`. So really there are two
ADC channels: `CH_V` (voltage across the DUT) and `CH_I` (voltage across the
sense resistor, converted to current).

Plot V (x-axis) against I (y-axis) as the sine sweeps through one full
cycle, and you get the closed loop — the signature. That's *why* both a
drive (DAC) and a synchronized read (ADC, 2 channels) are non-negotiable:
DAC creates the sweep, ADC captures the part's response to every point in
that sweep, and you need both V and I to plot a *curve* rather than a
*number*.

## 3b. The oscilloscope analogy (Q&A recap)
*Asked: 2026-09-14*

**Q:** On a bench, you'd use a function generator + oscilloscope in X-Y mode
to trace the V-I loop, with the generator swinging ± — is the DAC just
standing in for the generator?

**A:** Yes. Bench setup: a function generator drives the DUT with a sine that
swings positive and negative around 0V; a scope in X-Y mode plots V against
I (via a sense-resistor channel) in real time — the scope doesn't generate
anything, it just digitizes and plots the two channels. On the ESP32, the
**DAC plays the generator's role** (creates the drive sweep) and the **2-channel
ADC plays the scope's X-Y role** (captures the response), except instead of
drawing it on a screen, the numbers get logged and the loop is reconstructed
in `calibrate.py`.

One gotcha this surfaces: a bench generator can output true bipolar ±
voltage; the ESP32's built-in DAC (`dacWrite()`) **cannot** — it only outputs
0–3.3V, unsigned. So the drive sine has to be **biased/offset** to sit
entirely within 0–3.3V (e.g. centered at 1.65V), and that offset is
**subtracted back out in software** (using the known amplitude `A` carried
in the raw dict) to reconstruct the effective ± signal before computing the
V-I loop. See `firmware/esp32/README.md` → "Things to decide when
implementing" for where this gets decided in Stage 3.

## 4. Why loopback (DAC → ADC directly, Stage 2 you're on now)

Right now the real circuit (sense resistor, DUT socket, signal
conditioning) is still being built by the advisor. So instead of waiting,
the DAC output is wired straight into an ADC input with nothing in
between. This proves the *data path* — can the ESP32 reliably generate a
signal and read a signal back, sample it correctly, and get it over serial
without garbage — completely independent of whether the analog front-end
hardware works yet.

Stage 2 (`loopback_check.ino`) is the simplest possible version of that:
DAC outputs a slow ramp, ADC reads it back, and you eyeball that
`adc_counts ≈ dacValue * 16`. No sine, no timing precision, no second
channel yet — just "does a voltage I command on this pin show up correctly
on that pin."

Stage 3 will upgrade this to: DAC outputs an actual sine wave, ADC samples
it at a fixed, known rate (with the sample index acting as a phase
reference, since the ESP32 knows exactly when it wrote each DAC value), and
the result streams over serial as `{v, i, phase, A, Rr}`-shaped data — the
same raw dict format the ML side expects (see `docs/DATA_CONTRACT.md`).
Once the real circuit is ready, this exact same sketch design gets a second
ADC channel added (V and I) and gets pointed at the real DUT instead of a
wire — nothing else about the downstream code changes.

## 5. The full pipeline, end to end

```
[ESP32]  DAC ── drive sine ──►  [circuit + DUT]  ── V, I ──►  ADC  ──USB──►  [PC / Python]
                                     (loopback: DAC→ADC directly for now)          │
                                                                                    ▼
   raw {v, i, phase, A, Rr}            <- physical measurement, per-sample arrays
        │
        │  calibrate.py: resample to 360 points (one per drive-phase degree,
        │                 not geometric angle — see CLAUDE.md #6.2) and
        │                 normalize V and I by fixed constants A and Rr
        │                 (NOT per-axis min-max — see CLAUDE.md #6.3)
        ▼
   signature (360 × 2 array)           <- the "shape" — this is the fingerprint
        │
        │  features.py: reduce the shape to 12 interpretable numbers
        │                (loop area, slope, symmetry, knee sharpness, etc.)
        ▼
   feature vector (12,)
        │
        │  train.py (offline, once): fit Random Forest (health + type) and
        │                              Isolation Forest (anomaly) on many
        │                              labeled signatures, save to models/
        │
        │  verify.py (online, every test): load the saved models, run this
        │                                    one feature vector through them
        ▼
   verdict: GOOD / FAULTY  (+ confidence, detected component type, anomaly flag)
```

The **golden rule** (CLAUDE.md #3): `calibrate.py` and `features.py` must
run identically whether the raw data came from `synth.py` (synthetic, what
everything is validated on today) or from real hardware. That's *why*
Stage 3's serial output is being designed to match the raw dict format
exactly — so the ML pipeline downstream never has to know or care whether
the V-I loop it's classifying came from a simulated component or a real
one sitting on the bench.

## 6. One-paragraph summary

The DAC's job is to *create* the sweep of voltages needed to trace a curve
at all. The ADC's job (on two channels) is to *record* how the part
responded — its actual V and its I — at each point in that sweep, so a full
loop can be reconstructed. Loopback is a temporary wiring trick to test that
generate-and-record data path before the real analog front-end exists.
Everything from `calibrate.py` onward is agnostic to where the raw
`{v, i, phase, A, Rr}` data came from — synthetic, loopback, or real
hardware — as long as it's shaped the same way.

"""hardware/autorange.py planning: the same (frequency, Rr) choice synth trains with, from one
1 kHz measurement. No hardware needed."""
import numpy as np
import pytest

import autorange
import synth

W1K = 2 * np.pi * 1000.0


def _plan(z):
    return autorange.plan(z, 1000.0, nonlinear=False)


@pytest.mark.parametrize("z, want", [
    (988 + 0j, (1000.0, 1000.0)),                       # resistor near Rr 1k
    (50 + 0j, (1000.0, 220.0)),                         # small R -> smallest Rr
    (200e3 + 0j, (1000.0, 100000.0)),                   # big R -> largest Rr
    (-1j / (W1K * 100e-9), (1000.0, 1000.0)),           # 0.1 uF: X 1.6k at 1 kHz
    (-1j / (W1K * 1e-9), (1000.0, 100000.0)),           # 1 nF: X 159k -> Rr 100k
    (1j * W1K * 100e-3, (1000.0, 1000.0)),              # 100 mH: X 628 ohm
])
def test_plan_matches_the_part(z, want):
    f, rr = _plan(z)
    assert (round(f, 3), rr) == want


def test_big_capacitor_goes_to_low_frequency_and_small_rr():
    # 1000 uF: X 0.16 ohm at 1 kHz; readable only near 1 Hz with 220 ohm (X 159 ohm)
    f, rr = _plan(-1j / (W1K * 1000e-6))
    assert f == pytest.approx(1.0) and rr == 220.0
    f, rr = _plan(-1j / (W1K * 47e-6))                  # 47 uF -> tens of Hz
    assert 3 < f < 40 and rr == 220.0


def test_nonlinear_parts_stay_at_the_training_condition():
    assert autorange.plan(-1j / (W1K * 1e-3), 1000.0, nonlinear=True) == (synth.DEFAULT_F, synth.DEFAULT_RR)


def test_frequencies_are_ones_the_firmware_can_make():
    for f in synth.TEST_FREQS_HZ:
        m = 1000.0 / f
        assert abs(m - round(m)) < 1e-9 and 1 <= round(m) <= 1000


def test_z_model_extrapolates_r_c_and_l():
    zc = autorange.z_model(complex(80, -1600), 1000.0)          # lossy C
    assert zc(100.0).imag == pytest.approx(-16000, rel=1e-6) and zc(100.0).real == pytest.approx(80)
    zl = autorange.z_model(complex(30, 628), 1000.0)            # L + DCR
    assert zl(100.0).imag == pytest.approx(62.8, rel=1e-6)
    zr = autorange.z_model(complex(1000, 20), 1000.0)           # nearly resistive
    assert abs(zr(1.0)) == pytest.approx(abs(complex(1000, 20)))


def test_harmonics_separate_diodes_from_linear_parts():
    rng = np.random.default_rng(4)
    thd = {c: [autorange.current_thd(synth.generate_sample(c, "good", rng)) for _ in range(10)]
           for c in ("R", "C", "L", "D", "LED")}
    for c in ("R", "C", "L"):
        assert max(thd[c]) < autorange.NONLINEAR_THD, (c, max(thd[c]))
    for c in ("D", "LED"):
        assert min(thd[c]) > autorange.NONLINEAR_THD, (c, min(thd[c]))


# ---- judge(): the model's verdict only where it applies (real captures, 2026-11-27) ----------
ML = {"verdict": "ML"}          # stand-in: judge passes the model's verdict through unchanged


def _judge(name):
    import eval_real
    row = next(r for r in eval_real.load_labels() if r["file"] == name)
    return autorange.judge(eval_real.raw_for(row), ML)


@pytest.mark.parametrize("name, verdict, rng", [
    ("2026-11-27_mf1k_R10.txt", "OUT_OF_RANGE", "below"),           # good 10 ohm at Rr 221: short-like shape
    ("2026-11-27_mf1k_R47.txt", "OUT_OF_RANGE", "below"),
    ("2026-11-27_mf1k_R1k_at_Rr10k.txt", "OUT_OF_RANGE", "below"),  # right part, wrong Rr
    ("2026-11-27_mf1k_R470k.txt", "OUT_OF_RANGE", "above"),
    ("2026-11-27_mf1k_R1M.txt", "OUT_OF_RANGE", "above"),           # good 1 Mohm at Rr 101k: open-like shape
    ("2026-11-27_1k_open.txt", "FAULTY", "open"),
    ("2026-11-27_1k_short.txt", "FAULTY", "short"),
    ("2026-11-27_mf1k_short.txt", "FAULTY", "short"),
    ("2026-11-27_mf1k_R100.txt", "ML", "ok"),                       # ends of the trained range stay with the model
    ("2026-11-27_mf1k_R300k.txt", "ML", "ok"),
    ("2026-11-27_mf1k_R3.3k.txt", "ML", "ok"),
    ("2026-11-27_1k_C100n.txt", "ML", "ok"),
    ("2026-11-27_mf1k_LED_fwd_ref.txt", "ML", "nonlinear"),
    ("2026-11-27_1k_D1N4148_rev.txt", "ML", "nonlinear"),
])
def test_judge_on_real_captures(name, verdict, rng):
    out = _judge(name)
    assert (out["verdict"], out["range"]) == (verdict, rng), out["reason"]


def test_judge_keeps_every_scored_real_capture_with_the_model():
    # the range rule must not take over any part the model is scored on
    import eval_real
    for row in eval_real.load_labels():
        if row["health"] in ("good", "faulty"):
            out = autorange.judge(eval_real.raw_for(row), ML)
            assert out["verdict"] in ("ML", "FAULTY"), (row["file"], out["reason"])
            if out["verdict"] == "FAULTY":
                assert row["health"] == "faulty", (row["file"], out["reason"])

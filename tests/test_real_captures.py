"""Real Case 1 captures (hardware/captures/labels.csv): the reader -> calibrate -> features path
and the trained model must keep getting them right. Add new labelled captures to labels.csv."""
import os

import numpy as np
import pytest

import calibrate
import eval_real
import features

ROWS = eval_real.load_labels()
SCORED = [r for r in ROWS if r["health"] in ("good", "faulty")]
BY_FILE = {r["file"]: r for r in ROWS}


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["file"])
def test_real_capture_flows_through_the_pipeline(row):
    raw = eval_real.raw_for(row)
    sig = calibrate.calibrate(raw)
    assert sig.shape == (calibrate.N_POINTS, 2) and np.isfinite(sig).all()
    assert np.isfinite(features.extract(sig)).all()
    assert 4.0 < raw["A"] < 6.0                       # inside synth's drive-amplitude range


def test_real_resistor_and_capacitor_values():
    r988 = eval_real.lockin_z(eval_real.raw_for(BY_FILE["2026-11-27_1k_R988.txt"]))
    assert abs(r988) == pytest.approx(988.0, rel=0.01)          # multimeter value
    zc = eval_real.lockin_z(eval_real.raw_for(BY_FILE["2026-11-27_1k_C100n.txt"]))
    assert -1 / (2 * np.pi * 1000.0 * zc.imag) == pytest.approx(100e-9, rel=0.05)


@pytest.fixture(scope="module")
def verify_mod():
    import train
    import verify
    if not os.path.exists(os.path.join(train.MODEL_DIR, "health_rf.joblib")):
        train.main(save=True, verbose=False)
    verify._CACHE.clear()                              # load whatever is on disk now
    return verify


@pytest.mark.parametrize("row", SCORED, ids=lambda r: r["file"])
def test_model_verdict_on_real_capture(verify_mod, row):
    expect = "GOOD" if row["health"] == "good" else "FAULTY"
    assert verify_mod.verify(eval_real.raw_for(row))["verdict"] == expect

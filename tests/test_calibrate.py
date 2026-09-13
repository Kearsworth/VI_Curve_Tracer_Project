"""Invariants for the calibration step. If these fail, the data contract changed."""
import numpy as np
import synth, calibrate

def test_shape_is_360_by_2():
    raw = synth.generate_sample("C", "good", np.random.default_rng(0))
    sig = calibrate.calibrate(raw)
    assert sig.shape == (calibrate.N_POINTS, 2)
    assert calibrate.N_POINTS == 360

def test_no_nan_or_inf():
    rng = np.random.default_rng(1)
    for comp in synth.COMPONENTS:
        sig = calibrate.calibrate(synth.generate_sample(comp, "good", rng))
        assert np.isfinite(sig).all()

def test_deterministic_dataset():
    a = synth.make_dataset(n_good=3, n_faulty=3, seed=7)
    b = synth.make_dataset(n_good=3, n_faulty=3, seed=7)
    assert all(np.allclose(x["v"], y["v"]) and x["fault"] == y["fault"] for x, y in zip(a, b))

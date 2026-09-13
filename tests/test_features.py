"""Invariants for feature extraction, incl. the C-vs-L direction property."""
import numpy as np
import synth, calibrate, features

def test_twelve_finite_features():
    raw = synth.generate_sample("R", "good", np.random.default_rng(0))
    f = features.extract(calibrate.calibrate(raw))
    assert f.shape == (12,)
    assert len(features.FEATURE_NAMES) == 12
    assert np.isfinite(f).all()

def test_capacitor_and_inductor_have_opposite_rotation():
    # signed_area sign encodes rotation direction; C and L must be opposite and consistent.
    rng = np.random.default_rng(3)
    def areas(comp):
        return np.array([
            features._signed_area(*calibrate.calibrate(synth.generate_sample(comp, "good", rng)).T)
            for _ in range(20)
        ])
    ca, la = areas("C"), areas("L")
    assert np.all(np.sign(ca) == np.sign(ca[0]))   # C consistent
    assert np.all(np.sign(la) == np.sign(la[0]))   # L consistent
    assert np.sign(ca.mean()) != np.sign(la.mean())  # opposite to each other

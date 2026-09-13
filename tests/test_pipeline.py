"""End-to-end: training reaches a sane accuracy floor and obvious cases verify correctly."""
import numpy as np
import synth, calibrate, features, train, verify

def test_training_meets_accuracy_floor():
    # Train quietly, then evaluate on a FRESH independent set (different seed).
    train.main(save=True, verbose=False)
    health = __import__("joblib").load(train.os.path.join(train.MODEL_DIR, "health_rf.joblib"))
    rng = np.random.default_rng(2024)
    X, y = [], []
    for comp in synth.COMPONENTS:
        for _ in range(40):
            X.append(features.extract(calibrate.calibrate(synth.generate_sample(comp, "good", rng)))); y.append(0)
        for _ in range(40):
            X.append(features.extract(calibrate.calibrate(synth.generate_sample(comp, "faulty", rng)))); y.append(1)
    acc = (health.predict(np.array(X)) == np.array(y)).mean()
    assert acc > 0.90, f"health accuracy dropped to {acc:.3f} (was ~0.97)"

def test_obvious_cases_verify_correctly():
    train.main(save=True, verbose=False)
    rng = np.random.default_rng(99)
    good = verify.verify(synth.generate_sample("R", "good", rng))
    assert good["verdict"] == "GOOD"
    # an open/short resistor should read FAULTY
    bad_raw = None
    while bad_raw is None:
        r = synth.generate_sample("R", "faulty", rng)
        if r["fault"] in ("open", "short"):
            bad_raw = r
    assert verify.verify(bad_raw)["verdict"] == "FAULTY"

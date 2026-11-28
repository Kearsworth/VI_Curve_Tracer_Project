"""
eval_synth.py — the synthetic numbers quoted in the docs, on a set the models never saw.

  python3 vi_ml/eval_synth.py                 # ~1 min: train (as train.py) + score 7,200 samples
  python3 vi_ml/eval_synth.py --good 100 --faulty 200   # quicker, noisier

Trains the three models exactly as train.py does (without saving them), then scores a fresh
synth.make_dataset(seed=1) set: health accuracy and MCC, good parts called GOOD, type accuracy
on good parts, anomaly ROC-AUC, the health confusion matrix, and recall per component/fault.
train.py's own test split has only ~75-150 samples per fault, too few for steady per-fault recall.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calibrate  # noqa: E402
import features  # noqa: E402
import synth  # noqa: E402
import train  # noqa: E402
from sklearn.metrics import confusion_matrix, matthews_corrcoef, roc_auc_score  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--good", type=int, default=400, help="good samples per component (default 400)")
    ap.add_argument("--faulty", type=int, default=800, help="faulty samples per component (default 800)")
    ap.add_argument("--seed", type=int, default=1, help="dataset seed; train.py uses 0 (default 1)")
    args = ap.parse_args(argv)

    health_rf, type_rf, anomaly_if = train.main(save=False, verbose=False)
    data = synth.make_dataset(n_good=args.good, n_faulty=args.faulty, seed=args.seed)
    X = np.array([features.extract(calibrate.calibrate(r)) for r in data])
    comp = np.array([r["component"] for r in data])
    faulty = np.array([r["health"] == "faulty" for r in data])
    fault = np.array([r["fault"] or "" for r in data])
    pred = health_rf.predict(X) == 1

    print(f"{len(X)} synthetic samples, seed {args.seed} (train.py trains on seed 0)")
    print(f"  health accuracy        {(pred == faulty).mean():.3f}   MCC {matthews_corrcoef(faulty, pred):.3f}")
    print(f"  good parts -> GOOD     {(~pred[~faulty]).mean():.3f}")
    print(f"  type accuracy (good)   {(type_rf.predict(X[~faulty]) == comp[~faulty]).mean():.3f}")
    print(f"  anomaly ROC-AUC        {roc_auc_score(faulty, -anomaly_if.decision_function(X)):.3f}")
    print(f"  confusion [truth good, faulty] x [said GOOD, FAULTY]: {confusion_matrix(faulty, pred).tolist()}")
    print("\n  recall per component / fault")
    for c in synth.COMPONENTS:
        m = (comp == c) & ~faulty
        print(f"    {c:4s} {'good -> GOOD':14s} {(~pred[m]).mean():.3f}  (n={m.sum()})")
        for f in synth.FAULTS[c]:
            m = (comp == c) & (fault == f)
            print(f"    {c:4s} {f:14s} {pred[m].mean():.3f}  (n={m.sum()})")


if __name__ == "__main__":
    main()

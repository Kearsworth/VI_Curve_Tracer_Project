"""
compare_models.py — the health classifier: Random Forest vs SVM vs a neural network (MLP), plus
gradient boosting, on the same 14 features (docs/ROADMAP.md Phase C, docs/LITERATURE.md §3).

  python3 vi_ml/compare_models.py             # a few minutes; changes no saved model
  python3 vi_ml/compare_models.py --per-class 1200   # the same, on a 4x bigger training set

Each model is tuned by 5-fold cross-validation on a train.py-style training split (seed 0,
--per-class samples per component and health; 300 by default, as in the 2026-11-28 run) only,
then scored on data none of them saw:
  - a fresh synthetic set (seed 1, the same set as eval_synth.py): accuracy, MCC, good parts
    called GOOD, and recall per fault, the weak soft faults first;
  - the labelled real captures (hardware/captures/labels.csv, as eval_real.py): how many scored
    rows each model gets right, and its p_faulty on the boundary rows.
A last check trains RF and the best other model on 2x and 4x more synthetic data, to tell a
limit of the classifier from a limit of the features/data.
SVM and MLP get a feature scaler (standard, quantile or signed log); the features are
heavy-tailed. The tree models need none. On Python 3.13 with joblib 1.4 the worker processes
print harmless "ResourceTracker ... No child processes" tracebacks when they exit (a known
joblib/Python bug); the results are unaffected.
"""
import argparse
import os
import sys
import time
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "hardware"))
import calibrate  # noqa: E402
import features  # noqa: E402
import synth  # noqa: E402
import train  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.metrics import accuracy_score, matthews_corrcoef  # noqa: E402
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split  # noqa: E402
from sklearn.neural_network import MLPClassifier  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import FunctionTransformer, QuantileTransformer, StandardScaler  # noqa: E402
from sklearn.svm import SVC  # noqa: E402

# weakest classes of the current RF first (eval_synth.py, 2026-11-28)
FAULT_ORDER = [("Z", "leak"), ("L", "shorted_turns"), ("C", "esr"), ("C", "leak"), ("L", "dcr"),
               ("D", "reversed"), ("D", "degraded"), ("Z", "reversed"), ("LED", "degraded")]


def _signed_log(X):
    return np.sign(X) * np.log1p(np.abs(X))


def scalers():
    return [StandardScaler(),
            QuantileTransformer(output_distribution="normal", n_quantiles=500, random_state=0),
            Pipeline([("log", FunctionTransformer(_signed_log)), ("std", StandardScaler())])]


def scaler_name(v):
    if isinstance(v, Pipeline):
        return "signed log + standard"
    return type(v).__name__ if hasattr(v, "fit") else v


def candidates():
    """name -> (estimator, CV grid or None). 'RF (train.py)' is the model in use, untuned here."""
    return {
        "RF (train.py)": (RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                                                 class_weight="balanced", random_state=42), None),
        "RF tuned": (RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42),
                     {"min_samples_leaf": [1, 2, 4], "max_features": ["sqrt", 0.5, 1.0]}),
        "SVM (RBF)": (Pipeline([("scale", StandardScaler()),
                                ("clf", SVC(kernel="rbf", class_weight="balanced"))]),
                      {"scale": scalers(), "clf__C": [1, 10, 100, 1000],
                       "clf__gamma": ["scale", 0.03, 0.1, 0.3]}),
        "MLP": (Pipeline([("scale", StandardScaler()),
                          ("clf", MLPClassifier(max_iter=3000, early_stopping=True,
                                                n_iter_no_change=30, random_state=0))]),
                {"scale": scalers(), "clf__hidden_layer_sizes": [(32,), (64,), (64, 32), (128, 64), (256, 128)],
                 "clf__alpha": [1e-5, 1e-4, 1e-3, 1e-2]}),
        "Gradient boosting": (HistGradientBoostingClassifier(max_iter=400, random_state=0),
                              {"learning_rate": [0.05, 0.1], "max_leaf_nodes": [15, 31, 63],
                               "l2_regularization": [0.0, 1.0]}),
    }


def synth_xy(n_good, n_faulty, seed):
    data = synth.make_dataset(n_good=n_good, n_faulty=n_faulty, seed=seed)
    X = np.array([features.extract(calibrate.calibrate(r)) for r in data])
    comp = np.array([r["component"] for r in data])
    faulty = np.array([r["health"] == "faulty" for r in data], dtype=int)
    fault = np.array([r["fault"] or "" for r in data])
    return X, comp, faulty, fault


def real_xy(cycles):
    import eval_real
    rows = [r for r in eval_real.load_labels() if r["health"] in ("good", "faulty", "boundary")]
    X = np.array([features.extract(calibrate.calibrate(eval_real.raw_for(r, cycles))) for r in rows])
    return X, rows


def p_faulty(model, X):
    return model.predict_proba(X)[:, list(model.classes_).index(1)]


def scores(model, X, comp, faulty, fault):
    pred = model.predict(X)
    out = {"acc": accuracy_score(faulty, pred), "mcc": matthews_corrcoef(faulty, pred),
           "good": float((pred[faulty == 0] == 0).mean())}
    for c, f in FAULT_ORDER:
        m = (comp == c) & (fault == f)
        out[f"{c} {f}"] = float(pred[m].mean())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycles", type=int, default=16, help="drive cycles per real capture (default 16)")
    ap.add_argument("--no-curve", action="store_true", help="skip the 2x/4x training-data check")
    ap.add_argument("--per-class", type=int, default=300,
                    help="training samples per component and health (default 300, as in the 2026-11-28 run)")
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore")
    sys.stdout.reconfigure(line_buffering=True)               # progress shows even when redirected

    t0 = time.time()
    X, comp, health = train.build_xy(n_good=args.per_class, n_faulty=args.per_class)   # train.py's split
    strat = np.array([f"{c}_{h}" for c, h in zip(comp, health)])
    tr, _ = train_test_split(np.arange(len(X)), test_size=0.25, stratify=strat, random_state=42)
    Xtr, ytr = X[tr], health[tr]
    Xs, cs, ys, fs = synth_xy(400, 800, seed=1)              # unseen, as eval_synth.py
    Xr, rows = real_xy(args.cycles)
    print(f"data: train {len(Xtr)} (seed 0, {args.per_class} per class, train.py split) | unseen synth {len(Xs)} (seed 1) | "
          f"real {len(rows)} captures  [{time.time() - t0:.0f} s]\n")

    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    fitted, table = {}, {}
    for name, (est, grid) in candidates().items():
        t = time.time()
        if grid:
            gs = GridSearchCV(est, grid, cv=cv, scoring="accuracy", n_jobs=-1).fit(Xtr, ytr)
            model, cv_acc, best = gs.best_estimator_, gs.best_score_, gs.best_params_
        else:
            model, cv_acc, best = est.fit(Xtr, ytr), np.nan, {}
        if name.startswith("SVM"):                           # probabilities for p_faulty (Platt)
            model.set_params(clf__probability=True, clf__random_state=0).fit(Xtr, ytr)
        fitted[name] = model
        s = scores(model, Xs, cs, ys, fs)
        s["train"], s["cv"] = accuracy_score(ytr, model.predict(Xtr)), cv_acc
        pr = model.predict(Xr)
        scored = [k for k, r in enumerate(rows) if r["health"] in ("good", "faulty")]
        s["real"] = sum(pr[k] == (rows[k]["health"] == "faulty") for k in scored)
        s["real_n"] = len(scored)
        table[name] = s
        shown = {k: scaler_name(v) for k, v in best.items()}
        print(f"{name:18s} {time.time() - t:5.0f} s  best {shown}")

    names = list(table)
    print("\nunseen synthetic set (7,200) — recall of FAULTY per fault, and good parts called GOOD")
    cols = ["acc", "mcc", "good"] + [f"{c} {f}" for c, f in FAULT_ORDER]
    print(f"{'':18s}" + "".join(f"{c[:13]:>14s}" for c in cols))
    for n in names:
        print(f"{n:18s}" + "".join(f"{table[n][c]:14.3f}" for c in cols))
    print(f"\n{'':18s}{'train acc':>12s}{'CV acc':>10s}{'unseen acc':>12s}{'real right':>12s}")
    for n in names:
        s = table[n]
        print(f"{n:18s}{s['train']:12.3f}{s['cv']:10.3f}{s['acc']:12.3f}{s['real']:>9d}/{s['real_n']}")

    print("\nreal boundary captures (kept, not scored) — p_faulty per model")
    print(f"{'capture':40s}" + "".join(f"{n[:12]:>13s}" for n in names))
    for k, r in enumerate(rows):
        if r["health"] == "boundary":
            print(f"{r['file'][11:-4]:40s}" + "".join(f"{p_faulty(fitted[n], Xr[k:k + 1])[0]:13.2f}" for n in names))
    wrong = {n: [rows[k]["file"][11:-4] for k, p in enumerate(fitted[n].predict(Xr))
                 if rows[k]["health"] in ("good", "faulty") and p != (rows[k]["health"] == "faulty")]
             for n in names}
    for n in names:
        if wrong[n]:
            print(f"  {n}: wrong on {', '.join(wrong[n])}")

    if args.no_curve:
        return
    other = max((n for n in names if not n.startswith("RF")), key=lambda n: table[n]["acc"])
    weak = FAULT_ORDER[:4]
    print(f"\nmore training data (fresh seed-3 sets, all used for training) — RF (train.py) vs {other}")
    print(f"{'':20s}{'n train':>8s}{'acc':>8s}{'good':>8s}" + "".join(f"{c + ' ' + f:>17s}" for c, f in weak)
          + f"{'real right':>12s}")

    def curve_row(n, model, n_train, s):
        right = sum(p == (rows[k]["health"] == "faulty") for k, p in enumerate(model.predict(Xr))
                    if rows[k]["health"] in ("good", "faulty"))
        print(f"{n:20s}{n_train:8d}{s['acc']:8.3f}{s['good']:8.3f}"
              + "".join(f"{s[f'{c} {f}']:17.3f}" for c, f in weak) + f"{right:>9d}/{table[n]['real_n']}")

    from sklearn.base import clone
    for n in ("RF (train.py)", other):
        curve_row(n, fitted[n], len(Xtr), table[n])
    for n_per in (600, 1200):
        Xb, _, yb, _ = synth_xy(n_per, n_per, seed=3)
        for n in ("RF (train.py)", other):
            model = clone(fitted[n]).fit(Xb, yb)
            curve_row(n, model, len(Xb), scores(model, Xs, cs, ys, fs))
    print(f"\ntotal {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()

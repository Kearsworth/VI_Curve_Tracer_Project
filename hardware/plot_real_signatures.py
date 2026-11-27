"""
plot_real_signatures.py — real Case 1 captures as the model sees them (the README figure).

Each panel is one labelled capture from hardware/captures, run through the same path as
eval_real.py: reader (zero-cal, reference drift, per-channel gains, drive-phase alignment) ->
calibrate.calibrate (360 points indexed by drive phase, V/A against I*Rr/A) -> verify.

    python3 hardware/plot_real_signatures.py        # writes docs/images/real_signatures.png
"""
import os
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "vi_ml"))
import calibrate  # noqa: E402
import eval_real  # noqa: E402
import verify  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images", "real_signatures.png")
PANELS = [                                     # (capture, title)
    ("2026-11-27_1k_R988.txt", "Resistor 988 Ω"),
    ("2026-11-27_1k_C100n.txt", "Capacitor 0.1 µF"),
    ("2026-11-27_1k_D1N4148_fwd.txt", "Diode 1N4148"),
    ("2026-11-27_mf1k_LED_fwd_ref.txt", "LED"),
    ("2026-11-27_1k_open.txt", "Open"),
    ("2026-11-27_1k_short.txt", "Short"),
    ("2026-11-27_1k_C100n_par_2k.txt", "Leaky capacitor (‖ 2 kΩ)"),
    ("2026-11-27_mf1k_LED_rev.txt", "LED reversed"),
]
GREEN, RED = "#1b7f3b", "#c0392b"


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    rows = {r["file"]: r for r in eval_real.load_labels()}
    fig, axes = plt.subplots(2, 4, figsize=(13, 7))
    for ax, (name, title) in zip(axes.flat, PANELS):
        row = rows[name]
        raw = eval_real.raw_for(row)
        sig = calibrate.calibrate(raw)
        verdict = verify.verify(raw)["verdict"]
        truth = "GOOD" if row["health"] == "good" else "FAULTY"
        colour = GREEN if verdict == "GOOD" else RED
        ax.plot(sig[:, 0], sig[:, 1], color=colour, lw=2)
        ax.axhline(0, color="#999", lw=0.6)
        ax.axvline(0, color="#999", lw=0.6)
        ax.set_xlim(-1.15, 1.15)
        ax.set_ylim(-1.15, 1.15)
        ax.set_aspect("equal")
        ax.set_xticks([-1, 0, 1])
        ax.set_yticks([-1, 0, 1])
        ax.set_title(title, fontsize=12, fontweight="bold")
        mark = "✓" if verdict == truth else "✗"
        ax.text(0.03, 0.95, f"model: {verdict} {mark}", transform=ax.transAxes, va="top",
                fontsize=10, color=colour, fontweight="bold")
    for ax in axes[1]:
        ax.set_xlabel("V / A")
    for ax in axes[:, 0]:
        ax.set_ylabel("I · Rr / A")
    fig.suptitle("Real V-I signatures from the Case 1 board (1 kHz, Rr 1 kΩ) and the model's verdicts",
                 fontsize=13)
    fig.tight_layout()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=110)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

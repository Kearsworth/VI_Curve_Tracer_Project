"""
stage0_check.py — Stage 0 of docs/STANDALONE_TESTER_PLAN.md: simulate the standalone front
end in ngspice for every Rr x DUT case and check each node against its limit.

Run:  python3 hardware/sim/stage0_check.py        (needs `ngspice` on PATH: brew install ngspice)

Models are deliberately simple: the op-amp is an ideal amplifier clamped at the NE5532's
approximate output swing on +-9 V rails (+-7.5 V), so the current check below is the real
limit to watch, not the model. Rails come from ideal sources (MT3608 / ICL7660S not modeled).
"""
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

# ---- design values (keep in sync with docs/STANDALONE_TESTER_PLAN.md) ----
DAC_BIAS, DAC_AMP = 1.65, 104 * 3.3 / 255  # ESP32 DAC sine: 128 +- 104 counts (levelled to A = 5.0 V)
GAIN_RG, GAIN_RF = 10e3, 27e3            # non-inverting gain 1 + Rf/Rg = 3.7 -> A = 4.98 V
C_COUPLE, R_BIAS = 1e-6, 100e3           # AC coupling (tau = 0.1 s)
RP_IN, RP_UP, RP_DN, C_PIN = 100e3, 56e3, 56e3, 1e-9   # return path per channel
OPAMP_SWING, OPAMP_IMAX = 7.5, 0.030     # NE5532 on +-9 V: ~+-7.5 V swing, keep |I| <= ~30 mA
ADC_OK = (0.15, 2.45)                    # Espressif: ESP32 ADC accurate range at 11/12 dB atten

MODELS = """
.model D1N4148 D(Is=2.52n Rs=0.568 N=1.752 Cjo=4p M=0.4 tt=20n Bv=100)
.model LEDRED D(Is=1e-22 N=1.6 Rs=2 Cjo=20p Bv=30)
"""
DUTS = {          # name -> (spice line between nodes a and b, drive frequency, |Z| at that frequency or None)
    "open":   ("Rdut a b 1e12", 50, None),
    "short":  ("Rdut a b 1m", 50, None),
    "R 1k":   ("Rdut a b 1k", 50, None),
    "1N4148": ("Ddut a b D1N4148", 50, None),
    "LED":    ("Ddut a b LEDRED", 50, None),
    "C 100n": ("Cdut a b 100n", 1000, 1 / (2 * 3.14159265 * 1000 * 100e-9)),   # ~1.59 kOhm
    "L 100m": ("Ldut a b 100m", 1000, 2 * 3.14159265 * 1000 * 100e-3),         # ~628 Ohm
}
MISMATCH = 20     # Rr/|Z| above this gives a degenerate signature; auto-range must never pick it
RR_BANK = [220, 1e3, 10e3, 100e3]


def netlist(dut_line, freq, rr):
    t_settle = 0.5                       # 5 x tau of the 1 uF / 100 k coupling network
    t_end = t_settle + 2.0 / freq
    return f"""stage0
Vdac dac 0 SIN({DAC_BIAS} {DAC_AMP} {freq})
Cc dac inp {C_COUPLE} IC={DAC_BIAS}
Rb inp 0 {R_BIAS}
Rg inn 0 {GAIN_RG}
Rf o inn {GAIN_RF}
Bop o 0 V = max(min(1e5*(V(inp)-V(inn)), {OPAMP_SWING}), {-OPAMP_SWING})
Vimeas o a 0
Vdm a ad 0
{dut_line.replace(" a b ", " ad b ")}
Rr b 0 {rr}
V33 v33 0 3.3
R1a a p1 {RP_IN}
R2a p1 v33 {RP_UP}
R3a p1 0 {RP_DN}
Cpa p1 0 {C_PIN}
R1b b p2 {RP_IN}
R2b p2 v33 {RP_UP}
R3b p2 0 {RP_DN}
Cpb p2 0 {C_PIN}
{MODELS}
.control
set wr_singlescale
tran {1 / freq / 400} {t_end} {t_settle} uic
wrdata {{OUT}} v(a) v(b) v(p1) v(p2) i(vimeas) i(vdm)
.endc
.end
"""


# Return-path loading seen from a measured node: Thevenin of the 3-resistor network
RP_VTH = 3.3 * RP_DN / (RP_UP + RP_DN)
RP_RTH = RP_IN + RP_UP * RP_DN / (RP_UP + RP_DN)


def run(dut_line, freq, rr):
    d = tempfile.mkdtemp()
    cir, out = os.path.join(d, "s.cir"), os.path.join(d, "s.txt")
    with open(cir, "w") as f:
        f.write(netlist(dut_line, freq, rr).replace("{OUT}", out))
    log = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True)
    if not os.path.exists(out):
        sys.exit(f"ngspice failed:\n{log.stdout[-1500:]}{log.stderr[-800:]}")
    t, va, vb, p1, p2, iop, idut = np.loadtxt(out).T
    i_est = vb / rr + (vb - RP_VTH) / RP_RTH        # what software will compute from V_B
    full_scale = 5.0 / rr
    return dict(amax=va.max(), amin=va.min(), bmax=vb.max(), bmin=vb.min(),
                p1max=p1.max(), p1min=p1.min(), p2max=p2.max(), p2min=p2.min(),
                imax=iop.max(), imin=iop.min(),
                ierr=np.max(np.abs(i_est - idut)) / full_scale,
                ierr_naive=np.max(np.abs(vb / rr - idut)) / full_scale)


def main():
    print(f"{'DUT':8s} {'Rr':>7s} | {'V(A) pk':>8s} {'V(B) pk':>8s} | {'ADC34 range':>13s} {'ADC35 range':>13s} | {'I pk mA':>7s} | {'I err':>6s} {'naive':>6s} | result")
    print("-" * 108)
    fails = 0
    skipped = 0
    for name, (line, freq, z) in DUTS.items():
        for rr in RR_BANK:
            r = run(line, freq, rr)
            ipk = max(abs(r["imax"]), abs(r["imin"]))
            problems = []
            for ch in ("p1", "p2"):
                lo, hi = r[ch + "min"], r[ch + "max"]
                if lo < 0 or hi > 3.3:
                    problems.append(f"{ch} OUTSIDE 0-3.3V")
                elif lo < ADC_OK[0] - 1e-3 or hi > ADC_OK[1] + 1e-3:
                    problems.append(f"{ch} outside accurate range")
            if max(abs(r["amax"]), abs(r["amin"])) > OPAMP_SWING - 0.05:
                problems.append("op-amp clipping")
            if ipk > OPAMP_IMAX:
                problems.append(f"current {ipk*1e3:.0f} mA > {OPAMP_IMAX*1e3:.0f} mA")
            if r["ierr"] > 0.01:
                problems.append(f"corrected current error {r['ierr']*100:.1f}% of A/Rr")
            if problems and z and rr / z > MISMATCH:
                problems = [f"excluded: Rr/|Z| = {rr / z:.0f} (auto-range never selects) — " + "; ".join(problems)]
                skipped += 1
            else:
                fails += bool(problems)
            rr_s = {220: "220", 1e3: "1k", 10e3: "10k", 100e3: "100k"}[rr]
            print(f"{name:8s} {rr_s:>7s} | {max(r['amax'], -r['amin']):8.3f} {max(r['bmax'], -r['bmin']):8.3f} | "
                  f"{r['p1min']:5.3f}–{r['p1max']:5.3f}  {r['p2min']:5.3f}–{r['p2max']:5.3f}  | {ipk*1e3:7.2f} | {r['ierr']*100:5.2f}% {r['ierr_naive']*100:5.1f}% | "
                  f"{'OK' if not problems else '; '.join(problems)}")
    print("-" * 108)
    print("I err = DUT-current error after the return-path correction, naive = plain V_B/Rr (both as % of 5 V/Rr)")
    print(("ALL CASES PASS" if not fails else f"{fails} case(s) need attention")
          + (f" ({skipped} mismatched setting(s) excluded, see rows marked 'excluded')" if skipped else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

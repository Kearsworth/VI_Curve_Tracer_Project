"""sim_r_error.py — does the digital/timing chain of case1_frontend_mf explain the ~1 % R error at
91-333 Hz (docs/CASE1_WIRING.md, ADC step 3)?   python3 hardware/sim/sim_r_error.py   (~1 s)

Simulates, for a resistor R = Rr, everything the firmware does in time:
  DAC staircase (LUT 100 steps, value at mid-step, inverted, 8-bit codes), drive gain 5.92,
  node B = node A * Rr / (R + Rr), divider g/offset per channel, RC at the ADC pin (tau 0.88 us),
  ADC conversions every 10 us alternating node A / node B, 12-bit quantization + noise,
  optional charge-sharing crosstalk from the previous conversion, M pairs per point,
  trapezoid V, labels at the mean time, lock-in Z over whole cycles.
Burst start relative to the DAC steps is random, as on the board. Prints |Z|/R - 1 and the angle per M.

Result (2026-11-28): no. The ideal chain is within ~0.2 % at M >= 3 (only burst-to-burst scatter, and
-0.4 +- 0.4 % at M = 1); the measured crosstalk (0.2 %) adds the same -0.6 % at every M; 2 us of DAC
update jitter changes nothing. The measured error peaks at 91-333 Hz and is ~0 at <= 30 Hz, so its
cause is outside this model: the analog side or the ADC's own conversion behaviour.
"""
import numpy as np

TAU = 8.84e3 * 100e-12 * 1e6          # RC at the ADC pin, in us (100 pF fitted now)
G_A, G_B, OFF = 0.08844, 0.08802, 1.515
VPC = 3.3 / 4095
GAIN = 5.92
DAC_MV = 12.7e-3


def dac_levels():
    i = np.arange(100)
    code = 132 - np.round(63 * np.sin(2 * np.pi * (i + 0.5) / 100))
    return -GAIN * (code - 132) * DAC_MV           # node A level per step (inverting stage), V


def node_a(t_us, period_us, levels):
    """Staircase through the pin RC: last step plus the decaying remainder of the one before."""
    step = period_us / 100
    k = np.floor(t_us / step).astype(np.int64)
    dt = t_us - k * step
    now = levels[k % 100]
    prev = levels[(k - 1) % 100]
    return now + (prev - now) * np.exp(-dt / TAU)


def run(M, rng, cycles=16, noise_counts=8.0, xtalk=0.0, r_over_rr=1.0, step_jitter_us=0.0):
    period = 1000.0 * M
    levels = dac_levels()
    n_pts = cycles * 50
    n_conv = 2 * M * n_pts + 2
    t0 = rng.uniform(0, period)                     # burst start vs the drive, random
    t = t0 + 10.0 * np.arange(n_conv)
    tj = t + rng.normal(0, step_jitter_us, n_conv) if step_jitter_us else t
    a = node_a(tj, period, levels)
    b = a / (1 + r_over_rr)
    pin = np.where(np.arange(n_conv) % 2 == 0, G_A * a + OFF, G_B * b + OFF)
    if xtalk:
        pin[1:] = pin[1:] + xtalk * (pin[:-1] - pin[1:])
    counts = np.round(pin / VPC + rng.normal(0, noise_counts, n_conv))
    v_raw, i_raw = counts[0::2], counts[1::2]
    vp, ip, tp = [], [], []
    for j in range(n_pts):
        s = j * M
        vs = v_raw[s:s + M + 1]
        w = np.ones(M + 1); w[0] = w[-1] = 0.5
        vp.append(np.sum(w * vs) / M)
        ip.append(np.mean(i_raw[s:s + M]))
        tp.append(t[2 * s] + 10.0 * M)              # mean time of the point
    vp, ip, tp = np.array(vp), np.array(ip), np.array(tp)
    phase = 2 * np.pi * (tp % period) / period
    na = (vp * VPC - OFF) / G_A
    nb = (ip * VPC - OFF) / G_B
    v, i = na - nb, nb                              # V_DUT, I * Rr
    e = np.exp(-1j * phase)
    z = np.mean(v * e) / np.mean(i * e)             # in units of Rr
    return abs(z) / r_over_rr - 1, np.degrees(np.angle(z))


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    measured = {1: (+0.7, +0.29), 3: (-1.2, +1.10), 11: (-0.8, -0.53), 33: (-0.1, -0.30), 101: (+0.2, -0.12)}
    for label, kw in (("ideal chain", {}), ("+ crosstalk 0.2 %", dict(xtalk=0.002)),
                      ("+ 2 us DAC-update jitter", dict(step_jitter_us=2.0))):
        print(label)
        for M in (1, 3, 11, 33, 101):
            res = np.array([run(M, rng, **kw) for _ in range(8)])
            m, s = res.mean(0), res.std(0)
            print(f"  M={M:4d} ({1000 / M:6.1f} Hz): |Z| error {100 * m[0]:+.3f} % (±{100 * s[0]:.3f}),"
                  f" angle {m[1]:+.3f}° (±{s[1]:.3f})   measured {measured[M][0]:+.1f} %, {measured[M][1]:+.2f}°")

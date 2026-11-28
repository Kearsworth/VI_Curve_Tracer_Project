"""
synth.py — ตัวสร้างข้อมูลสังเคราะห์ (synthetic data generator)
================================================================
สร้าง "ข้อมูลดิบเสมือน" ที่จำลองว่าเครื่อง V-I curve tracer ส่งมาให้ สำหรับอุปกรณ์
พื้นฐาน 6 ชนิด ทั้งสภาพดีและเสีย ใช้เป็นชุดข้อมูลสำหรับเทรนและทดสอบโมเดล ML

อุปกรณ์ 6 ชนิด:
  R   = ตัวต้านทาน
  C   = ตัวเก็บประจุ
  L   = ตัวเหนี่ยวนำ
  D   = ไดโอด (ซิลิคอน + Schottky)
  LED = ไดโอดเปล่งแสง (สีแดง..ขาว/น้ำเงิน)
  Z   = ซีเนอร์ไดโอด

เอาต์พุตของ generate_sample() คือ dict ที่เลียนแบบสิ่งที่ tracer ส่งมา:
  {'v': ..., 'i': ..., 'phase': ..., 'A': ..., 'Rr': ...}
โดย v,i,phase เป็นอาเรย์ของตัวอย่างดิบ (หลายรอบ มี noise) และ A,Rr คือ
ค่าตั้งเครื่อง (แอมพลิจูดขับ, ตัวต้านทานช่วง) ที่ tracer แนบมาด้วย
(คีย์ component/health/fault/F/value เป็น label/ข้อมูลประกอบของ synth เท่านั้น)

เปลี่ยน 2026-11-27 — จาก "ค่าเดียวต่อชนิด" เป็น "ทุกค่า" (เป้าโปรเจกต์: บอกได้ว่าอุปกรณ์เสีย
ไม่ว่าค่าจะเท่าไร):
  1) ค่าอุปกรณ์สุ่มแบบ log-uniform ทั้งช่วง (R 100 Ω–300 kΩ, C 1 nF–1000 µF, L 10 mH–10 H)
     แล้วจำลอง "auto-range" แบบที่เครื่องจริงต้องทำ: เลือกความถี่ขับ F และ Rr ให้ |Z|/Rr
     อยู่ราว 1 (วงรีเปิดให้เห็น) — หลัง normalize ใน calibrate.py (V/A, I·Rr/A) ค่าสัมบูรณ์
     หายไป เหลือแค่ |Z|/Rr กับสัดส่วนความสูญเสีย (ESR/X, Rleak/X, Q) ที่กำหนดรูป
  2) fault นิยามเทียบกับ "สเกลของตัวมันเอง" (เช่น ESR = 0.1–0.75×X_C) ไม่ใช่โอห์มตายตัว
  3) แบบจำลองการวัดของบอร์ด Case 1 จริง: วัดที่ node A / node B แยกกัน (V = A−B, I = B/Rr),
     noise/offset/quantization ต่อ node, crosstalk ADC, skew ระหว่างช่อง, 40–60 จุดต่อรอบ
     และ spike ของ ADC (ค่ามาจากการวัด 2026-11-26, docs/CASE1_WIRING.md) — สุ่มเป็นช่วงให้ครอบ
     สภาพบอร์ดจริง
  4) Zener: fault 'vz_shift' -> 'leak' เพราะเมื่อ Vz สุ่มทั้งช่วง การเลื่อน Vz คือ "ค่าเพี้ยน"
     ซึ่งแยกจากของดีค่าอื่นไม่ได้ด้วยรูปทรง (CLAUDE.md design decision #5)
"""

import numpy as np

VT = 0.02585           # thermal voltage ที่อุณหภูมิห้อง (โวลต์)
NG = 720               # ความละเอียดของกริดเฟส "อุดมคติ" (จุดต่อรอบ)

COMPONENTS = ['R', 'C', 'L', 'D', 'LED', 'Z']

# เมนู fault ของแต่ละชนิด (เฉพาะ fault ที่ "เปลี่ยนรูปทรง" ของ signature จึงตรวจจับ
# ได้จากภาพลายเซ็นโดยตรง — การเพี้ยนค่าต้องใช้ reference เทียบ ไม่รวมในนี้)
FAULTS = {
    'R':   ['open', 'short'],
    'C':   ['open', 'short', 'esr', 'leak'],
    'L':   ['open', 'short', 'dcr', 'shorted_turns'],
    'D':   ['open', 'short', 'reversed', 'degraded'],
    'LED': ['open', 'short', 'reversed', 'degraded'],
    'Z':   ['open', 'short', 'reversed', 'leak'],
}

# ----------------------------------------------------------------------------
# เงื่อนไขทดสอบที่เครื่องเลือกได้ (auto-range)
# ----------------------------------------------------------------------------
# หลัง normalize รูป signature ของ R/C/L ขึ้นกับ |Z|/Rr ที่เงื่อนไขที่เลือกเท่านั้น สองรายการนี้
# จึงกำหนดแค่ว่า "ค่าไหนอยู่ในช่วงวัดได้" — เฟิร์มแวร์ขยับความถี่ออกจากพหุคูณของ 50 Hz ได้
# โดยไม่ต้องเทรนใหม่
# = ความถี่ที่ firmware case1_frontend_mf ทำได้จริง: 1000/M Hz (M = 1, 3, 11, 33, 101, 333, 1000), เลี่ยง
# พหุคูณของ 50 Hz; hardware/autorange.py เลือกจากรายการเดียวกันนี้ด้วย auto_range() ตัวเดียวกัน
TEST_DECIM = (1, 3, 11, 33, 101, 333, 1000)
TEST_FREQS_HZ = tuple(1000.0 / m for m in TEST_DECIM)   # สูง -> ต่ำ (ชอบความถี่สูง: จับเร็ว)
RR_OPTIONS = (220.0, 1000.0, 10000.0, 100000.0)   # บอร์ดมี 220/1k/10k/100k (สายเลือก Rr) — ค่าระบุ
RANGE_BAND = (0.5, 2.0)                           # ยอมรับ |Z|/Rr ในช่วงนี้
DEFAULT_F, DEFAULT_RR = 1000.0, 1000.0            # สารกึ่งตัวนำ + การมองครั้งแรก

VALUE_RANGE = {'R': (100.0, 300e3), 'C': (1e-9, 1e-3), 'L': (10e-3, 10.0)}

# ----------------------------------------------------------------------------
# แบบจำลองการวัด (บอร์ด Case 1 จริง, วัด 2026-11-26)
# ----------------------------------------------------------------------------
HW = dict(
    A_range=(4.0, 6.0),          # แอมพลิจูดที่ node A (V peak)
    node_lsb_v=0.0091,           # 1 count ADC ที่ node A/B (0.806 mV / gain divider 0.0882)
    noise_counts=(3.0, 14.0),    # σ noise ต่อ node ต่อจุด (วัดได้ 9.4 / 11 count ตอน C5/C6 = 100 pF)
    offset_frac=0.006,           # σ offset DC ค้างหลัง zero-cal ต่อ node (สัดส่วนของ A)
    crosstalk=(0.0, 0.005),      # node B รับสัญญาณ node A มาเป็นสัดส่วนนี้: firmware DMA วัดได้ 0.07–0.2 %
                                 # (polling รุ่นเก่า ~4 %; ค่าเดิม 0–3 % กลบ soft fault ของ C — 2026-11-28)
    crosstalk_phase_deg=(0.0, 15.0),
    skew_deg=0.75,               # σ ความเหลื่อมเวลาของช่อง B เทียบ A: firmware DMA < 1 µs ตอนช็อต, มุมเพี้ยนบน R
                                 # 0.3–0.6° ที่ 1 kHz (สูงสุด 1.1° ที่ 333 Hz); polling 50 Hz รุ่นเก่า ~2.5°
    phase_offset_deg=5.0,        # เฟสที่ติดป้ายเหลื่อมจากคลื่นจริง ±ค่านี้ (DAC/RC delay)
    amp_err=0.02,                # σ ความคลาดของ A ที่วัดได้
    samples_per_cycle=(40, 60),
    cycles=(8, 24),
    locked_prob=0.8,             # บอร์ดจริงสุ่มตัวอย่างล็อกกับเฟส: 50 จุด/รอบ ตกที่เฟสเดิมทุกรอบ (วัด 2026-11-27:
                                 # 1 kHz เติม 50 จาก 360 bin, 50 Hz เติม 58) -> ส่วนใหญ่ไม่มี drift
    rate_drift=0.002,            # ที่เหลือ: อัตราสุ่มไม่ลงตัวกับรอบ -> เฟสไหลช้า ๆ เติม bin
    jitter_deg=0.3,              # σ ความคลาดเวลาสุ่มตัวอย่างแต่ละจุด (timestamp jitter ~1.4 µs ที่ 1 kHz)
    spike_rate=(0.0, 0.01),      # สัดส่วนจุดที่ ADC กระโดด (วัดจริง ~0.5% ของจุดเกิน 5σ)
    spike_counts=(40.0, 110.0),  # ขนาด spike (วัดจริงสูงสุด ~70–100 count)
)


def _loguniform(rng, lo, hi):
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


# ----------------------------------------------------------------------------
# ฟังก์ชันกระแสของอุปกรณ์ไม่เชิงเส้น: คืน (I, dI/dVd) เพื่อใช้แก้ด้วย Newton
# ----------------------------------------------------------------------------
def _diode(Vd, Is, n):
    x = np.clip(Vd / (n * VT), -60, 60)
    e = np.exp(x)
    return Is * (e - 1.0), Is / (n * VT) * e

def _zener(Vd, Is, n, Vz, nz, Isz=1e-9):
    If, dIf = _diode(Vd, Is, n)
    xr = np.clip(-(Vd + Vz) / (nz * VT), -60, 60)
    er = np.exp(xr)
    Ir = -Isz * (er - 1.0)
    dIr = Isz / (nz * VT) * er
    return If + Ir, dIf + dIr

def _solve_loadline(Vs, Rtot, cur_fn, iters=60):
    """แก้สมการ load line: Vs = I*Rtot + Vd หา Vd ทุกจุดด้วย Newton (เวกเตอร์)"""
    Vd = np.zeros_like(Vs)
    for _ in range(iters):
        I, dI = cur_fn(Vd)
        f = Vs - Vd - Rtot * I
        fp = -1.0 - Rtot * dI
        Vd = Vd - np.clip(f / fp, -2.0, 2.0)
    return Vd

def _Is_for_vf(Vf, n, i_ref=1e-3):
    """คำนวณ Is ให้หัวเข่าอยู่ที่แรงดัน Vf โดยประมาณ (ที่กระแสอ้างอิง i_ref)"""
    return i_ref * np.exp(-Vf / (n * VT))


# ----------------------------------------------------------------------------
# อุปกรณ์เชิงเส้น + auto-range
# ----------------------------------------------------------------------------
def _z_linear(comp, p, f):
    """อิมพีแดนซ์เชิงซ้อนของ R/C/L (พร้อมความสูญเสีย) ที่ความถี่ f"""
    w = 2 * np.pi * f
    if comp == 'R':
        return complex(p['R'], 0.0)
    if comp == 'C':
        z = 1.0 / (1j * w * p['C']) + p.get('esr', 0.0)
        if p.get('rleak'):
            z = 1.0 / (1.0 / z + 1.0 / p['rleak'])
        return z
    return 1j * w * p['L'] + p.get('rs', 0.0)


def auto_range(zfun):
    """
    เลือก (F, Rr) แบบที่เครื่องควรทำ: ไล่จากความถี่สูงไปต่ำ เอาคู่แรกที่ |Z|/Rr อยู่ใน RANGE_BAND
    ถ้าไม่มีคู่ไหนเข้าช่วง (ค่าอยู่นอกช่วงวัด) เอาคู่ที่ใกล้ 1 ที่สุด
    """
    best, best_score = (DEFAULT_F, DEFAULT_RR), np.inf
    for f in TEST_FREQS_HZ:
        zf = abs(zfun(f))
        for rr in RR_OPTIONS:
            r = zf / rr
            if RANGE_BAND[0] <= r <= RANGE_BAND[1]:
                return f, rr
            score = abs(np.log(r)) if 0 < r < np.inf else np.inf
            if score < best_score:
                best, best_score = (f, rr), score
    return best


def _linear_ideal(comp, fault, rng, A, g):
    lo, hi = VALUE_RANGE[comp]
    value = _loguniform(rng, lo, hi)
    p = {comp: value}

    # สเกลของตัวมันเอง: เงื่อนไขที่เครื่องจะเลือกให้ "ของดีค่านี้"
    f0, _ = auto_range(lambda f: _z_linear(comp, p, f))
    if comp == 'C':
        x0 = 1.0 / (2 * np.pi * f0 * value)
        p['esr'] = x0 * _loguniform(rng, 1e-3, 0.06)           # ของดี: DF ≤ 6% (เซรามิก class II วัดจริงได้ ~4–5%)
        if fault == 'esr':
            p['esr'] = x0 * rng.uniform(0.12, 0.75)
        elif fault == 'leak':
            p['rleak'] = x0 * rng.uniform(1.25, 12.5)
    elif comp == 'L':
        q = _loguniform(rng, 8.0, 100.0)                        # ของดี: Q สูง
        if fault == 'dcr':
            q = rng.uniform(0.4, 2.1)
        elif fault == 'shorted_turns':
            p['L'] = value * rng.uniform(0.2, 0.4)              # รอบลัด: L ลด + สูญเสียเพิ่ม
            q = rng.uniform(1.0, 3.0)
        p['rs'] = 2 * np.pi * f0 * p['L'] / q

    # เครื่องไม่รู้ค่าระบุ: auto-range จากสิ่งที่เห็นจริง (ตัวที่อาจเสียแล้ว)
    F, Rr = auto_range(lambda f: _z_linear(comp, p, f))
    Zd = _z_linear(comp, p, F)
    Iph = A / (Rr + Zd)                                         # เฟเซอร์กระแส
    i = np.imag(Iph * np.exp(1j * g))
    v = np.imag(Iph * Zd * np.exp(1j * g))
    return v, i, Rr, F, value


def _nonlinear_ideal(comp, fault, rng, A, g):
    Vs = A * np.sin(g)
    Rr = DEFAULT_RR
    if comp == 'D':
        if rng.random() < 0.25:                                 # Schottky
            Vf, n = rng.uniform(0.25, 0.45), rng.uniform(1.0, 1.4)
        else:                                                   # ซิลิคอน
            Vf, n = rng.uniform(0.55, 0.75), rng.uniform(1.5, 2.0)
    elif comp == 'LED':
        Vf, n = rng.uniform(1.6, 3.2), rng.uniform(2.0, 3.0)    # แดง .. น้ำเงิน/ขาว
    else:
        Vf, n = rng.uniform(0.6, 0.75), rng.uniform(1.5, 2.0)
    Is = _Is_for_vf(Vf, n)
    Rs = rng.uniform(200, 800) if fault == 'degraded' else 0.0  # เสื่อม = ความต้านทานอนุกรมสูง

    value = Vf
    if comp == 'Z':
        Vz = rng.uniform(2.4, min(5.1, A / 1.3))                # ต้องให้ A > ~1.3 Vz จึงเห็นเข่า
        value = Vz
        nz = rng.uniform(1.5, 2.5)
        if fault == 'leak':                                     # รอยต่อรั่ว: R ขนาน
            Rp = rng.uniform(2000, 20000)
            base = lambda vd: (lambda I, dI: (I + vd / Rp, dI + 1.0 / Rp))(*_zener(vd, Is, n, Vz, nz))
        else:
            base = lambda vd: _zener(vd, Is, n, Vz, nz)
    else:
        base = lambda vd: _diode(vd, Is, n)

    if fault == 'reversed':
        cur = lambda vd: (lambda I, dI: (-I, dI))(*base(-vd))   # กลับขั้ว: I(vd) = -base(-vd)
    else:
        cur = base

    Vd = _solve_loadline(Vs, Rr + Rs, cur)
    I, _ = cur(Vd)
    v = Vs - I * Rr                                             # แรงดันคร่อม DUT (รวม Rs ภายใน)
    return v, I, Rr, DEFAULT_F, value


# ----------------------------------------------------------------------------
# สร้าง signature อุดมคติ (v, i) บนกริดเฟส NG จุด — หน่วยฟิสิกส์จริง
# ----------------------------------------------------------------------------
def generate_ideal(component, health, rng, A=5.0):
    """คืน (v, i, fault, Rr, F, value) บนกริด NG จุด ที่แอมพลิจูดขับ A"""
    g = np.linspace(0, 2 * np.pi, NG, endpoint=False)
    Vs = A * np.sin(g)
    fault = rng.choice(FAULTS[component]) if health == 'faulty' else None

    # --- open / short เหมือนกันทุกชนิด (auto-range ไปสุดช่วงแล้วยังเป็นเส้นตรง) ---
    if fault == 'open':
        return Vs.copy(), np.zeros_like(Vs), fault, RR_OPTIONS[-1], DEFAULT_F, np.nan
    if fault == 'short':
        return np.zeros_like(Vs), Vs / RR_OPTIONS[0], fault, RR_OPTIONS[0], DEFAULT_F, np.nan

    if component in ('R', 'C', 'L'):
        v, i, Rr, F, value = _linear_ideal(component, fault, rng, A, g)
    else:
        v, i, Rr, F, value = _nonlinear_ideal(component, fault, rng, A, g)
    return v, i, fault, Rr, F, value


# ----------------------------------------------------------------------------
# จำลอง "การเก็บข้อมูลดิบ" ผ่าน front end Case 1 (node A / node B -> ADC)
# ----------------------------------------------------------------------------
def generate_sample(component, health, rng, n_raw=None, n_cycles=None):
    hw = HW
    A = rng.uniform(*hw['A_range'])
    v_ideal, i_ideal, fault, Rr, F, value = generate_ideal(component, health, rng, A)
    g = np.linspace(0, 2 * np.pi, NG, endpoint=False)
    node_a = A * np.sin(g)                  # ไดรฟ์ (follower C อ่าน)
    node_b = i_ideal * Rr                   # คร่อม Rr (follower D อ่าน);  v_ideal = node_a − node_b

    if n_cycles is None:
        n_cycles = int(rng.integers(hw['cycles'][0], hw['cycles'][1] + 1))
    if n_raw is None:
        n_raw = n_cycles * int(rng.integers(hw['samples_per_cycle'][0], hw['samples_per_cycle'][1] + 1))
    locked = rng.random() < hw['locked_prob']
    drift = 1.0 if locked else 1.0 + rng.uniform(-hw['rate_drift'], hw['rate_drift'])
    start = rng.uniform(0, 2 * np.pi)                     # เฟสของจุดแรกไม่แน่นอน
    drive_phase = start + (2 * np.pi * n_cycles * drift / n_raw) * np.arange(n_raw)   # เฟสที่ "รู้" จากนาฬิกา
    deg = np.pi / 180
    off = rng.uniform(-hw['phase_offset_deg'], hw['phase_offset_deg']) * deg
    skew = rng.normal(0, hw['skew_deg']) * deg
    jit = rng.normal(0, hw['jitter_deg'] * deg, n_raw)
    qa = (drive_phase + off + jit) % (2 * np.pi)
    qb = (drive_phase + off + jit + skew) % (2 * np.pi)

    a = np.interp(qa, g, node_a, period=2 * np.pi)
    b = np.interp(qb, g, node_b, period=2 * np.pi)
    xt = rng.uniform(*hw['crosstalk'])
    b = b + xt * A * np.sin(qa + rng.uniform(*hw['crosstalk_phase_deg']) * deg)

    lsb = hw['node_lsb_v']
    for arr in (a, b):
        arr += rng.normal(0, rng.uniform(*hw['noise_counts']) * lsb, n_raw)
        arr += rng.normal(0, hw['offset_frac'] * A)
        hit = rng.random(n_raw) < rng.uniform(*hw['spike_rate'])
        arr[hit] += rng.choice([-1.0, 1.0], hit.sum()) * rng.uniform(*hw['spike_counts'], hit.sum()) * lsb
    a = np.round(a / lsb) * lsb
    b = np.round(b / lsb) * lsb

    v = a - b
    i = b / Rr
    A_meas = A * (1.0 + rng.normal(0, hw['amp_err']))
    phase = drive_phase % (2 * np.pi)
    return dict(v=v, i=i, phase=phase, A=A_meas, Rr=Rr,
                component=component, health=health, fault=fault, F=F, value=value)


def make_dataset(n_good=120, n_faulty=120, seed=0):
    """สร้างชุดข้อมูลทั้งหมด: คืน list ของ raw samples"""
    rng = np.random.default_rng(seed)
    data = []
    for comp in COMPONENTS:
        for _ in range(n_good):
            data.append(generate_sample(comp, 'good', rng))
        for _ in range(n_faulty):
            data.append(generate_sample(comp, 'faulty', rng))
    rng.shuffle(data)
    return data


if __name__ == '__main__':
    rng = np.random.default_rng(1)
    for comp in COMPONENTS:
        for _ in range(3):
            s = generate_sample(comp, 'good', rng)
            print(f"{comp:4s} good value={s['value']:.3g}  F={s['F']:g} Hz  Rr={s['Rr']:g}  "
                  f"v[{s['v'].min():+.2f},{s['v'].max():+.2f}] i[{s['i'].min()*1e3:+.3f},{s['i'].max()*1e3:+.3f}] mA")
        sf = generate_sample(comp, 'faulty', rng)
        print(f"{comp:4s} fault({sf['fault']}) Rr={sf['Rr']:g}")

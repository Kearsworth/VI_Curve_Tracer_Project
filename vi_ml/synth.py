"""
synth.py — ตัวสร้างข้อมูลสังเคราะห์ (synthetic data generator)
================================================================
สร้าง "ข้อมูลดิบเสมือน" ที่จำลองว่าเครื่อง V-I curve tracer ส่งมาให้ สำหรับอุปกรณ์
พื้นฐาน 6 ชนิด ทั้งสภาพดีและเสีย ใช้เป็นชุดข้อมูลสำหรับเทรนและทดสอบโมเดล ML

อุปกรณ์ 6 ชนิด:
  R   = ตัวต้านทาน
  C   = ตัวเก็บประจุ
  L   = ตัวเหนี่ยวนำ
  D   = ไดโอด (ซิลิคอน)
  LED = ไดโอดเปล่งแสง
  Z   = ซีเนอร์ไดโอด

เอาต์พุตของ generate_sample() คือ dict ที่เลียนแบบสิ่งที่ tracer ส่งมา:
  {'v': ..., 'i': ..., 'phase': ..., 'A': ..., 'Rr': ...}
โดย v,i,phase เป็นอาเรย์ของตัวอย่างดิบ (หลายรอบ มี noise/jitter) และ A,Rr คือ
ค่าตั้งเครื่อง (แอมพลิจูดขับ, ตัวต้านทานช่วง) ที่ tracer แนบมาด้วย
"""

import numpy as np

VT = 0.02585           # thermal voltage ที่อุณหภูมิห้อง (โวลต์)
F  = 1000.0            # ความถี่สัญญาณขับ (Hz)
W  = 2 * np.pi * F     # ความถี่เชิงมุม
NG = 720               # ความละเอียดของกริดเฟส "อุดมคติ" (จุดต่อรอบ)

# ค่าตั้งต้นของแต่ละอุปกรณ์: A = แอมพลิจูดขับ (V peak), Rr = ตัวต้านทานช่วง
CONFIG = {
    'R':   dict(A=5.0, Rr=1000.0, nominal=1000.0),
    'C':   dict(A=5.0, Rr=1600.0, nominal=100e-9),
    'L':   dict(A=5.0, Rr=680.0,  nominal=100e-3),
    'D':   dict(A=5.0, Rr=1000.0, Vf=0.65, n=1.7),
    'LED': dict(A=5.0, Rr=1000.0, Vf=1.90, n=2.5),
    'Z':   dict(A=6.0, Rr=1000.0, Vf=0.65, n=1.7, Vz=3.3, nz=2.0),
}

COMPONENTS = ['R', 'C', 'L', 'D', 'LED', 'Z']

# เมนู fault ของแต่ละชนิด (เฉพาะ fault ที่ "เปลี่ยนรูปทรง" ของ signature จึงตรวจจับ
# ได้จากภาพลายเซ็นโดยตรง — การเพี้ยนค่าเล็กน้อยต้องใช้ reference เทียบ ไม่รวมในเดโมนี้)
FAULTS = {
    'R':   ['open', 'short'],
    'C':   ['open', 'short', 'esr', 'leak'],
    'L':   ['open', 'short', 'dcr', 'shorted_turns'],
    'D':   ['open', 'short', 'reversed', 'degraded'],
    'LED': ['open', 'short', 'reversed', 'degraded'],
    'Z':   ['open', 'short', 'reversed', 'vz_shift'],
}


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
# สร้าง signature อุดมคติ (v, i) บนกริดเฟส NG จุด — หน่วยฟิสิกส์จริง
# ----------------------------------------------------------------------------
def generate_ideal(component, health, rng):
    cfg = CONFIG[component]
    A, Rr = cfg['A'], cfg['Rr']
    g = np.linspace(0, 2 * np.pi, NG, endpoint=False)
    Vs = A * np.sin(g)

    fault = None
    if health == 'faulty':
        fault = rng.choice(FAULTS[component])

    # --- open / short เหมือนกันทุกชนิด ---
    if fault == 'open':
        return Vs.copy(), np.zeros_like(Vs) + rng.normal(0, 1e-6, NG), fault
    if fault == 'short':
        return np.zeros_like(Vs) + rng.normal(0, 1e-4, NG), Vs / Rr, fault

    # ---------- อุปกรณ์เชิงเส้น: R, C, L (ใช้เฟเซอร์) ----------
    if component in ('R', 'C', 'L'):
        if component == 'R':
            Rd = cfg['nominal'] * rng.uniform(0.8, 1.2)   # good = ค่าปกติ ±20%
            Zd = complex(Rd, 0.0)
        elif component == 'C':
            Cv = cfg['nominal'] * rng.uniform(0.8, 1.2)
            Zd = 1.0 / (1j * W * Cv)
            if fault == 'esr':
                Zd += rng.uniform(150, 1200)              # ESR อนุกรม
            elif fault == 'leak':
                Rleak = rng.uniform(2000, 20000)
                Zd = 1.0 / (1.0 / Zd + 1.0 / Rleak)       # รั่วขนาน
        else:  # L
            Lv = cfg['nominal'] * rng.uniform(0.8, 1.2)
            dcr = rng.uniform(5, 40)
            if fault == 'dcr':
                dcr = rng.uniform(300, 1500)
            elif fault == 'shorted_turns':
                Lv *= rng.uniform(0.2, 0.4)               # รอบลัด L ลด
            Zd = 1j * W * Lv + dcr

        Iph = A / (Rr + Zd)                               # เฟเซอร์กระแส
        i = np.imag(Iph * np.exp(1j * g))
        v = np.imag(Iph * Zd * np.exp(1j * g))
        return v, i, fault

    # ---------- อุปกรณ์ไม่เชิงเส้น: D, LED, Z (แก้ load line) ----------
    n = cfg['n']
    Vf = cfg['Vf']
    Rs = 0.0                                              # series R ภายใน
    if fault == 'degraded':
        Rs = rng.uniform(200, 800)                        # เสื่อม = ความต้านทานอนุกรมสูง
    Is = _Is_for_vf(Vf * rng.uniform(0.95, 1.05), n)

    if component == 'Z':
        Vz = cfg['Vz'] * (rng.uniform(0.6, 1.4) if fault == 'vz_shift' else rng.uniform(0.97, 1.03))
        base = lambda vd: _zener(vd, Is, n, Vz, cfg['nz'])
    else:
        base = lambda vd: _diode(vd, Is, n)

    if fault == 'reversed':
        cur = lambda vd: (lambda I, dI: (-I, dI))(*base(-vd))   # กลับขั้ว: I(vd) = -base(-vd)
    else:
        cur = base

    Vd = _solve_loadline(Vs, Rr + Rs, cur)
    I, _ = cur(Vd)
    v = Vs - I * Rr                                       # แรงดันคร่อม DUT (รวม Rs ภายใน)
    return v, I, fault


# ----------------------------------------------------------------------------
# จำลอง "การเก็บข้อมูลดิบ" จาก signature อุดมคติ (หลายรอบ + noise + jitter)
# ----------------------------------------------------------------------------
def generate_sample(component, health, rng, n_raw=1600, n_cycles=4):
    v_ideal, i_ideal, fault = generate_ideal(component, health, rng)
    cfg = CONFIG[component]
    A, Rr = cfg['A'], cfg['Rr']
    g = np.linspace(0, 2 * np.pi, NG, endpoint=False)

    t = np.linspace(0, n_cycles / F, n_raw, endpoint=False)
    drive_phase = W * t                                   # เฟสที่ "รู้" จากสัญญาณ SYNC
    phi0 = rng.uniform(0, 2 * np.pi)                      # trigger jitter (เฟสศูนย์เลื่อน)
    q = (drive_phase + phi0) % (2 * np.pi)

    v = np.interp(q, g, v_ideal, period=2 * np.pi)
    i = np.interp(q, g, i_ideal, period=2 * np.pi)

    amp_var = 1.0 + rng.normal(0, 0.02)                   # แอมพลิจูดแปรผันเล็กน้อย
    v = v * amp_var + rng.normal(0, 0.01 * A, n_raw) + rng.normal(0, 0.01 * A)
    i_scale = A / Rr
    i = i * amp_var + rng.normal(0, 0.01 * i_scale, n_raw) + rng.normal(0, 0.005 * i_scale)

    return dict(v=v, i=i, phase=drive_phase, A=A, Rr=Rr,
                component=component, health=health, fault=fault)


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
        s = generate_sample(comp, 'good', rng)
        print(f"{comp:4s} good  -> v[{s['v'].min():+.2f},{s['v'].max():+.2f}] "
              f"i[{s['i'].min()*1e3:+.2f},{s['i'].max()*1e3:+.2f}] mA")
        sf = generate_sample(comp, 'faulty', rng)
        print(f"{comp:4s} fault({sf['fault']}) ok")

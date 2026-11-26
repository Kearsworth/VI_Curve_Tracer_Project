"""
features.py — สกัดฟีเจอร์ที่ตีความได้จาก signature มาตรฐาน
==========================================================
รับ signature (N, 2) ที่ calibrate แล้ว คืนเวกเตอร์ฟีเจอร์เชิงเรขาคณิต/ไฟฟ้า
ฟีเจอร์เหล่านี้แมปกับฟิสิกส์ ทำให้โมเดล (เช่น Random Forest) อธิบายได้ว่าตัดสินจากอะไร
(feature importance) — จุดขายสำคัญเวลานำเสนอ
"""

import numpy as np

FEATURE_NAMES = [
    'signed_area', 'abs_area', 'slope0', 'phaseVI', 'aspect',
    'knee_V', 'symmetry', 'rms_radius', 'n_segments',
    'peakV', 'peakI', 'spread_ratio',
    'off_slope', 'on_res',          # soft-fault features (2026-11-27)
]


def _signed_area(v, i):
    # พื้นที่วงแบบมีเครื่องหมาย (shoelace) : ขนาด=รีแอกแตนซ์, เครื่องหมาย=ทิศหมุน (C vs L)
    return 0.5 * np.sum(v * np.roll(i, -1) - np.roll(v, -1) * i)


def _slope0(v, i):
    # ความชัน dI/dV ใกล้จุดกำเนิด -> conductance ของตัวต้านทาน
    m = np.abs(v) < 0.2 * (np.max(np.abs(v)) + 1e-12)
    if m.sum() < 2:
        m = np.ones_like(v, bool)
    A = np.vstack([v[m], np.ones(m.sum())]).T
    return np.linalg.lstsq(A, i[m], rcond=None)[0][0]


def _phase_VI(v, i):
    # เฟสต่างระหว่าง V กับ I (องศา) จาก fundamental : 0=R, +90=C, -90=L
    V = np.fft.rfft(v - v.mean())
    I = np.fft.rfft(i - i.mean())
    return np.degrees(np.angle(I[1]) - np.angle(V[1]))


def _aspect(v, i):
    # อัตราแกนรอง/แกนหลัก : ~0 = เส้น (R), ->1 = วงรีอ้วน
    pts = np.column_stack([v - v.mean(), i - i.mean()])
    w = np.linalg.svd(pts, compute_uv=False)
    return (w[1] / w[0]) if w[0] > 1e-12 else 0.0


def _knee_V(v, i, frac=0.25):
    # แรงดันที่กระแสเริ่มขึ้นเกินเศษส่วนของ peak -> หัวเข่าไดโอด
    ipk = np.max(np.abs(i)) + 1e-12
    hit = np.where(np.abs(i) > frac * ipk)[0]
    return v[hit[0]] if hit.size else 0.0


def _symmetry(v, i):
    # ความสมมาตรรอบจุดกำเนิด : สูง=R/C/L, ต่ำ=ไดโอด (เรกติไฟ)
    return np.corrcoef(np.r_[v, i], np.r_[-v[::-1], -i[::-1]])[0, 1]


def _n_segments(v, i, tol=15.0):
    # จำนวนการหักทิศตามวง -> ~2 สำหรับไดโอด (หัวเข่า)
    d = np.diff(np.column_stack([v, i]), axis=0)
    ang = np.arctan2(d[:, 1], d[:, 0])
    dang = np.abs(np.diff(np.unwrap(ang)))
    return float(np.sum(np.degrees(dang) > tol))


def _conducting_side(v, i):
    # ฝั่งที่นำกระแสมากกว่า (+1 = V บวก, -1 = V ลบ) -> ไดโอดกลับขั้วก็ยังหาเจอ
    pos, neg = i[v > 0], i[v < 0]
    ip = np.max(np.abs(pos)) if pos.size else 0.0
    im = np.max(np.abs(neg)) if neg.size else 0.0
    return 1.0 if ip >= im else -1.0


def _line_slope(x, y):
    if x.size < 3 or np.ptp(x) < 1e-9:
        return 0.0
    return float(np.polyfit(x, y, 1)[0])


def _off_slope(v, i):
    # ความชัน dI/dV ฝั่งที่ "ปิด" (ช่วงก่อน breakdown, กระแสยังต่ำ) -> รอยต่อรั่ว (Zener/diode leak)
    # ของดี ~0 (เหลือแค่ noise/crosstalk), รั่ว = Rr/Rleak
    s = _conducting_side(v, i)
    vpk = np.max(np.abs(v)) + 1e-12
    ipk = np.max(np.abs(i)) + 1e-12
    off = (-s * v) > 0.1 * vpk
    m = off & (np.abs(i) < 0.1 * ipk)
    if m.sum() < 5:                 # ฝั่งปิดมีกระแสเยอะ (R/C/L): ใช้ทั้งฝั่ง
        m = off
    return _line_slope(v[m], i[m])


def _on_res(v, i):
    # ความต้านทานพลวัต dV/dI ฝั่งที่นำ หลังหัวเข่า (|I| > ครึ่ง peak) -> ไดโอด/LED เสื่อม (Rs สูง)
    # ของดี ~ n·VT/I/Rr (เล็กมาก), เสื่อม = Rs/Rr
    s = _conducting_side(v, i)
    ipk = np.max(np.abs(i)) + 1e-12
    m = ((s * v) > 0) & (np.abs(i) > 0.5 * ipk)
    return abs(_line_slope(i[m], v[m]))


def extract(sig):
    """สกัดเวกเตอร์ฟีเจอร์ (14 มิติ) จาก signature (N,2)"""
    v, i = sig[:, 0], sig[:, 1]
    a = _signed_area(v, i)
    return np.array([
        a,
        abs(a),
        _slope0(v, i),
        _phase_VI(v, i),
        _aspect(v, i),
        _knee_V(v, i),
        _symmetry(v, i),
        np.sqrt(np.mean(v**2 + i**2)),
        _n_segments(v, i),
        np.max(np.abs(v)),
        np.max(np.abs(i)),
        np.std(i) / (np.std(v) + 1e-12),
        _off_slope(v, i),
        _on_res(v, i),
    ], dtype=np.float64)


def extract_batch(sigs):
    return np.array([extract(s) for s in sigs])

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


def extract(sig):
    """สกัดเวกเตอร์ฟีเจอร์ (12 มิติ) จาก signature (N,2)"""
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
    ], dtype=np.float64)


def extract_batch(sigs):
    return np.array([extract(s) for s in sigs])

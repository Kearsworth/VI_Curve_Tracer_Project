"""
calibrate.py — โมดูลสอบเทียบ/แปลงข้อมูล (calibration / pre-processing)
=====================================================================
นี่คือส่วนแรกที่ "เรา" รับผิดชอบตามโจทย์: รับข้อมูลดิบที่ tracer ส่งมา แล้วแปลงให้
เป็น "พิกัดฉากมาตรฐาน" จำนวนคงที่ N จุด (ค่าปริยาย 360 = 1 จุดต่อ 1 องศาของเฟสขับ)
พร้อม normalize ให้เทียบกันได้ เอาต์พุตเป็นอาเรย์ (N, 2): คอลัมน์ 0 = V, 1 = I

ทำ 3 ขั้นตามลำดับ:
  1) resample  : พับตัวอย่างหลายรอบลงกริดเฟส N จุด (เฉลี่ยต่อองศา -> ลด noise)
  2) normalize : หารด้วยตัวหารร่วม รักษาอัตราส่วน V/I ไว้ (จับ fault ที่เปลี่ยนรูปได้)
  3) align     : (ออปชัน) จัดเฟสให้ตรงกับ reference ด้วย cross-correlation ตอน inference
"""

import numpy as np

N_POINTS = 360        # ความละเอียดพิกัดฉากที่ต้องการ (ปรับเป็น 400 ได้ถ้าต้องการ)


def _periodic_resample(phase, values, n_points):
    """เฉลี่ยค่าในแต่ละ bin องศา (ทน glitch) แล้วเติม bin ที่ว่างด้วย interp แบบวน"""
    idx = np.floor((phase % (2 * np.pi)) / (2 * np.pi) * n_points).astype(int) % n_points
    counts = np.bincount(idx, minlength=n_points).astype(float)
    sums = np.bincount(idx, weights=values, minlength=n_points)
    out = np.full(n_points, np.nan)
    nz = counts > 0
    out[nz] = sums[nz] / counts[nz]
    if (~nz).any():                                   # เติม bin ว่าง
        xs = np.where(nz)[0]
        out = np.interp(np.arange(n_points), xs, out[nz], period=n_points)
    return out


def calibrate(raw, n_points=N_POINTS):
    """
    แปลง raw capture -> signature มาตรฐาน (n_points, 2) ที่ normalize แล้ว

    raw ต้องมีคีย์: 'v', 'i', 'phase' (อาเรย์ตัวอย่างดิบ) และ 'A', 'Rr'
    (ค่าตั้งเครื่องที่ tracer แนบมา ใช้ normalize)
    """
    v = np.asarray(raw['v'], float)
    i = np.asarray(raw['i'], float)
    phase = np.asarray(raw['phase'], float)
    A, Rr = float(raw['A']), float(raw['Rr'])

    # 1) resample ลงกริดเฟส n_points จุด
    v_c = _periodic_resample(phase, v, n_points)
    i_c = _periodic_resample(phase, i, n_points)

    # 2) normalize ด้วยตัวหารร่วม (รักษาอัตราส่วน V/I):
    #    - V หารด้วยแอมพลิจูดขับ A  -> ไร้มิติ
    #    - I คูณ Rr (แปลงเป็น "โวลต์") แล้วหาร A -> ไร้มิติ สเกลเดียวกับ V
    #    ผล: ตัวต้านทานค่าเท่า Rr จะได้เส้น 45 องศาพอดี, วงรี C/L รูปคงที่
    v_n = v_c / A
    i_n = (i_c * Rr) / A

    return np.column_stack([v_n, i_n])


def circular_align(sig, ref):
    """(ใช้ตอน inference ถ้าจะเทียบกับ reference โดยตรง) เลื่อนแบบวนให้ตรงกับ ref มากสุด"""
    a = sig[:, 1] - sig[:, 1].mean()
    b = ref[:, 1] - ref[:, 1].mean()
    corr = np.fft.irfft(np.fft.rfft(b) * np.conj(np.fft.rfft(a)), n=len(a))
    shift = int(np.argmax(corr))
    return np.roll(sig, shift, axis=0), shift


if __name__ == '__main__':
    from synth import generate_sample
    rng = np.random.default_rng(2)
    for comp in ['R', 'C', 'L', 'D', 'LED', 'Z']:
        s = calibrate(generate_sample(comp, 'good', rng))
        print(f"{comp:4s} -> shape {s.shape}, "
              f"V[{s[:,0].min():+.2f},{s[:,0].max():+.2f}] "
              f"I[{s[:,1].min():+.2f},{s[:,1].max():+.2f}]")

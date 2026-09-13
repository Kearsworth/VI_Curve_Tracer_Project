"""
verify.py — โมดูลใช้งานจริง (inference)
========================================
โหลดโมเดลที่เทรนแล้ว รับข้อมูลดิบจาก tracer หนึ่งชิ้น แล้วคืนคำตัดสิน

verify(raw) -> dict:
    {
      'type'        : ชนิดอุปกรณ์ที่โมเดลเดา ('R'/'C'/'L'/'D'/'LED'/'Z'),
      'verdict'     : 'GOOD' หรือ 'FAULTY',
      'confidence'  : ความมั่นใจของคำตัดสิน ดี/เสีย (0..1),
      'anomaly'     : True/False จากตัวตรวจจับความผิดปกติ (ฝึกด้วยของดี),
      'anomaly_score': คะแนนความผิดปกติ (สูง = ผิดปกติมาก),
    }
"""

import os
import joblib
import numpy as np

import calibrate
import features

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')

_CACHE = {}


def _load():
    if not _CACHE:
        _CACHE['health'] = joblib.load(os.path.join(MODEL_DIR, 'health_rf.joblib'))
        _CACHE['type'] = joblib.load(os.path.join(MODEL_DIR, 'type_rf.joblib'))
        _CACHE['anomaly'] = joblib.load(os.path.join(MODEL_DIR, 'anomaly_if.joblib'))
    return _CACHE


def verify(raw):
    m = _load()
    sig = calibrate.calibrate(raw)          # ขั้นตอนแปลงเดียวกับตอนเทรนเป๊ะ
    x = features.extract(sig).reshape(1, -1)

    health = int(m['health'].predict(x)[0])            # 0=ดี, 1=เสีย
    proba = m['health'].predict_proba(x)[0]
    comp = str(m['type'].predict(x)[0])
    a_score = float(-m['anomaly'].decision_function(x)[0])
    a_flag = bool(m['anomaly'].predict(x)[0] == -1)

    return dict(
        type=comp,
        verdict='FAULTY' if health == 1 else 'GOOD',
        confidence=float(proba[health]),
        anomaly=a_flag,
        anomaly_score=a_score,
    )


if __name__ == '__main__':
    from synth import generate_sample, COMPONENTS
    rng = np.random.default_rng(99)
    print(f"{'จริง':>16s} | {'ทำนายชนิด':>9s} | {'คำตัดสิน':>8s} | conf | anomaly")
    print("-" * 60)
    for comp in COMPONENTS:
        for health in ['good', 'faulty']:
            raw = generate_sample(comp, health, rng)
            r = verify(raw)
            tag = f"{comp}/{health}"
            ok = '✓' if (r['verdict'] == 'FAULTY') == (health == 'faulty') else '✗'
            print(f"{tag:>16s} | {r['type']:>9s} | {r['verdict']:>8s} |"
                  f" {r['confidence']:.2f} | {str(r['anomaly']):>5s}  {ok}")

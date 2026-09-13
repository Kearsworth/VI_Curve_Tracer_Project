"""
demo.py — เดโมรันครบ end-to-end ในไฟล์เดียว
============================================
รัน:  python3 demo.py
ลำดับ: เทรนโมเดล (Part 2->5) -> เซฟ -> ทดลองใช้งานจริงกับตัวอย่างใหม่ (Part 6)
"""
import numpy as np
import train
import verify
from synth import generate_sample, COMPONENTS

print("\n########## ขั้นเทรน (Part 2 ถึง 5) ##########")
train.main()

print("\n########## ขั้นใช้งานจริง (Part 6): ทดลองกับอุปกรณ์ใหม่ ##########")
rng = np.random.default_rng(123)
correct = 0; total = 0
print(f"{'อุปกรณ์จริง':>16s} | {'ทำนายชนิด':>9s} | {'คำตัดสิน':>8s} | conf")
print("-" * 56)
for comp in COMPONENTS:
    for health in ['good', 'faulty']:
        raw = generate_sample(comp, health, rng)
        r = verify.verify(raw)
        hit = (r['verdict'] == 'FAULTY') == (health == 'faulty')
        correct += hit; total += 1
        tag = f"{comp}/{health}"
        print(f"{tag:>16s} | {r['type']:>9s} | {r['verdict']:>8s} | {r['confidence']:.2f}")
print("-" * 56)
print(f"คำตัดสิน ดี/เสีย ถูก {correct}/{total} เคส")

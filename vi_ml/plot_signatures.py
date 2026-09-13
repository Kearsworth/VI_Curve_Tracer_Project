"""สร้างรูป signature ของ 6 อุปกรณ์ (ดี vs เสีย) ไว้ตรวจสอบและใส่รายงาน"""
import numpy as np, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
fm.fontManager.addfont('/usr/share/fonts/opentype/tlwg/Loma.otf')
plt.rcParams.update({'font.family':'Loma','savefig.dpi':150,'savefig.bbox':'tight','axes.unicode_minus':False})
import synth, calibrate

NAMES = {'R':'Resistor','C':'Capacitor','L':'Inductor','D':'Diode','LED':'LED','Z':'Zener'}
rng = np.random.default_rng(7)
fig, axs = plt.subplots(2, 3, figsize=(12, 7.4))
for ax, comp in zip(axs.ravel(), synth.COMPONENTS):
    g = calibrate.calibrate(synth.generate_sample(comp, 'good', rng))
    f = calibrate.calibrate(synth.generate_sample(comp, 'faulty', rng))
    fr = synth.generate_sample(comp, 'faulty', rng)  # เอาชื่อ fault
    ax.plot(g[:,0], g[:,1], color='#1f77b4', lw=2.2, label='good')
    ax.plot(f[:,0], f[:,1], color='#d62728', lw=1.8, ls='--', label=f"faulty")
    ax.axhline(0, color='#ccc', lw=0.6); ax.axvline(0, color='#ccc', lw=0.6)
    ax.set_title(f"{NAMES[comp]} ({comp})", fontsize=13)
    ax.set_xlabel('V (normalized)', fontsize=9); ax.set_ylabel('I (normalized)', fontsize=9)
    ax.legend(fontsize=9, loc='best'); ax.grid(True, ls=':', lw=0.4, alpha=0.6)
    ax.set_aspect('equal', 'box')
fig.suptitle('ลายเซ็น V-I ของอุปกรณ์ 6 ชนิด : เส้นทึบ = ดี, เส้นประ = เสีย', fontsize=14, y=1.01)
fig.tight_layout()
fig.savefig('figs_ml/signatures.png')
print('saved')

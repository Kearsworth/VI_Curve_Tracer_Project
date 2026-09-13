"""
train.py — สคริปต์เทรนโมเดล (ส่วนที่เป็น "ปัญหา" ที่พี่กังวล — จบในไฟล์นี้)
==========================================================================
เดินครบ pipeline การเทรน:
  1) สร้างชุดข้อมูล (สังเคราะห์) ของ 6 อุปกรณ์ ทั้งดีและเสีย
  2) calibrate ข้อมูลดิบ -> signature มาตรฐาน 360 จุด
  3) สกัดฟีเจอร์
  4) แบ่ง train/test
  5) เทรน 3 โมเดล:
       (ก) health_rf  : Random Forest ตัดสิน ดี/เสีย   <-- คำตอบหลักของโจทย์
       (ข) type_rf    : Random Forest บอกชนิดอุปกรณ์ (6 คลาส)  <-- ทำให้ผลอ่านง่าย
       (ค) anomaly_if : Isolation Forest ฝึกด้วย "ของดี" อย่างเดียว (แนว anomaly)
  6) ประเมินผล + พิมพ์รายงาน + เซฟโมเดลลงโฟลเดอร์ models/

รันตรง ๆ:  python3 train.py
"""

import os
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.metrics import (classification_report, confusion_matrix,
                             accuracy_score, roc_auc_score)

import synth
import calibrate
import features

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')


def build_xy(n_good=150, n_faulty=150, seed=0):
    """สร้างข้อมูล -> calibrate -> features. คืน X, ป้ายชนิด, ป้ายสุขภาพ"""
    data = synth.make_dataset(n_good=n_good, n_faulty=n_faulty, seed=seed)
    X, comp, health = [], [], []
    for raw in data:
        sig = calibrate.calibrate(raw)
        X.append(features.extract(sig))
        comp.append(raw['component'])
        health.append(0 if raw['health'] == 'good' else 1)   # 0=ดี, 1=เสีย
    return np.array(X), np.array(comp), np.array(health)


def main(save=True, verbose=True):
    os.makedirs(MODEL_DIR, exist_ok=True)
    if verbose:
        print("=" * 68)
        print("  สร้างชุดข้อมูล + calibrate + สกัดฟีเจอร์ ...")
    X, comp, health = build_xy()
    if verbose:
        print(f"  ตัวอย่างทั้งหมด: {len(X)}  |  ฟีเจอร์/ตัวอย่าง: {X.shape[1]}")
        print(f"  ดี: {(health==0).sum()}   เสีย: {(health==1).sum()}")

    # แบ่ง train/test (stratify ตามคู่ ชนิด+สุขภาพ เพื่อให้สัดส่วนสมดุลทั้งสองชุด)
    strat = np.array([f"{c}_{h}" for c, h in zip(comp, health)])
    idx = np.arange(len(X))
    tr, te = train_test_split(idx, test_size=0.25, stratify=strat, random_state=42)

    # ---------- (ก) โมเดลตัดสิน ดี/เสีย ----------
    if verbose:
        print("\n" + "=" * 68)
        print("  (ก) HEALTH — Random Forest ตัดสิน ดี/เสีย")
    health_rf = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=2, class_weight='balanced', random_state=42)
    cv = cross_val_score(health_rf, X[tr], health[tr],
                         cv=StratifiedKFold(5, shuffle=True, random_state=42),
                         scoring='f1_macro')
    health_rf.fit(X[tr], health[tr])
    pred = health_rf.predict(X[te])
    if verbose:
        print(f"  CV F1(macro) = {cv.mean():.3f} ± {cv.std():.3f}")
        print(f"  test accuracy = {accuracy_score(health[te], pred):.3f}")
        print(classification_report(health[te], pred,
              target_names=['ดี (good)', 'เสีย (faulty)']))
        print("  confusion matrix [แถว=จริง, คอลัมน์=ทำนาย]:")
        print("  ", confusion_matrix(health[te], pred).tolist())

    # ---------- (ข) โมเดลบอกชนิดอุปกรณ์ (ฝึกด้วยของดี) ----------
    if verbose:
        print("\n" + "=" * 68)
        print("  (ข) TYPE — Random Forest บอกชนิดอุปกรณ์ (6 คลาส, ฝึกด้วยของดี)")
    good_tr = tr[health[tr] == 0]
    good_te = te[health[te] == 0]
    type_rf = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=2, random_state=42)
    type_rf.fit(X[good_tr], comp[good_tr])
    pred_t = type_rf.predict(X[good_te])
    if verbose:
        print(f"  test accuracy = {accuracy_score(comp[good_te], pred_t):.3f}")
        print(classification_report(comp[good_te], pred_t))

    # ---------- (ค) โมเดล anomaly (ฝึกด้วยของดีอย่างเดียว) ----------
    if verbose:
        print("=" * 68)
        print("  (ค) ANOMALY — Isolation Forest ฝึกด้วย 'ของดี' อย่างเดียว")
    anomaly_if = make_pipeline(
        StandardScaler(),
        IsolationForest(n_estimators=300, contamination=0.02, random_state=42))
    anomaly_if.fit(X[good_tr])
    # decision_function สูง=ปกติ, ต่ำ=ผิดปกติ -> ใช้ค่าลบเป็นคะแนน anomaly
    scores = -anomaly_if.decision_function(X[te])
    auc = roc_auc_score(health[te], scores)
    flag = (anomaly_if.predict(X[te]) == -1).astype(int)   # -1 = ผิดปกติ
    if verbose:
        print(f"  ROC-AUC (แยกดี/เสีย ด้วยคะแนน anomaly) = {auc:.3f}")
        print(f"  ตรวจจับของเสียได้ (recall) = "
              f"{(flag[health[te]==1]==1).mean():.3f}  |  "
              f"เตือนผิดบนของดี (false alarm) = {(flag[health[te]==0]==1).mean():.3f}")

    # ---------- feature importance ของ health_rf ----------
    if verbose:
        print("\n" + "=" * 68)
        print("  ฟีเจอร์ที่โมเดล ดี/เสีย ให้ความสำคัญสูงสุด:")
        imp = health_rf.feature_importances_
        for k in np.argsort(imp)[::-1][:6]:
            print(f"    {features.FEATURE_NAMES[k]:14s} {imp[k]:.3f}")

    # ---------- เซฟโมเดล + metadata ----------
    if save:
        joblib.dump(health_rf, os.path.join(MODEL_DIR, 'health_rf.joblib'))
        joblib.dump(type_rf,   os.path.join(MODEL_DIR, 'type_rf.joblib'))
        joblib.dump(anomaly_if, os.path.join(MODEL_DIR, 'anomaly_if.joblib'))
        joblib.dump(dict(feature_names=features.FEATURE_NAMES,
                         components=synth.COMPONENTS,
                         n_points=calibrate.N_POINTS),
                    os.path.join(MODEL_DIR, 'meta.joblib'))
        if verbose:
            print("\n  เซฟโมเดลแล้วที่โฟลเดอร์ models/ : "
                  "health_rf, type_rf, anomaly_if, meta")

    return health_rf, type_rf, anomaly_if


if __name__ == '__main__':
    main()

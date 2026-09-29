"""hardware/reader.py: serial frames -> raw dict, without hardware.

The fake capture below mimics firmware/esp32/loopback/sine_capture: same meta line, same CSV
header/rows, free-running (uneven) sample spacing, and the ADC offset measured in Stage 2.
"""
import numpy as np
import pytest
import reader, calibrate, features

F_HZ = 50.0
A_NOM = 100 * 3.3 / 255
META = ("# drive_freq_hz=50.000 lut_size=100 dac_center=128 dac_amplitude_counts=100 "
        f"A_nominal_v={A_NOM:.4f} Rr_ohm_placeholder=1.0000 vref=3.30 dac_bits=8 adc_bits=12 baud=921600")


def fake_lines(n_cycles=5, seed=0, adc_offset=-180, junk=True):
    """Serial text as the board prints it. Sine centred at ~1868 counts (Stage 2: offset)."""
    rng = np.random.default_rng(seed)
    lines = ["# sine_capture Stage 3 ready", META, "index,t_us,phase_rad,adc_v_counts,adc_i_counts"]
    if junk:
        lines.insert(0, "5,187,0.0587,148")          # half-received line at port open
    t, idx = 0.0, 0
    while t < n_cycles / F_HZ * 1e6:
        cyc = (t * F_HZ / 1e6) % 1.0
        counts = int(round(2048 + adc_offset + 1530 * np.sin(2 * np.pi * cyc)))
        lines.append(f"{idx},{int(t)},{cyc * 2 * np.pi:.4f},{counts},{counts}")
        t += rng.uniform(150, 450)                    # jittery spacing
        idx += 1
    return lines


def test_parse_skips_comments_header_and_junk():
    cap = reader.parse_capture(fake_lines())
    assert cap.n_bad_lines == 1
    assert cap.meta["A_nominal_v"] == pytest.approx(A_NOM, abs=1e-4)
    assert cap.meta["vref"] == 3.3
    assert len(cap.phase) == len(cap.adc_v) == len(cap.adc_i) > 100


def test_parse_rejects_out_of_range_rows():
    cap = reader.parse_capture(["0,0,0.1,5000,10", "1,1,0.2,10,-3", "2,2,9.0,10,10", "3,3,0.3,10,10"])
    assert cap.n_bad_lines == 3 and len(cap.phase) == 1


def test_parse_accepts_bytes_and_crlf():
    cap = reader.parse_capture([b"0,0,0.1000,100,100\r\n"])
    assert len(cap.phase) == 1


def test_max_cycles_stops_early():
    full = reader.parse_capture(fake_lines(n_cycles=8))
    part = reader.parse_capture(fake_lines(n_cycles=8), max_cycles=2)
    assert len(part.phase) < len(full.phase) / 2


def test_raw_dict_matches_contract():
    raw = reader.capture_to_raw(reader.parse_capture(fake_lines()), loopback=True)
    assert set(raw) == {"v", "i", "phase", "A", "Rr"}
    assert raw["v"].shape == raw["i"].shape == raw["phase"].shape
    assert raw["A"] == pytest.approx(A_NOM, abs=1e-4) and raw["Rr"] == 1.0
    assert np.isfinite(raw["v"]).all()


def test_only_whole_cycles_kept():
    raw = reader.capture_to_raw(reader.parse_capture(fake_lines(n_cycles=5)), loopback=True)
    wraps = np.sum(np.diff(raw["phase"]) < -np.pi)
    assert wraps == 2                                  # 5 cycles -> 4 wraps -> 3 whole cycles kept
    assert raw["phase"][0] < 0.5                       # starts right after a wrap


def test_loopback_centring_removes_adc_offset():
    cap = reader.parse_capture(fake_lines(adc_offset=-180))
    ideal = reader.capture_to_raw(cap)["v"]
    centred = reader.capture_to_raw(cap, loopback=True)["v"]
    assert abs(ideal.mean()) > 0.1                     # ideal mid-rail leaves a DC error
    assert abs(centred.mean()) < 0.02
    assert centred.max() == pytest.approx(-centred.min(), abs=0.05)


def test_i_is_v_over_rr_when_channels_alias():
    raw = reader.capture_to_raw(reader.parse_capture(fake_lines()), Rr=4.0, loopback=True)
    assert np.allclose(raw["i"], raw["v"] / 4.0)


def test_missing_meta_requires_explicit_A_Rr():
    cap = reader.parse_capture(fake_lines()[3:])       # drop '# ...' lines
    with pytest.raises(ValueError, match="A and Rr"):
        reader.capture_to_raw(cap)
    raw = reader.capture_to_raw(cap, A=1.3, Rr=1.0, loopback=True)
    assert raw["A"] == 1.3


def test_less_than_one_cycle_raises():
    cap = reader.parse_capture(fake_lines(n_cycles=1))
    with pytest.raises(ValueError, match="full drive cycle"):
        reader.capture_to_raw(cap)


def test_loopback_capture_flows_through_pipeline_unchanged():
    """reader -> calibrate -> features with no ML-side changes; loop is a 45-degree line."""
    raw = reader.capture_to_raw(reader.parse_capture(fake_lines(n_cycles=6)), loopback=True)
    sig = calibrate.calibrate(raw)
    assert sig.shape == (calibrate.N_POINTS, 2) and np.isfinite(sig).all()
    assert np.allclose(sig[:, 0], sig[:, 1])           # V == I*Rr/... (Rr=1, shared pin)
    assert abs(sig[:, 0].max()) < 1.2                  # ~1 after v/A normalisation
    x = features.extract(sig)
    assert x.shape == (12,) and np.isfinite(x).all()

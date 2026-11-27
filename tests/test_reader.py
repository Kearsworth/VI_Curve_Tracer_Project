"""hardware/reader.py: serial frames -> raw dict, without hardware.

The fake capture below mimics firmware/esp32/loopback/sine_capture: same meta line, same CSV
header/rows, free-running (uneven) sample spacing, and the ADC offset measured in Stage 2.
"""
import numpy as np
import time
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
    assert x.shape == (len(features.FEATURE_NAMES),) and np.isfinite(x).all()


# ---- standalone front end (docs/STANDALONE_TESTER_PLAN.md) -------------------------------
def frontend_lines(r_dut=1000.0, rr=1000.0, a=5.0, n=600):
    """Pins as the Stage 1 board would produce them for a resistor DUT, loading included."""
    fe = reader.FrontEnd()
    lines = ["# stage1_frontend ready", "# A_nominal_v=4.98 Rr_ohm_placeholder=1000 vref=3.30",
             "index,t_us,phase_rad,adc_v_counts,adc_i_counts"]
    g_rp = 1 / fe.r_th
    for k in range(n):
        ph = (k * 2 * np.pi * 3 / n) % (2 * np.pi)            # 3 cycles
        va = a * np.sin(ph)
        # KCL at node B: (va - vb)/R = vb/Rr + (vb - v_th)/r_th
        vb = (va / r_dut + fe.v_th * g_rp) / (1 / r_dut + 1 / rr + g_rp)
        pa, pb = fe.gain * va + fe.offset, fe.gain * vb + fe.offset
        ca, cb = (int(round(p / 3.3 * reader.ADC_MAX)) for p in (pa, pb))
        lines.append(f"{k},{k * 333},{ph:.4f},{ca},{cb}")
    return lines


def test_frontend_values_match_stage0_design():
    fe = reader.FrontEnd()
    assert fe.gain == pytest.approx(0.219, abs=1e-3)
    assert fe.offset == pytest.approx(1.289, abs=1e-3)
    assert fe.r_th == pytest.approx(128e3)


@pytest.mark.parametrize("rr", [220.0, 1000.0, 10000.0, 100000.0])
def test_frontend_recovers_dut_current_with_loading_correction(rr):
    r_dut = 1000.0
    fe = reader.FrontEnd()
    raw = reader.frontend_to_raw(reader.parse_capture(frontend_lines(r_dut, rr)), Rr=rr)
    # exact (unquantised) DUT current from the same KCL the fake board used
    va = 5.0 * np.sin(raw["phase"])
    vb = (va / r_dut + fe.v_th / fe.r_th) / (1 / r_dut + 1 / rr + 1 / fe.r_th)
    i_exact = (va - vb) / r_dut
    lsb_node = 3.3 / reader.ADC_MAX / fe.gain                 # one ADC count, referred to the node
    assert np.max(np.abs(raw["i"] - i_exact)) < 1.5 * lsb_node * (1 / rr + 1 / fe.r_th) + 1e-12
    # without the loading correction the error would be far larger at high Rr
    naive = fe.node_from_pin(fe.gain * vb + fe.offset) / rr
    assert np.max(np.abs(naive - i_exact)) > np.max(np.abs(raw["i"] - i_exact))
    assert raw["A"] == pytest.approx(5.0, rel=0.02)
    assert raw["Rr"] == rr
    sig = calibrate.calibrate(raw)
    assert sig.shape == (360, 2) and np.isfinite(features.extract(sig)).all()


# ---- Case 1 front end (docs/CASE1_WIRING.md): followers, 100k/22k/22k dividers -----------
def case1_lines(r_dut=1000.0, rr=1000.0, a=5.0, n=600, meta_key=True, adc_offset=0, label_lead_deg=0.0):
    """Pins as the Case 1 board would produce them: followers, so node B is NOT loaded.
    r_dut=np.inf is the no-DUT (zero) capture; adc_offset shifts both channels' counts;
    label_lead_deg makes the printed phase run ahead of the real drive (firmware timing offset)."""
    fe = reader.FrontEnd.case1()
    key = " frontend_case=1" if meta_key else ""
    lines = ["# case1_frontend ready", f"# A_nominal_v=4.97 Rr_ohm_placeholder=1000 vref=3.30{key}",
             "index,t_us,phase_rad,adc_v_counts,adc_i_counts"]
    for k in range(n):
        ph = (k * 2 * np.pi * 3 / n) % (2 * np.pi)
        va = a * np.sin(ph)
        vb = va * rr / (r_dut + rr)                      # plain divider: no loading term
        ca, cb = (int(round((fe.gain_of(ch) * v + fe.offset_of(ch)) / 3.3 * reader.ADC_MAX)) + adc_offset
                  for ch, v in (("a", va), ("b", vb)))
        label = (ph + np.radians(label_lead_deg)) % (2 * np.pi)
        lines.append(f"{k},{k * 333},{label:.4f},{ca},{cb}")
    return lines


def test_case1_values_match_wiring_doc():
    fe = reader.FrontEnd.case1()
    assert fe.buffered
    assert fe.gain_of("a") == pytest.approx(0.08844, abs=1e-4)   # ch C 100k/19.38k/19.43k, measured
    assert fe.gain_of("b") == pytest.approx(0.08802, abs=1e-4)   # ch D 101k/19.48k/19.51k
    for ch in "ab":
        assert fe.offset_of(ch) == pytest.approx(1.515, abs=1e-3)   # P1/P2 read 1.509-1.532 V
        # +-13.5 V (op-amp saturation) must stay inside the ADC's 0..3.3 V
        assert 0 < fe.gain_of(ch) * -13.5 + fe.offset_of(ch) and fe.gain_of(ch) * 13.5 + fe.offset_of(ch) < 3.3


def test_front_end_is_picked_from_meta_line():
    assert reader.FrontEnd.from_meta(reader.parse_capture(case1_lines()).meta) == reader.FrontEnd.case1()
    assert reader.FrontEnd.from_meta(reader.parse_capture(frontend_lines()).meta) == reader.FrontEnd()


@pytest.mark.parametrize("rr", [1000.0, 10000.0, 100000.0])
def test_case1_recovers_dut_current_without_loading_term(rr):
    r_dut = 1000.0
    fe = reader.FrontEnd.case1()
    raw = reader.frontend_to_raw(reader.parse_capture(case1_lines(r_dut, rr)), Rr=rr)
    va = 5.0 * np.sin(raw["phase"])
    i_exact = va / (r_dut + rr)
    lsb_node = 3.3 / reader.ADC_MAX / fe.gain
    assert np.max(np.abs(raw["i"] - i_exact)) < 1.5 * lsb_node / rr + 1e-12
    assert np.max(np.abs(raw["v"] - i_exact * r_dut)) < 3 * lsb_node
    assert raw["A"] == pytest.approx(5.0, rel=0.02)
    # the Stage 1 constants on Case 1 data would be badly wrong
    wrong = reader.frontend_to_raw(reader.parse_capture(case1_lines(r_dut, rr)), Rr=rr, fe=reader.FrontEnd())
    assert np.max(np.abs(wrong["i"] - i_exact)) > 10 * np.max(np.abs(raw["i"] - i_exact))
    sig = calibrate.calibrate(raw)
    assert sig.shape == (360, 2) and np.isfinite(features.extract(sig)).all()


def test_case1_cli_override_without_meta_key(tmp_path, capsys):
    path = tmp_path / "cap.txt"
    path.write_text("\n".join(case1_lines(meta_key=False)) + "\n")
    import re
    reader.main(["--file", str(path), "--frontend", "--rr", "1000", "--fe", "case1"])
    a_case1 = float(re.search(r"A=([\d.]+) V", capsys.readouterr().out).group(1))
    assert a_case1 == pytest.approx(5.0, rel=0.02)
    reader.main(["--file", str(path), "--frontend", "--rr", "1000"])   # no key -> Stage 1 constants
    a_stage1 = float(re.search(r"A=([\d.]+) V", capsys.readouterr().out).group(1))
    assert abs(a_stage1 - 5.0) > 0.5


# ---- zero-cal: ESP32 ADC reads ~0.17 V low on the Case 1 board (2026-11-26) ---------------
def _cap(lines):
    return reader.parse_capture(lines)


def test_zero_cal_removes_adc_offset_from_current():
    off, rr, r_dut = -216, 1000.0, 1000.0             # -216 counts measured on the board
    cal_a, cal_b = reader.zero_cal(_cap(case1_lines(r_dut=np.inf, rr=rr, adc_offset=off)))
    cap = _cap(case1_lines(r_dut, rr, adc_offset=off))
    raw = reader.frontend_to_raw(cap, Rr=rr, cal_a=cal_a, cal_b=cal_b)
    i_exact = 5.0 * np.sin(raw["phase"]) / (r_dut + rr)
    lsb_i = 3.3 / reader.ADC_MAX / reader.FrontEnd.case1().gain / rr
    assert np.max(np.abs(raw["i"] - i_exact)) < 2 * lsb_i
    # without it, I carries a ~-2 mA offset as large as the signal itself
    bad = reader.frontend_to_raw(cap, Rr=rr)
    assert abs(np.mean(bad["i"])) > 1e-3


def test_reference_counts_parsed_from_burst_lines():
    lines = case1_lines() + ["# burst=0 lines=600 cycles=3 ref_counts=1872.50 ovf=0",
                             "# burst=1 lines=600 cycles=3 ref_counts=1874.50 ovf=0"]
    assert _cap(lines).ref_counts == pytest.approx(1873.5)
    assert _cap(case1_lines()).ref_counts is None          # older firmware: no reference
    # the reference comes after the burst's last row: still found when parsing stops early
    assert reader.parse_capture(lines, max_cycles=1).ref_counts == pytest.approx(1872.5)


def test_reference_divider_drift_is_subtracted():
    # 2026-11-27: offsets moved up to ~0.25 V at the node within minutes, both channels alike.
    # The reference divider (GPIO32) moves with them; its shift since the zero is subtracted.
    off, drift, rr, r_dut = 60, 25, 1000.0, 1000.0
    zero = _cap(case1_lines(r_dut=np.inf, rr=rr, adc_offset=off) + [f"# burst=0 ref_counts={1873.0:.2f}"])
    cal_a, cal_b = reader.zero_cal(zero)
    assert cal_a.ref_counts == cal_b.ref_counts == pytest.approx(1873.0)
    later = case1_lines(r_dut, rr, adc_offset=off + drift)
    info = {}
    raw = reader.frontend_to_raw(_cap(later + [f"# burst=1 ref_counts={1873.0 + drift:.2f}"]),
                                 Rr=rr, cal_a=cal_a, cal_b=cal_b, info=info)
    assert info["ref_drift_counts"] == pytest.approx(drift)
    i_exact = 5.0 * np.sin(raw["phase"]) / (r_dut + rr)
    lsb_i = 3.3 / reader.ADC_MAX / reader.FrontEnd.case1().gain / rr
    assert np.max(np.abs(raw["i"] - i_exact)) < 2 * lsb_i
    # without the reference reading the same capture carries the drift as a current offset
    stale = reader.frontend_to_raw(_cap(later), Rr=rr, cal_a=cal_a, cal_b=cal_b)
    assert abs(np.mean(stale["i"]) - np.mean(i_exact)) > 10 * lsb_i


def test_zero_cal_refuses_a_capture_with_a_dut_in():
    with pytest.raises(ValueError, match="no DUT"):
        reader.zero_cal(_cap(case1_lines(r_dut=1000.0, rr=1000.0)))


def test_zero_flag_on_the_command_line(tmp_path, capsys):
    zero, cap = tmp_path / "zero.txt", tmp_path / "cap.txt"
    zero.write_text("\n".join(case1_lines(r_dut=np.inf, adc_offset=-216)) + "\n")
    cap.write_text("\n".join(case1_lines(adc_offset=-216)) + "\n")
    reader.main(["--file", str(cap), "--frontend", "--rr", "1000", "--zero", str(zero)])
    assert "zero-cal from" in capsys.readouterr().out


# ---- serial robustness (2026-11-27: CP2102 overflow re-delivered old 64-byte packets) ---------
def test_parse_drops_repeated_usb_packets():
    lines = fake_lines(n_cycles=6, junk=False)
    head, tail = lines[:60], lines[60:]
    replay = lines[50:58]                      # an old chunk comes through again, 3 times
    cap = reader.parse_capture(head + replay * 3 + tail)
    ref = reader.parse_capture(lines)
    assert cap.n_dup_lines == 24
    assert np.array_equal(cap.index, ref.index) and np.array_equal(cap.adc_v, ref.adc_v)


def test_parse_keeps_lost_rows_and_follows_a_board_reset():
    lines = fake_lines(n_cycles=3, junk=False)
    gap = lines[:40] + lines[45:]              # 5 rows lost: forward jump is fine
    assert reader.parse_capture(gap).n_dup_lines == 0
    restarted = lines + lines                  # board reset: meta + header, index back to 0
    cap = reader.parse_capture(restarted)
    assert cap.n_dup_lines == 0 and len(cap.index) == 2 * len(reader.parse_capture(lines).index)


def test_serial_lines_reassembles_bulk_reads():
    class FakePort:
        def __init__(self, data, size):
            self.chunks = [data[k:k + size] for k in range(0, len(data), size)]
        @property
        def in_waiting(self):
            return len(self.chunks[0]) if self.chunks else 0
        def read(self, n):
            return self.chunks.pop(0) if self.chunks else b""
    text = "\n".join(fake_lines(n_cycles=2, junk=False)) + "\n"
    port = FakePort(text.encode(), size=37)    # chunk edges fall mid-line
    got = [l.decode() for l in reader._serial_lines(port, time.monotonic() + 0.5)]
    assert got == text.splitlines()


# ---- per-channel gains + drive-phase alignment (2026-11-27, 988 ohm on the 1 kHz firmware) -----
def _lockin_r(raw):
    e = np.exp(-1j * raw["phase"])
    return abs(np.mean(raw["v"] * e)) / abs(np.mean(raw["i"] * e))


def test_case1_per_channel_gains_read_r_exactly():
    raw = reader.frontend_to_raw(reader.parse_capture(case1_lines(r_dut=988.0, rr=1022.0, n=1200)), Rr=1022.0)
    assert _lockin_r(raw) == pytest.approx(988.0, rel=2e-3)
    # one shared (average) gain is what read 998.6 ohm on the board
    avg = reader.FrontEnd(r_in=100.5e3, r_up=19.43e3, r_dn=19.47e3, v_supply=3.32, buffered=True)
    raw_avg = reader.frontend_to_raw(reader.parse_capture(case1_lines(r_dut=988.0, rr=1022.0, n=1200)),
                                     Rr=1022.0, fe=avg)
    assert _lockin_r(raw_avg) > 988.0 * 1.007


def test_phase_labels_aligned_to_node_a():
    info = {}
    lines = case1_lines(r_dut=1000.0, rr=1000.0, n=1200, label_lead_deg=14.0)
    raw = reader.frontend_to_raw(reader.parse_capture(lines), Rr=1000.0, info=info)
    assert info["phase_shift_deg"] == pytest.approx(-14.0, abs=0.3)
    i_exact = 5.0 * np.sin(raw["phase"]) / 2000.0          # drive = +A sin(phase) again
    assert np.max(np.abs(raw["i"] - i_exact)) < 0.03 * 5.0 / 2000.0
    off = reader.frontend_to_raw(reader.parse_capture(lines), Rr=1000.0, align_phase=False)
    assert np.allclose(off["v"], raw["v"]) and np.allclose(off["i"], raw["i"])   # V/I untouched

"""hardware/adc_check.py analysis helpers (no hardware needed)."""
import numpy as np
import pytest
import adc_check


def test_parse_step_lines_skips_junk_and_groups_by_code():
    lines = ["# adc_step ready", "dac_code,index,adc_counts", "28,0,300", "28,1,302",
             "48,0,600", "garbage", "48,1,9999", b"48,2,601\r\n", "# done"]
    steps = adc_check.parse_step_lines(lines)
    assert list(steps[28]) == [300, 302]
    assert list(steps[48]) == [600, 601]          # 9999 out of range dropped


def test_linearity_recovers_line_and_flags_bow():
    v = np.linspace(0.3, 3.0, 10)
    ideal = 1000 * v + 40
    gain, offset, res = adc_check.linearity(v, ideal)
    assert gain == pytest.approx(1000) and offset == pytest.approx(40) and np.abs(res).max() < 1e-6
    bowed = ideal + 6 * np.sin(np.pi * (v - v[0]) / (v[-1] - v[0]))
    assert np.abs(adc_check.linearity(v, bowed)[2]).max() > 2


def test_budget_is_about_two_counts_for_10mv_at_20v_scale():
    assert adc_check.PASS_COUNTS == pytest.approx(2.05, abs=0.01)


def test_verdict_thresholds():
    assert adc_check.verdict(1.0).startswith("PASS")
    assert adc_check.verdict(3.0).startswith("BORDERLINE")
    assert adc_check.verdict(9.0).startswith("FAIL")

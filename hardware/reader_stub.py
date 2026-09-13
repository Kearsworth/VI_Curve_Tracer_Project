"""
reader_stub.py — starting point for turning hardware output into the pipeline's raw dict.

This is a STUB. When the ESP32 firmware exists, implement `read_capture()` to read real
serial data. The rest of the ML pipeline (calibrate -> features -> verify) consumes the
dict returned here unchanged. See docs/DATA_CONTRACT.md sections 1 and 7.
"""
import numpy as np

# --- capture settings (must match how the hardware was configured) ---
DRIVE_FREQ_HZ = 1000.0
DRIVE_AMPL_V = 5.0        # A
SENSE_R_OHM = 1000.0      # Rr
ADC_VREF = 3.3
ADC_MAX = 4095            # 12-bit
ADC_BIAS_V = 1.65         # offset added in hardware so the signal is positive; removed here


def counts_to_volts(counts):
    """Convert raw ADC counts to a signed voltage (removing the hardware bias)."""
    return (np.asarray(counts, float) / ADC_MAX) * ADC_VREF - ADC_BIAS_V


def frame_to_raw(index, ch_v_counts, ch_i_counts,
                 f=DRIVE_FREQ_HZ, A=DRIVE_AMPL_V, Rr=SENSE_R_OHM, fs=None):
    """
    Turn arrays of (sample index, CH_V counts, CH_I counts) into the pipeline raw dict.
    `fs` = sample rate (Hz); if None, infer nothing and treat index as time steps of 1/fs.
    """
    index = np.asarray(index, float)
    v = counts_to_volts(ch_v_counts)                 # volts across DUT
    v_sense = counts_to_volts(ch_i_counts)           # volts across sense R
    i = v_sense / Rr                                 # current (A) via Ohm's law
    if fs is None:
        fs = f * 400.0                               # placeholder: 400 samples/cycle
    t = index / fs
    phase = 2 * np.pi * f * t                        # drive phase (rad), known from f
    return {"v": v, "i": i, "phase": phase, "A": A, "Rr": Rr}


def read_capture(port="/dev/ttyUSB0", baud=115200, n_cycles=4):
    """
    TODO: open the serial port with pyserial, read one capture (>= 1 full cycle),
    parse lines "index,ch_v,ch_i", and return frame_to_raw(...).
    For now this raises so it's obvious it isn't implemented.
    """
    raise NotImplementedError(
        "Implement serial reading here once the ESP32 firmware is ready. "
        "Return the dict from frame_to_raw(index, ch_v_counts, ch_i_counts)."
    )


if __name__ == "__main__":
    # Demo the conversion path with fake counts (a clean sine), no hardware needed.
    idx = np.arange(1600)
    fs = DRIVE_FREQ_HZ * 400
    t = idx / fs
    drive = np.sin(2 * np.pi * DRIVE_FREQ_HZ * t)
    ch_v = (drive * 0.5 + ADC_BIAS_V) / ADC_VREF * ADC_MAX      # fake DUT voltage
    ch_i = (drive * 0.5 + ADC_BIAS_V) / ADC_VREF * ADC_MAX      # fake sense voltage
    raw = frame_to_raw(idx, ch_v, ch_i, fs=fs)
    print("raw keys:", list(raw))
    print("v range:", round(raw["v"].min(), 2), "to", round(raw["v"].max(), 2), "V")
    print("shape check:", raw["v"].shape, raw["phase"].shape)

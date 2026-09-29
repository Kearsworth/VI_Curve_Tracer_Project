"""
live_plot_demo.py — live plot of the ESP32 sine capture, for demos.

Not part of the ML pipeline; a standalone tool for showing the DAC->ADC loopback sine
working in real time (e.g. to a professor). Arduino IDE's Serial Plotter only offers a
fixed list of baud rates (up to 2000000, but 921600 isn't one of the presets) and the
sketch's baud is a deliberate, already-validated choice (see firmware/esp32/README.md
Stage 3) — so rather than reflash at a different baud, this reads the real 921600 stream
directly with pyserial and plots it, which also shows both channels at once.

Usage:
    pip install pyserial            # matplotlib is already in requirements.txt
    python3 hardware/live_plot_demo.py --port /dev/cu.usbserial-XXXX
    (close the plot window, or Ctrl+C, to stop)

While it's running, click the plot window and use:
    space   pause / resume (freezes the view so you can point at a feature)
    , / .   slow down / speed up (adds a pause between redraws)
"""
import argparse
import collections
import sys

import matplotlib.pyplot as plt

DELAY_STEP = 0.05   # seconds added/removed per , or . press


def _status_text(state):
    running = "PAUSED" if state["paused"] else "running"
    return f"{running}  |  delay {state['delay']:.2f}s   (space=pause, ,/.=speed)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True, help="e.g. /dev/cu.usbserial-0001")
    ap.add_argument("--baud", type=int, default=921600, help="must match the sketch's BAUD")
    ap.add_argument("--window", type=int, default=600, help="samples kept on screen")
    ap.add_argument("--delay", type=float, default=0.0,
                     help="seconds to pause after each redraw, i.e. how slow the graph "
                          "scrolls (default 0 = as fast as data arrives); adjustable live "
                          "with , and .")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        sys.exit("pyserial is required: pip install pyserial")

    ser = serial.Serial(args.port, args.baud, timeout=1.0)

    ADC_MAX, ADC_VREF = 4095, 3.3                     # 12-bit ADC, 0..3.3V pin range

    xs = collections.deque(maxlen=args.window)
    adc_v = collections.deque(maxlen=args.window)
    adc_i = collections.deque(maxlen=args.window)
    volts_v = collections.deque(maxlen=args.window)
    volts_i = collections.deque(maxlen=args.window)

    plt.ion()
    fig, (ax_counts, ax_volts) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)

    line_v, = ax_counts.plot([], [], label="adc_v_counts", linewidth=1.6)
    line_i, = ax_counts.plot([], [], label="adc_i_counts", linewidth=1.2, linestyle="--", alpha=.7)
    ax_counts.set_ylabel("ADC counts (0-4095)")
    ax_counts.set_ylim(0, ADC_MAX)
    ax_counts.set_title(f"ESP32 DAC→ADC loopback — live @ {args.baud} baud")
    ax_counts.legend(loc="upper right")
    ax_counts.grid(alpha=.3)

    # counts -> volts at the ADC pin: raw = counts/4095*3.3 (ideal, no per-channel
    # offset/gain correction — see hardware/reader.py ChannelCal for that)
    line_vv, = ax_volts.plot([], [], color=line_v.get_color(), label="V at ADC pin", linewidth=1.6)
    line_vi, = ax_volts.plot([], [], color=line_i.get_color(), label="I-sense at ADC pin",
                              linewidth=1.2, linestyle="--", alpha=.7)
    ax_volts.set_xlabel("sample #")
    ax_volts.set_ylabel("volts (V)")
    ax_volts.set_ylim(0, ADC_VREF)
    ax_volts.legend(loc="upper right")
    ax_volts.grid(alpha=.3)

    state = {"delay": max(0.0, args.delay), "paused": False}
    status = fig.text(0.99, 0.99, _status_text(state), ha="right", va="top",
                       fontsize=9, family="monospace")

    def on_key(event):
        if event.key == " ":
            state["paused"] = not state["paused"]
        elif event.key in (",", "left"):
            state["delay"] = round(state["delay"] + DELAY_STEP, 2)
        elif event.key in (".", "right"):
            state["delay"] = max(0.0, round(state["delay"] - DELAY_STEP, 2))
        else:
            return
        status.set_text(_status_text(state))
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("key_press_event", on_key)

    n = 0
    print(f"listening on {args.port} @ {args.baud} baud — close the plot window to stop")
    print("click the plot window, then: space=pause/resume  ,=slower  .=faster")
    try:
        while plt.fignum_exists(fig.number):
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if not line or line.startswith("#") or line.startswith("index"):
                continue
            parts = line.split(",")
            if len(parts) != 5:
                continue
            try:
                v, i = int(parts[3]), int(parts[4])
            except ValueError:
                continue

            if state["paused"]:
                # keep draining the port (avoids the OS buffer filling up while frozen)
                # but don't touch the buffers or redraw — the view stays put.
                plt.pause(0.05)
                continue

            n += 1
            xs.append(n)
            adc_v.append(v)
            adc_i.append(i)
            volts_v.append(v / ADC_MAX * ADC_VREF)
            volts_i.append(i / ADC_MAX * ADC_VREF)

            if n % 15 == 0:                          # redraw every ~15 samples, not every one
                line_v.set_data(xs, adc_v)
                line_i.set_data(xs, adc_i)
                line_vv.set_data(xs, volts_v)
                line_vi.set_data(xs, volts_i)
                ax_counts.set_xlim(max(0, n - args.window), n)
                if state["delay"] > 0:
                    plt.pause(state["delay"])         # redraws AND sleeps AND stays clickable
                else:
                    fig.canvas.draw_idle()
                    fig.canvas.flush_events()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == "__main__":
    main()

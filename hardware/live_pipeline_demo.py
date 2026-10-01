"""
live_pipeline_demo.py — real-time dashboard of BOTH boards + the ML pipeline, live.

Not the static "Signal Path" artifact (that's a snapshot for reference). This actually opens
both serial ports and updates continuously as real data streams in: GEN's output -> CAP's
capture -> reader.py -> calibrate.py -> features.py -> verify.py, all running locally because
only local Python has real serial access (a browser page can't reach /dev/cu.usbserial-*).

Three live panels:
  left    raw volts at CAP's ADC pins, scrolling in real time (proves data is actually moving)
  middle  the calibrated V-I loop, redrawn every time enough new full cycles have arrived
  right   the current verify() verdict + key features, updated the same moments

Controls (click the plot window first so it has keyboard focus):
    r / c / d   switch GEN's signature live (sent over GEN's own serial port)
    space       pause / resume the live view
    , / .       slow down / speed up the redraw rate
    q           quit

Usage:
    python3 hardware/live_pipeline_demo.py --gen-port /dev/cu.usbserial-0001 --cap-port /dev/cu.usbserial-9
"""
import argparse
import collections
import os
import sys
import time

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vi_ml"))
import calibrate
import features

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reader

FEATURE_HIGHLIGHTS = ["aspect", "slope0", "symmetry", "n_segments"]
A_PLACEHOLDER = 1.29
RR_PLACEHOLDER = 1.0
SHAPE_LABEL = {"R": "line (R)", "C": "ellipse (C/L)", "D": "knee (D)"}


def _status_text(state):
    running = "PAUSED" if state["paused"] else "running"
    return (f"{running} | shape {state['shape']} | delay {state['delay']:.2f}s\n"
            f"space=pause  ,/.=speed  r/c/d=shape  q=quit")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gen-port", required=True)
    ap.add_argument("--cap-port", required=True)
    ap.add_argument("--window", type=int, default=400, help="raw samples kept on the scroll plot")
    ap.add_argument("--refresh-lines", type=int, default=40,
                     help="try a pipeline update every this many new raw lines")
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--duration", type=float, help="auto-quit after this many seconds (for testing)")
    args = ap.parse_args()

    import serial

    gen = serial.Serial(args.gen_port, 115200, timeout=0.5)
    time.sleep(1.0)
    gen.reset_input_buffer()

    cap = serial.Serial(args.cap_port, 921600, timeout=0.5)
    time.sleep(1.0)
    cap.reset_input_buffer()

    def send_shape(shape):
        gen.reset_input_buffer()
        gen.write(f"{shape}\n".encode())
        time.sleep(0.05)

    state = {"paused": False, "delay": max(0.0, args.delay), "shape": "R"}
    send_shape(state["shape"])

    xs = collections.deque(maxlen=args.window)
    volts_v = collections.deque(maxlen=args.window)
    volts_i = collections.deque(maxlen=args.window)
    line_buf = collections.deque(maxlen=2000)   # raw CSV text lines, for the pipeline stages

    plt.ion()
    fig, ((ax_scroll, ax_rawvi), (ax_loop, ax_text)) = plt.subplots(2, 2, figsize=(12, 10))

    line_v, = ax_scroll.plot([], [], label="V", linewidth=1.4)
    line_i, = ax_scroll.plot([], [], label="I", linewidth=1.2, linestyle="--", alpha=.8)
    ax_scroll.set_title("CAP: live ADC (volts) vs sample #")
    ax_scroll.set_xlabel("sample #")
    ax_scroll.set_ylabel("volts")
    ax_scroll.set_ylim(0, 3.3)
    ax_scroll.legend(loc="upper right")
    ax_scroll.grid(alpha=.3)

    rawvi_line, = ax_rawvi.plot([], [], linewidth=1.2, marker=".", markersize=3, alpha=.7)
    ax_rawvi.set_title("CAP: raw I vs V (before calibrate.py)")
    ax_rawvi.set_xlabel("V (volts, raw)")
    ax_rawvi.set_ylabel("I (volts, raw)")
    ax_rawvi.set_xlim(0, 3.3)
    ax_rawvi.set_ylim(0, 3.3)
    ax_rawvi.set_aspect("equal", adjustable="box")
    ax_rawvi.grid(alpha=.3)

    loop_line, = ax_loop.plot([], [], linewidth=1.6)
    ax_loop.axhline(0, color="0.8", linewidth=.8)
    ax_loop.axvline(0, color="0.8", linewidth=.8)
    ax_loop.set_title("calibrate.py: V-I signature")
    ax_loop.set_xlabel("V (normalized)")
    ax_loop.set_ylabel("I (normalized)")
    ax_loop.set_aspect("equal", adjustable="box")
    ax_loop.grid(alpha=.3)

    ax_text.axis("off")
    verdict_txt = ax_text.text(0.02, 0.98, "waiting for first full capture...", va="top",
                                fontsize=10, family="monospace", transform=ax_text.transAxes)

    status = fig.text(0.99, 0.99, _status_text(state), ha="right", va="top",
                       fontsize=9, family="monospace")

    def on_key(event):
        if event.key == " ":
            state["paused"] = not state["paused"]
        elif event.key in (",", "left"):
            state["delay"] = round(state["delay"] + 0.05, 2)
        elif event.key in (".", "right"):
            state["delay"] = max(0.0, round(state["delay"] - 0.05, 2))
        elif event.key in ("r", "c", "d"):
            state["shape"] = event.key.upper()
            send_shape(state["shape"])
        elif event.key == "q":
            plt.close(fig)
            return
        else:
            return
        status.set_text(_status_text(state))
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("key_press_event", on_key)

    print(f"GEN={args.gen_port}  CAP={args.cap_port}  shape={state['shape']}")
    print("click the plot window, then: r/c/d=shape  space=pause  ,/.=speed  q=quit")

    n = 0
    t_start = time.time()
    last_draw = 0.0
    MIN_DRAW_INTERVAL = 0.05   # redraw the GUI at most ~20x/sec, not once per serial line
    try:
        while plt.fignum_exists(fig.number):
            if args.duration and time.time() - t_start > args.duration:
                break

            raw_line = cap.readline()
            if not raw_line:
                plt.pause(0.01)
                continue
            text = raw_line.decode(errors="replace").strip()
            if state["paused"]:
                plt.pause(0.02)
                continue
            if not text or text.startswith("#") or text.startswith("index"):
                continue
            parts = text.split(",")
            if len(parts) != 5:
                continue
            try:
                v_counts, i_counts = int(parts[3]), int(parts[4])
            except ValueError:
                continue

            n += 1
            xs.append(n)
            volts_v.append(v_counts / 4095 * 3.3)
            volts_i.append(i_counts / 4095 * 3.3)
            line_buf.append(text)

            if n % 8 == 0:
                line_v.set_data(xs, volts_v)
                line_i.set_data(xs, volts_i)
                ax_scroll.set_xlim(max(0, n - args.window), n)
                rawvi_line.set_data(volts_v, volts_i)   # x=V, y=I, per this panel's own labels

            if n % args.refresh_lines == 0:
                try:
                    parsed = reader.parse_capture(list(line_buf))
                    raw = reader.capture_to_raw(parsed, A=A_PLACEHOLDER, Rr=RR_PLACEHOLDER)
                    sig = calibrate.calibrate(raw)
                    x = features.extract(sig)
                    fnames = features.FEATURE_NAMES if hasattr(features, "FEATURE_NAMES") else \
                        ["signed_area","abs_area","slope0","phaseVI","aspect","knee_V",
                         "symmetry","rms_radius","n_segments","peakV","peakI","spread_ratio"]

                    import verify as verify_mod
                    result = verify_mod.verify(raw)

                    n_raw = len(raw['v'])
                    loop_line.set_data(sig[:, 0], sig[:, 1])
                    m = max(0.1, abs(sig).max() * 1.15)
                    ax_loop.set_xlim(-m, m)
                    ax_loop.set_ylim(-m, m)
                    ax_loop.set_title(f"calibrate.py: {n_raw} raw → {sig.shape[0]}×{sig.shape[1]}"
                                       f"  ({state['shape']} = {SHAPE_LABEL[state['shape']]})")

                    feat_lines = "\n".join(f"  {n2:12s} {v2:+.3f}" for n2, v2 in
                                            zip(fnames, x) if n2 in FEATURE_HIGHLIGHTS)
                    verdict_color = "green" if result["verdict"] == "GOOD" else "red"
                    verdict_txt.set_text(
                        f"PIPELINE TRACE\n"
                        f"{'-'*24}\n"
                        f"raw (reader.py)\n"
                        f"  {n_raw} pts × 3 (v,i,phase)\n"
                        f"  = {n_raw*3} raw numbers\n"
                        f"calibrated (calibrate.py)\n"
                        f"  {sig.shape[0]} pts × {sig.shape[1]} (V,I) FIXED\n"
                        f"  = {sig.shape[0]*sig.shape[1]} numbers\n"
                        f"features (features.py)\n"
                        f"  {len(x)} numbers\n\n"
                        f"verify.py output\n"
                        f"{'-'*24}\n"
                        f"type       {result['type']}\n"
                        f"verdict    {result['verdict']}\n"
                        f"confidence {result['confidence']:.3f}\n"
                        f"anomaly    {result['anomaly']}\n"
                        f"a_score    {result['anomaly_score']:.3f}\n\n"
                        f"features (highlights)\n{feat_lines}"
                    )
                    verdict_txt.set_color(verdict_color)
                    print(f"[{state['shape']}] verdict={result['verdict']} type={result['type']} "
                          f"conf={result['confidence']:.3f} anomaly={result['anomaly']}")
                except ValueError:
                    pass   # not enough full cycles in the buffer yet -- try again next window

            now_t = time.time()
            if state["delay"] > 0:
                if now_t - last_draw >= state["delay"]:
                    plt.pause(state["delay"])
                    last_draw = now_t
            elif now_t - last_draw >= MIN_DRAW_INTERVAL:
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                last_draw = now_t
    except KeyboardInterrupt:
        pass
    finally:
        gen.close()
        cap.close()


if __name__ == "__main__":
    main()

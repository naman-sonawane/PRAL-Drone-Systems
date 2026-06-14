"""
Stage 2 stream server -- replays a local video file and simulates
overflight sensor data (rangefinder, drone pose) in real time.

Usage:
    python -m pipeline.stage2.stream_server --video DJI_0009.MP4 [--port 5002] [--fps 10]

Endpoints:
    GET /frame              -- single JPEG snapshot (nadir frame)
    GET /video_feed         -- MJPEG stream (multipart/x-mixed-replace)
    GET /status             -- JSON {frame_index, total_frames, fps}
    GET /rangefinder        -- JSON {timestamp, range_m, drone_pos_enu}
    GET /overflight_status  -- JSON {phase, h_survey, waypoint_index, total_waypoints}
"""
from __future__ import annotations

import argparse
import math
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_lock = threading.Lock()

# Video replay
_cap: cv2.VideoCapture | None = None
_frame_index: int = 0
_total_frames: int = 0
_fps: float = 10.0
_current_jpeg: bytes = b""

# Mock overflight state
_h_survey: float = 30.0
_waypoints: list = []          # list of (e, n, u)
_waypoint_index: int = 0
_rangefinder_reading: dict = {}
_overflight_phase: str = "idle"

# Simulated building (for synthetic rangefinder)
_aoi_half_e: float = 10.0
_aoi_half_n: float = 8.0
_H_true: float = 15.0


# ---------------------------------------------------------------------------
# Video replay thread
# ---------------------------------------------------------------------------

def _advance_frame() -> None:
    global _frame_index, _current_jpeg
    with _lock:
        if _cap is None:
            return
        ret, frame = _cap.read()
        if not ret:
            _cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = _cap.read()
            _frame_index = 0
        if ret:
            _frame_index += 1
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            _current_jpeg = buf.tobytes()


def _video_reader_thread() -> None:
    while True:
        _advance_frame()
        time.sleep(1.0 / _fps)


# ---------------------------------------------------------------------------
# Mock overflight thread
# ---------------------------------------------------------------------------

def _generate_waypoints() -> list:
    """Simple E-W lawnmower over a ±aoi_half bounding box."""
    e_min, e_max = -_aoi_half_e - 2, _aoi_half_e + 2
    n_min, n_max = -_aoi_half_n - 2, _aoi_half_n + 2
    wps = []
    n_cur = n_min
    direction = 1
    while n_cur <= n_max + 0.5:
        if direction == 1:
            wps += [(e_min, n_cur, _h_survey), (e_max, n_cur, _h_survey)]
        else:
            wps += [(e_max, n_cur, _h_survey), (e_min, n_cur, _h_survey)]
        n_cur += 5.0
        direction *= -1
    return wps


def _is_over_building(e: float, n: float) -> bool:
    return abs(e) <= _aoi_half_e and abs(n) <= _aoi_half_n


def _overflight_thread() -> None:
    global _waypoint_index, _rangefinder_reading, _overflight_phase
    rng = np.random.default_rng(99)

    while True:
        with _lock:
            wps = _waypoints
            phase = _overflight_phase

        if not wps or phase == "idle":
            time.sleep(0.5)
            continue

        total = len(wps)
        idx = _waypoint_index % total
        e_wp, n_wp, u_wp = wps[idx]

        # Interpolate along current strip at drone speed 2 m/s
        next_idx = (idx + 1) % total
        e_next, n_next, _ = wps[next_idx]
        seg_len = math.sqrt((e_next - e_wp) ** 2 + (n_next - n_wp) ** 2)
        travel_time = seg_len / 2.0  # seconds

        steps = max(4, int(seg_len / 2.0))
        for k in range(steps):
            frac = k / max(steps - 1, 1)
            e_pos = e_wp + frac * (e_next - e_wp) + float(rng.uniform(-0.3, 0.3))
            n_pos = n_wp + frac * (n_next - n_wp) + float(rng.uniform(-0.3, 0.3))
            over = _is_over_building(e_pos, n_pos)
            noise = float(rng.normal(0, 0.05))
            range_m = (_h_survey - _H_true if over else _h_survey) + noise

            reading = {
                "timestamp": time.time(),
                "range_m": round(max(0.5, range_m), 3),
                "drone_pos_enu": [round(e_pos, 2), round(n_pos, 2), round(u_wp, 2)],
                "over_building": over,
            }
            with _lock:
                _rangefinder_reading = reading
                _waypoint_index = idx

            time.sleep(travel_time / steps)

        with _lock:
            _waypoint_index = next_idx


# ---------------------------------------------------------------------------
# Flask endpoints
# ---------------------------------------------------------------------------

@app.route("/frame")
def frame_endpoint():
    data = _current_jpeg if _current_jpeg else b""
    return Response(data, mimetype="image/jpeg")


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            data = _current_jpeg
            if data:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                )
            time.sleep(1.0 / _fps)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/status")
def status():
    return jsonify({
        "frame_index": _frame_index,
        "total_frames": _total_frames,
        "fps": _fps,
    })


@app.route("/rangefinder")
def rangefinder():
    with _lock:
        reading = dict(_rangefinder_reading)
    if not reading:
        return jsonify({"error": "no reading yet"}), 503
    return jsonify(reading)


@app.route("/overflight_status")
def overflight_status():
    with _lock:
        return jsonify({
            "phase": _overflight_phase,
            "h_survey": _h_survey,
            "waypoint_index": _waypoint_index,
            "total_waypoints": len(_waypoints),
            "H_true_mock": _H_true,
        })


@app.route("/overflight/start", methods=["POST"])
def overflight_start():
    global _overflight_phase
    with _lock:
        _overflight_phase = "flying"
    return jsonify({"status": "started"})


@app.route("/overflight/stop", methods=["POST"])
def overflight_stop():
    global _overflight_phase
    with _lock:
        _overflight_phase = "idle"
    return jsonify({"status": "stopped"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _cap, _total_frames, _fps, _h_survey, _waypoints, _H_true
    global _overflight_phase

    parser = argparse.ArgumentParser(description="PRAL Stage 2 stream server")
    parser.add_argument("--video", required=True, help="Video file to replay as nadir frames")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--fps", type=float, default=10.0, help="Replay frame rate")
    parser.add_argument("--h-survey", type=float, default=30.0, help="Mock survey altitude (m AGL)")
    parser.add_argument("--h-true", type=float, default=15.0, help="Simulated building height (m)")
    parser.add_argument("--aoi-half-e", type=float, default=10.0, help="AOI half-width East (m)")
    parser.add_argument("--aoi-half-n", type=float, default=8.0, help="AOI half-width North (m)")
    parser.add_argument("--autostart", action="store_true", help="Start overflight immediately")
    args = parser.parse_args()

    _fps = args.fps
    _h_survey = args.h_survey
    _H_true = args.h_true
    _aoi_half_e = args.aoi_half_e  # type: ignore[assignment]
    _aoi_half_n = args.aoi_half_n  # type: ignore[assignment]

    _cap = cv2.VideoCapture(args.video)
    if not _cap.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")
    _total_frames = int(_cap.get(cv2.CAP_PROP_FRAME_COUNT))

    _waypoints.extend(_generate_waypoints())
    if args.autostart:
        _overflight_phase = "flying"

    print(f"[stage2-stream] {args.video}  --  {_total_frames} frames at {_fps} fps")
    print(f"[stage2-stream] h_survey={_h_survey} m  H_true={_H_true} m")
    print(f"[stage2-stream] {len(_waypoints)} waypoints generated")
    print(f"[stage2-stream] Serving on http://localhost:{args.port}")
    print(f"[stage2-stream]   /frame             -> nadir JPEG")
    print(f"[stage2-stream]   /video_feed        -> MJPEG stream")
    print(f"[stage2-stream]   /status            -> frame metadata")
    print(f"[stage2-stream]   /rangefinder       -> live rangefinder JSON")
    print(f"[stage2-stream]   /overflight_status -> overflight state JSON")
    print(f"[stage2-stream]   POST /overflight/start|stop -> control overflight")

    threading.Thread(target=_video_reader_thread, daemon=True).start()
    threading.Thread(target=_overflight_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()

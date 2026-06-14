"""
Fake live-stream server -- replays a local video file as an MJPEG stream.

Usage:
    python pipeline/stream_server.py --video DJI_0009.MP4 [--port 5001] [--fps 10]

Endpoints:
    GET /frame        -- single JPEG snapshot (polled by Streamlit)
    GET /video_feed   -- MJPEG stream (multipart/x-mixed-replace)
    GET /status       -- JSON {frame_index, total_frames, fps}
"""
import argparse
import threading
import time

import cv2
from flask import Flask, Response, jsonify

app = Flask(__name__)

_cap: cv2.VideoCapture | None = None
_lock = threading.Lock()
_frame_index = 0
_total_frames = 0
_fps: float = 10.0
_current_jpeg: bytes = b""


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


def _background_reader() -> None:
    """Advance frames at the configured FPS regardless of client connections."""
    while True:
        _advance_frame()
        time.sleep(1.0 / _fps)


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

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/status")
def status():
    return jsonify(
        {
            "frame_index": _frame_index,
            "total_frames": _total_frames,
            "fps": _fps,
        }
    )


def main() -> None:
    global _cap, _total_frames, _fps

    parser = argparse.ArgumentParser(description="PRAL fake drone live-stream server")
    parser.add_argument("--video", required=True, help="Path to the video file to replay")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--fps", type=float, default=10.0, help="Replay frame rate")
    args = parser.parse_args()

    _fps = args.fps
    _cap = cv2.VideoCapture(args.video)
    if not _cap.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")

    _total_frames = int(_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[stream] {args.video}  --  {_total_frames} frames at {_fps} fps replay")
    print(f"[stream] Serving on http://localhost:{args.port}")
    print(f"[stream]   /frame      -> single JPEG")
    print(f"[stream]   /video_feed -> MJPEG stream")
    print(f"[stream]   /status     -> JSON metadata")

    threading.Thread(target=_background_reader, daemon=True).start()
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()

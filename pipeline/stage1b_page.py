"""
Stage 1b -- AOI Annotation (Streamlit wrapper)

Launches the stage1b FastAPI server as a background process (if not already
running) and embeds it in an iframe.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Stage 1b -- AOI Annotation", layout="wide")

SERVER_PORT = 8000
SERVER_URL  = f"http://localhost:{SERVER_PORT}"
SERVER_SCRIPT = str(Path(__file__).resolve().parent / "stage1b" / "server.py")


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("localhost", port)) == 0


# ---------------------------------------------------------------------------
# Launch server if not already up
# ---------------------------------------------------------------------------
if not _port_open(SERVER_PORT):
    st.info(f"Starting stage1b server on port {SERVER_PORT}...")
    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait up to 5 s for the server to be ready
    for _ in range(50):
        if _port_open(SERVER_PORT):
            break
        time.sleep(0.1)
    else:
        st.error(
            f"Stage1b server did not start within 5 s. "
            f"Start it manually:\n\n```\npython {SERVER_SCRIPT}\n```"
        )
        st.stop()

# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------
st.title("Stage 1b -- AOI Annotation")
st.caption(f"Served by FastAPI at {SERVER_URL}")

components.iframe(SERVER_URL, height=780, scrolling=True)

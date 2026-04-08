#!/usr/bin/env python3
"""
hexplayer.py — HexPlayer main daemon
─────────────────────────────────────
Reads NFC tiles and triggers Spotify playback via the Spotify Web API.
Designed to run as a systemd service on Raspberry Pi OS Bookworm.

Usage:
    python3 hexplayer.py

Environment variables are loaded from .env (see .env.example).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv()

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hexplayer")

# ── Constants ─────────────────────────────────────────────────────────────────
TILES_FILE = Path(__file__).parent / "tiles.json"
DEBOUNCE_SECONDS = float(os.getenv("DEBOUNCE_SECONDS", "3"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.2"))
DEVICE_NAME = os.getenv("DEVICE_NAME", "HexPlayer")
NFC_RESET_PIN = int(os.getenv("NFC_RESET_PIN", "25"))

# ── Graceful shutdown ─────────────────────────────────────────────────────────
_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("🛑  Received signal %s — shutting down…", signal.Signals(signum).name)
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── Tile registry ─────────────────────────────────────────────────────────────

class TileRegistry:
    """
    Lazy-loads tiles.json and reloads it only when the file has been modified.
    Maps NFC UID strings to Spotify URIs.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float = 0.0
        self._tiles: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            log.warning("⚠️  tiles.json not found — no tiles registered yet")
            self._tiles = {}
            self._mtime = 0.0
            return
        mtime = self._path.stat().st_mtime
        if mtime == self._mtime:
            return
        try:
            with self._path.open() as fh:
                data = json.load(fh)
            self._tiles = {str(k): str(v) for k, v in data.items()}
            self._mtime = mtime
            log.info("📂  Loaded %d tile(s) from tiles.json", len(self._tiles))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("❌  Failed to reload tiles.json: %s", exc)

    def get_uri(self, uid: str) -> Optional[str]:
        """Return the Spotify URI for *uid*, reloading the file if needed."""
        self._load()
        return self._tiles.get(uid)

    def known_uids(self) -> list[str]:
        """Return all registered UIDs (triggers a reload check)."""
        self._load()
        return list(self._tiles.keys())


# ── Spotify client ────────────────────────────────────────────────────────────

def _build_spotify_client():
    """
    Authenticate with Spotify using the Authorization Code flow with PKCE.
    Credentials are read from environment variables.
    Returns a spotipy.Spotify instance or raises SystemExit on failure.
    """
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        log.critical("❌  spotipy is not installed — run: pip install -r requirements.txt")
        sys.exit(1)

    client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

    if not client_id or not client_secret:
        log.critical(
            "❌  SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env"
        )
        sys.exit(1)

    scope = (
        "user-read-playback-state "
        "user-modify-playback-state "
        "user-read-currently-playing"
    )

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        open_browser=False,
        cache_path=str(Path(__file__).parent / ".spotify_cache"),
    )
    sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10, retries=3)
    log.info("✅  Spotify client authenticated")
    return sp


def get_device_id(sp=None) -> Optional[str]:
    """
    Return the Spotify Connect device ID for DEVICE_NAME / DEVICE_ID.
    Tries the env-configured ID first; falls back to name-based lookup.
    """
    explicit_id = os.getenv("DEVICE_ID", "").strip()
    if explicit_id:
        return explicit_id

    if sp is None:
        return None

    try:
        devices = sp.devices().get("devices", [])
    except Exception as exc:
        log.warning("⚠️  Could not list Spotify devices: %s", exc)
        return None

    for device in devices:
        if device.get("name", "").lower() == DEVICE_NAME.lower():
            device_id = device["id"]
            log.info("🔍  Found device '%s' → %s", DEVICE_NAME, device_id)
            return device_id

    if devices:
        log.warning(
            "⚠️  Device '%s' not found; available: %s",
            DEVICE_NAME,
            [d["name"] for d in devices],
        )
    else:
        log.warning("⚠️  No active Spotify devices found — is Raspotify running?")
    return None


def start_playback(sp, uri: str, device_id: Optional[str]) -> bool:
    """
    Start playback of *uri* on *device_id*.
    Handles playlists, albums, tracks, and artist top-tracks URIs.
    Returns True on success.
    """
    kwargs: dict = {"device_id": device_id}

    if uri.startswith("spotify:track:"):
        kwargs["uris"] = [uri]
    elif uri.startswith(("spotify:playlist:", "spotify:album:", "spotify:artist:")):
        kwargs["context_uri"] = uri
    else:
        # Unknown URI type — try as context_uri and hope for the best
        log.warning("⚠️  Unrecognised URI type: %s — attempting as context_uri", uri)
        kwargs["context_uri"] = uri

    try:
        sp.start_playback(**kwargs)
        log.info("▶️   Playing %s", uri)
        return True
    except Exception as exc:  # spotipy raises SpotifyException
        log.error("❌  Playback error for %s: %s", uri, exc)
        return False


# ── NFC reader ────────────────────────────────────────────────────────────────

def _build_nfc_reader():
    """
    Initialise the RC522 reader using the pi-rc522 library.
    Returns an RFID reader instance or raises SystemExit if unavailable.
    """
    try:
        from pirc522 import RFID
    except ImportError:
        log.critical(
            "❌  pirc522 is not installed — run: pip install -r requirements.txt\n"
            "    Also ensure SPI is enabled: sudo raspi-config → Interface Options → SPI"
        )
        sys.exit(1)

    try:
        reader = RFID(pin_rst=NFC_RESET_PIN)
        log.info("📡  NFC reader initialised (reset pin GPIO%d)", NFC_RESET_PIN)
        return reader
    except Exception as exc:
        log.critical("❌  Failed to initialise NFC reader: %s", exc)
        sys.exit(1)


def read_uid(reader) -> Optional[str]:
    """
    Non-blocking UID read.  Returns a hex UID string if a card was present,
    otherwise returns None.
    """
    reader.wait_for_tag()
    error, tag_type = reader.request()
    if error:
        return None
    error, uid = reader.anticoll()
    if error:
        return None
    return "-".join(f"{b:02X}" for b in uid)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("╔══════════════════════════════════════╗")
    print("║  🎵  HexPlayer — NFC Spotify Player  ║")
    print("╚══════════════════════════════════════╝")
    print()

    # --- Spotify ---
    sp = _build_spotify_client()

    # --- NFC ---
    reader = _build_nfc_reader()

    # --- Tile registry ---
    registry = TileRegistry(TILES_FILE)

    # --- Resolve device ---
    device_id = get_device_id(sp)

    log.info("🚀  HexPlayer started — waiting for tiles…")
    log.info("    Device : %s", device_id or "(auto-detect on first tap)")
    log.info("    Tiles  : %s", TILES_FILE)

    last_uid: Optional[str] = None
    last_trigger_time: float = 0.0

    while _running:
        try:
            uid = read_uid(reader)
        except Exception as exc:
            log.error("❌  NFC read error: %s", exc)
            time.sleep(1.0)
            continue

        if uid is None:
            # No card present — reset last_uid so removing & re-tapping works
            last_uid = None
            time.sleep(POLL_INTERVAL)
            continue

        now = time.monotonic()

        # Anti-bounce: ignore the same tile within DEBOUNCE_SECONDS
        if uid == last_uid and (now - last_trigger_time) < DEBOUNCE_SECONDS:
            time.sleep(POLL_INTERVAL)
            continue

        last_uid = uid
        last_trigger_time = now

        uri = registry.get_uri(uid)
        if uri is None:
            log.warning("❓  Unknown tile %s — register it with register.py", uid)
            time.sleep(POLL_INTERVAL)
            continue

        log.info("🏷️   Tile tapped: %s → %s", uid, uri)

        # Re-resolve device ID on each tap in case Raspotify restarted
        if not device_id:
            device_id = get_device_id(sp)

        if device_id is None:
            log.warning("⚠️  No active device — retrying device lookup in 5 s…")
            time.sleep(5)
            device_id = get_device_id(sp)
            if device_id is None:
                log.error("❌  Still no device — skipping playback for this tap")
                continue

        start_playback(sp, uri, device_id)
        time.sleep(POLL_INTERVAL)

    log.info("👋  HexPlayer stopped cleanly")


if __name__ == "__main__":
    main()

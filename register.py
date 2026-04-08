#!/usr/bin/env python3
"""
register.py — HexPlayer tile registration tool
───────────────────────────────────────────────
Interactive CLI to associate NFC tile UIDs with Spotify URIs.

Usage:
    python3 register.py

Steps:
  1. Paste a Spotify URI when prompted.
  2. Tap the NFC tile you want to link.
  3. The mapping is saved to tiles.json automatically.

Tip: find URIs by right-clicking any playlist / album / track in the Spotify
app → Share → Copy Spotify URI.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("register")

# ── Constants ─────────────────────────────────────────────────────────────────
TILES_FILE = Path(__file__).parent / "tiles.json"
NFC_RESET_PIN = int(os.getenv("NFC_RESET_PIN", "25"))
TILE_READ_TIMEOUT = 30  # seconds to wait for a tile tap

# ── Graceful shutdown ─────────────────────────────────────────────────────────
_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    print("\n\n👋  Interrupted — exiting.")
    _running = False
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── tiles.json helpers ────────────────────────────────────────────────────────

def load_tiles() -> dict[str, str]:
    """Return existing tile mappings, or an empty dict if the file is absent."""
    if not TILES_FILE.exists():
        return {}
    try:
        with TILES_FILE.open() as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("❌  Could not read tiles.json: %s", exc)
        return {}


def save_tiles(tiles: dict[str, str]) -> None:
    """Write tile mappings to tiles.json with pretty formatting."""
    try:
        with TILES_FILE.open("w") as fh:
            json.dump(tiles, fh, indent=2, sort_keys=True)
            fh.write("\n")
        log.info("💾  Saved %d tile(s) to %s", len(tiles), TILES_FILE)
    except OSError as exc:
        log.error("❌  Could not write tiles.json: %s", exc)


# ── URI validation ────────────────────────────────────────────────────────────

VALID_URI_PREFIXES = (
    "spotify:track:",
    "spotify:playlist:",
    "spotify:album:",
    "spotify:artist:",
)


def validate_uri(uri: str) -> bool:
    """Return True if *uri* looks like a valid Spotify URI."""
    return any(uri.startswith(prefix) for prefix in VALID_URI_PREFIXES)


# ── NFC helpers ───────────────────────────────────────────────────────────────

def _build_nfc_reader():
    """Initialise the RC522 reader using pi-rc522."""
    try:
        from pirc522 import RFID
    except ImportError:
        print(
            "\n❌  pirc522 is not installed.\n"
            "    Run: pip install -r requirements.txt\n"
            "    Also ensure SPI is enabled: sudo raspi-config → Interface Options → SPI\n"
        )
        sys.exit(1)

    try:
        reader = RFID(pin_rst=NFC_RESET_PIN)
        print(f"📡  NFC reader ready (reset pin GPIO{NFC_RESET_PIN})")
        return reader
    except Exception as exc:
        print(f"\n❌  Failed to initialise NFC reader: {exc}\n")
        sys.exit(1)


def read_uid_with_timeout(reader, timeout: float = TILE_READ_TIMEOUT) -> str | None:
    """
    Poll for a card until one is read or *timeout* seconds elapse.
    Returns a hex UID string or None on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _running:
        reader.wait_for_tag()
        error, _tag_type = reader.request()
        if error:
            time.sleep(0.1)
            continue
        error, uid_bytes = reader.anticoll()
        if error:
            time.sleep(0.1)
            continue
        return "-".join(f"{b:02X}" for b in uid_bytes)
    return None


# ── Main flow ─────────────────────────────────────────────────────────────────

def list_tiles(tiles: dict[str, str]) -> None:
    """Pretty-print current registrations."""
    if not tiles:
        print("  (no tiles registered yet)")
        return
    max_uid = max(len(k) for k in tiles)
    for uid, uri in sorted(tiles.items()):
        print(f"  {uid:<{max_uid}}  →  {uri}")


def register_loop() -> None:
    print()
    print("╔══════════════════════════════════════════╗")
    print("║  🏷️   HexPlayer — Tile Registration Tool  ║")
    print("╚══════════════════════════════════════════╝")
    print()

    reader = _build_nfc_reader()
    tiles = load_tiles()

    print(f"\n📋  Currently registered tiles ({len(tiles)}):")
    list_tiles(tiles)
    print()

    while _running:
        print("─" * 50)
        print("Options:")
        print("  [Enter]  Register a new tile")
        print("  l        List registered tiles")
        print("  d        Delete a tile by UID")
        print("  q        Quit")
        print()
        choice = input("Choice: ").strip().lower()

        if choice in ("q", "quit", "exit"):
            print("\n👋  Goodbye!")
            break

        elif choice in ("l", "list"):
            print(f"\n📋  Registered tiles ({len(tiles)}):")
            list_tiles(tiles)
            print()

        elif choice in ("d", "del", "delete"):
            uid = input("  Enter UID to delete: ").strip().upper()
            if uid in tiles:
                removed_uri = tiles.pop(uid)
                save_tiles(tiles)
                print(f"  🗑️   Removed {uid} → {removed_uri}")
            else:
                print(f"  ⚠️  UID '{uid}' not found.")
            print()

        elif choice == "":
            # ── Get Spotify URI ───────────────────────────────────────────────
            print()
            print("Paste a Spotify URI (e.g. spotify:playlist:37i9dQZF1DXcBWIGoYBM5M)")
            print("Tip: right-click in Spotify → Share → Copy Spotify URI")
            uri = input("Spotify URI: ").strip()

            if not uri:
                print("  ⚠️  No URI entered — skipping.")
                print()
                continue

            if not validate_uri(uri):
                print(
                    f"  ❌  '{uri}' doesn't look like a valid Spotify URI.\n"
                    "     Expected format: spotify:<type>:<id>\n"
                    "     Valid types: track, playlist, album, artist\n"
                )
                continue

            # ── Wait for tile tap ─────────────────────────────────────────────
            print()
            print(f"  🕑  Tap the NFC tile now… (waiting up to {TILE_READ_TIMEOUT}s)")
            uid = read_uid_with_timeout(reader)

            if uid is None:
                print("  ⏱️   Timed out — no tile detected. Try again.\n")
                continue

            print(f"  ✅  Tile detected: {uid}")

            # ── Check for existing mapping ────────────────────────────────────
            if uid in tiles:
                old_uri = tiles[uid]
                print(f"  ⚠️  This tile is already mapped to: {old_uri}")
                overwrite = input("  Overwrite? [y/N]: ").strip().lower()
                if overwrite not in ("y", "yes"):
                    print("  ↩️   Skipped.\n")
                    continue

            tiles[uid] = uri
            save_tiles(tiles)
            print(f"  🎵  Registered: {uid} → {uri}\n")

        else:
            print(f"  ⚠️  Unknown option '{choice}'")
            print()


if __name__ == "__main__":
    register_loop()

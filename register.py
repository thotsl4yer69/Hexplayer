#!/usr/bin/env python3
"""Legacy-friendly CLI card registration for HexPlayer v2."""
from __future__ import annotations
import os
import sys
from dotenv import load_dotenv
from hexplayer import TileRegistry, NFC_RESET_PIN, uid_to_string

load_dotenv()
VALID_URI_PREFIXES = ("spotify:track:", "spotify:playlist:", "spotify:album:", "spotify:artist:")


def build_reader():
    try:
        from pirc522 import RFID
        return RFID(pin_rst=NFC_RESET_PIN)
    except Exception as exc:
        print(f"Unable to initialise RC522: {exc}")
        sys.exit(1)


def read_uid(reader):
    reader.wait_for_tag()
    uid = reader.read_id(as_number=False)
    return uid_to_string(uid) if uid else None


def main():
    registry = TileRegistry()
    reader = build_reader()
    print("HexPlayer v2 card registration")
    try:
        while True:
            choice = input("\n[Enter] add Spotify card | l list | d delete | q quit: ").strip().lower()
            if choice in {"q", "quit"}:
                return
            if choice == "l":
                for uid, card in registry.all().items():
                    print(f"{uid} -> {card.get('name') or '(unnamed)'} -> {card['action']}")
                continue
            if choice == "d":
                uid = input("UID: ").strip().upper()
                print("deleted" if registry.delete(uid) else "not found")
                continue
            if choice:
                print("Unknown command")
                continue
            uri = input("Spotify URI: ").strip()
            if not uri.startswith(VALID_URI_PREFIXES):
                print("Invalid Spotify URI")
                continue
            name = input("Card name (optional): ").strip()
            print("Tap card…")
            uid = read_uid(reader)
            if not uid:
                print("No card detected")
                continue
            registry.upsert(uid, {"name": name, "action": {"type": "spotify", "uri": uri}})
            print(f"Registered {uid}")
    finally:
        try:
            reader.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# Project Status — HexPlayer

**Portfolio class:** Flagship  
**Maturity:** **Bench prototype**  
**Primary platform:** Raspberry Pi + NFC reader + Spotify playback  
**Last portfolio review:** 2026-08-13

## What is demonstrated

- physical NFC-to-media interaction concept;
- Raspberry Pi/Linux integration;
- RC522/PN532-style NFC/RFID work and SPI-oriented hardware bring-up;
- Python service/helper development;
- Spotify URI/API/OAuth exploration;
- system-service/deployment thinking for a phone-independent physical music player.

## Evidence boundary

The defensible status is **bench prototype**. Hardware, reader choice, playback endpoint and enclosure/audio configuration should be documented per tested build rather than implied as universally interchangeable.

## Authorship / AI assistance

Authored MAZLABZ project developed with AI-assisted engineering workflows. AI assistance supported implementation and troubleshooting; hardware selection, physical integration, testing and product decisions remain the project owner's responsibility.

## Portfolio takeaway

HexPlayer is a compact example of **turning a physical interaction into a complete software/hardware product loop**.

## Fleet reconciliation — 2 November 2026

The 2 October retrospective records a local tile-placement/removal logic change with **16 mocked tests passed**, but the fix was then isolated, not pushed/merged/deployed. The Pi Zero 2 W HexPlayer was deliberately offline in that snapshot and lacked its speaker path. Do not treat mocked tag logic as verified RFID-to-audio operation. Next: confirm physical board and reader, verify UID, speaker/audio, Spotify auth/target, tag removal and reboot recovery. See [fleet audit](https://github.com/thotsl4yer69/fleet/blob/main/FLEET_STATE_2026-11-02.md).

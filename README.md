# 🎵 HexPlayer

> A compact, headless Spotify player for Raspberry Pi Zero 2 W — tap a 3D-printed hexagonal NFC tile to instantly start any playlist, album, or track. No phone, no screen, no fuss.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![Raspberry Pi OS Bookworm](https://img.shields.io/badge/Pi%20OS-Bookworm-red.svg)](https://www.raspberrypi.com/software/)

---

## Table of Contents

- [How It Works](#how-it-works)
- [Hardware Shopping List](#hardware-shopping-list)
- [Hardware Pinout](#hardware-pinout)
- [Step-by-Step Setup](#step-by-step-setup)
- [Adding New Tiles](#adding-new-tiles)
- [File Reference](#file-reference)
- [3D Print Files](#3d-print-files)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## How It Works

```
┌─────────────┐     SPI      ┌──────────────────┐     Wi-Fi / API     ┌──────────┐
│  NFC Tile   │────────────▶│  hexplayer.py     │───────────────────▶│ Spotify  │
│ (RC522 tag) │             │  (Pi Zero 2 W)    │                     │  Cloud   │
└─────────────┘             └──────────────────┘                     └──────────┘
                                      │
                                      │ I2S / PCM
                                      ▼
                             ┌──────────────────┐
                             │  I2S Amp HAT     │
                             │  → Speaker 🔊    │
                             └──────────────────┘
```

1. **Tap a tile** — the RC522 NFC reader detects the tile UID over SPI.
2. **Lookup** — `hexplayer.py` looks up the UID in `tiles.json`.
3. **Play** — Spotify Web API sends playback to the Raspotify Connect device on the Pi.
4. **Listen** — audio streams through the I2S amp HAT to your speaker.

---

## Hardware Shopping List

| # | Component | Notes |
|---|-----------|-------|
| 1 | **Raspberry Pi Zero 2 W** | Wi-Fi + quad-core Cortex-A53 |
| 2 | **RC522 NFC Reader** breakout | ~$3–5, SPI interface, 13.56 MHz |
| 3 | **NFC stickers** NTAG213 / NTAG215 | 1 per tile; 25 mm round |
| 4 | **I2S Amp HAT** (HiFiBerry DAC+ Zero or MAX98357A) | Plugs onto 40-pin header |
| 5 | **Passive speaker** | 4–8 Ω, 3–5 W |
| 6 | **Micro SD card** ≥ 8 GB | Class 10 / A1 recommended |
| 7 | **5 V / 3 A USB-C power supply** | Pi Zero 2 W needs ≥ 2.5 A |
| 8 | **8× female-to-female jumper wires** | RC522 to Pi header |
| 9 | **3D-printed hex tiles** | See [3D Print Files](#3d-print-files) |

---

## Hardware Pinout

See [`docs/hardware-pinout.md`](docs/hardware-pinout.md) for the full GPIO diagram.

Quick reference — RC522 to Pi Zero 2 W:

| RC522 | Pi GPIO (BCM) | Physical Pin |
|-------|--------------|--------------|
| VCC   | 3.3 V        | Pin 1        |
| GND   | GND          | Pin 6        |
| MOSI  | GPIO 10      | Pin 19       |
| MISO  | GPIO 9       | Pin 21       |
| SCK   | GPIO 11      | Pin 23       |
| SDA   | GPIO 8       | Pin 24       |
| RST   | GPIO 25      | Pin 22       |

> ⚠️ Use **3.3 V** only — never 5 V. The RC522 is not 5 V tolerant.

The I2S HAT plugs directly onto the 40-pin header. GPIO 18, 19, 21 are used for I2S
and do **not** conflict with SPI.

---

## Step-by-Step Setup

### 1 — Flash Raspberry Pi OS Lite (Bookworm)

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Choose **Raspberry Pi OS Lite (64-bit)** — Bookworm.
3. In Imager settings (⚙️ gear icon): set hostname, enable SSH, configure Wi-Fi.
4. Flash to SD card, insert into Pi, power on.

### 2 — Connect hardware

Wire the RC522 to the Pi header as shown in the pinout table above.
Seat the I2S HAT on top of the 40-pin header.

### 3 — SSH into the Pi

```bash
ssh pi@hexplayer.local   # or use the IP address
```

### 4 — Clone this repository

```bash
git clone https://github.com/thotsl4yer69/Hexplayer.git
cd Hexplayer
```

### 5 — Run the one-click setup script

```bash
chmod +x setup.sh
./setup.sh
```

This script:
- Installs system dependencies
- Enables SPI
- Configures the I2S audio overlay
- Installs [Raspotify](https://github.com/dtcooper/raspotify) (Spotify Connect)
- Creates a Python virtualenv and installs pip packages
- Copies `.env.example` → `.env`
- Installs and enables the `hexplayer` systemd service

> ⚠️ A **reboot** is required after setup to activate SPI and the I2S overlay:
> ```bash
> sudo reboot
> ```

### 6 — Add your Spotify credentials

Create a Spotify app at <https://developer.spotify.com/dashboard>:

1. Click **Create App**.
2. Set **Redirect URI** to `http://localhost:8888/callback`.
3. Copy the **Client ID** and **Client Secret**.

Edit `.env`:

```bash
nano .env
```

Fill in:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
DEVICE_NAME=HexPlayer
```

### 7 — Authenticate with Spotify

Run `hexplayer.py` once manually to complete OAuth:

```bash
source venv/bin/activate
python3 hexplayer.py
```

A URL will be printed. Open it in a browser on **any device** on the same network,
log in, and copy the redirected URL back to the terminal. A `.spotify_cache` token
file is saved and used for all future authentication.

### 8 — Register your first tile

```bash
python3 register.py
```

1. Paste a Spotify URI when prompted (e.g. `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M`).
2. Tap the NFC tile.
3. Mapping is saved to `tiles.json` automatically.

**Finding Spotify URIs:** Right-click any playlist, album, or track in the desktop
Spotify app → **Share** → **Copy Spotify URI**.

### 9 — Start the service

```bash
sudo systemctl start hexplayer
sudo systemctl status hexplayer
```

Tap a registered tile — music starts immediately! 🎶

Check logs any time:

```bash
journalctl -u hexplayer -f
```

---

## Adding New Tiles

Run the registration tool at any time:

```bash
cd ~/Hexplayer
source venv/bin/activate
python3 register.py
```

Choose the interactive menu to:
- Register a new tile
- List all tiles
- Delete a tile by UID

`tiles.json` is reloaded automatically by the daemon on every tile tap — no restart needed.

---

## File Reference

```
Hexplayer/
├── README.md                   ← This file
├── .env.example                ← Copy to .env and fill in credentials
├── .gitignore
├── requirements.txt            ← Python dependencies
├── setup.sh                    ← One-click installer
├── hexplayer.py                ← Main player daemon (run as systemd service)
├── register.py                 ← Interactive tile registration tool
├── tiles.json                  ← NFC UID → Spotify URI map (gitignored)
├── systemd/
│   └── hexplayer.service       ← systemd unit file
├── docs/
│   ├── hardware-pinout.md      ← GPIO wiring diagram
│   └── 3d-printing-tiles.md    ← Print settings and tile geometry
└── LICENSE
```

---

## 3D Print Files

Hex tile STL / 3MF files will be linked here once published.

- **Printables:** *(coming soon)*
- **Thingiverse:** *(coming soon)*

See [`docs/3d-printing-tiles.md`](docs/3d-printing-tiles.md) for print settings,
NFC sticker placement, and labelling tips.

---

## Troubleshooting

### No audio / I2S HAT not detected

```bash
aplay -l          # list audio devices
arecord -l        # should show your DAC
cat /proc/asound/cards
```

- Ensure the dtoverlay line in `/boot/firmware/config.txt` matches your HAT:
  - HiFiBerry DAC+ Zero: `dtoverlay=hifiberry-dac`
  - MAX98357A (Adafruit): `dtoverlay=hifiberry-dac` (same overlay)
- Disable onboard audio: `dtparam=audio=off`

### SPI / RC522 not working

```bash
ls /dev/spidev*           # should show /dev/spidev0.0
sudo dmesg | grep spi     # check for SPI messages
```

- Run `sudo raspi-config` → **Interface Options** → **SPI** → Enable.
- Re-seat jumper wires; check for loose connections on the RC522.
- Confirm VCC is 3.3 V, not 5 V.

### Spotify device not found

```bash
journalctl -u raspotify -f    # check Raspotify logs
systemctl status raspotify
```

- Ensure Raspotify is running: `sudo systemctl start raspotify`
- Check `DEVICE_NAME` in `.env` matches the Raspotify device name.
- Open Spotify on any device — the Pi should appear under **Devices**.

### Auth / token errors

```bash
rm .spotify_cache   # delete cached token and re-authenticate
python3 hexplayer.py
```

### Tile reads inconsistently

- Ensure the NFC sticker is within 5 mm of the RC522 antenna surface.
- Check `DEBOUNCE_SECONDS` in `.env` — lower it if tiles feel sluggish.
- Try a different NFC sticker type (NTAG215 has better range than NTAG213).

### Service won't start

```bash
journalctl -u hexplayer -n 50   # last 50 log lines
sudo systemctl status hexplayer
```

Common causes:
- `.env` missing or credentials incorrect.
- `venv/` not created (re-run `./setup.sh`).
- SPI or I2S overlay not loaded (reboot after editing `/boot/firmware/config.txt`).

---

## License

[MIT](LICENSE) — see the LICENSE file for details.

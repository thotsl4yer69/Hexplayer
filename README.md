# HexPlayer

**A physical music interface: tap an NFC tile, start the mapped Spotify item.**

[![Status](https://img.shields.io/badge/status-bench%20prototype-blue)](PROJECT_STATUS.md)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%20Zero%202%20W-red)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

> **Maturity: Bench prototype.** The core idea is intentionally simple: physical tiles become a tangible library for digital music. Exact reader, audio and playback configuration should be validated against the hardware revision in use. See [PROJECT_STATUS.md](PROJECT_STATUS.md).

## Product idea

HexPlayer is a compact, headless Raspberry Pi music player built around a physical interaction instead of a touchscreen. A registered NFC/contactless tag is read, mapped to a Spotify URI, and handed to the configured playback device.

The intended experience is closer to choosing a record than opening an app:

```text
       physical tile
            │
            ▼
      RC522 reader
        over SPI
            │
            ▼
     Raspberry Pi Zero 2 W
       hexplayer.py
          │      │
          │      └──── local mapping (tiles.json)
          │
          ▼
    Spotify playback target
          │
          ▼
       audio output
```

The system is designed to run without using a phone as the day-to-day control surface. A browser/other device may still be needed for initial Spotify authentication and account setup.

## Demonstrated engineering work

- Raspberry Pi/Linux deployment;
- SPI hardware integration;
- RC522 / ISO 14443A contactless-tag reading;
- UID-to-media mapping;
- Python daemon/service work;
- Spotify URI/API/OAuth integration;
- systemd deployment;
- I2S/audio-device integration;
- physical tile / 3D-print product concept.

## Hardware reference build

| Component | Reference |
|---|---|
| Compute | Raspberry Pi Zero 2 W |
| Reader | MFRC522 / RC522 breakout, 3.3 V logic |
| Tags | Compatible 13.56 MHz ISO 14443A / NTAG-family tags |
| Audio | Compatible I2S DAC/amp or other configured Pi audio path |
| Speaker | Matched to the selected amplifier |
| Storage | microSD card |
| Power | **5 V supply through the Pi Zero 2 W micro-USB power input** |
| Enclosure/media | 3D-printed hexagonal tiles + embedded/attached tags |

> **Electrical warning:** power the RC522 from **3.3 V**, not 5 V. Verify the pinout of the exact breakout board before wiring it.

## RC522 reference wiring

See [`docs/hardware-pinout.md`](docs/hardware-pinout.md) for the hardware guide.

| RC522 | Raspberry Pi signal | BCM GPIO | Physical pin |
|---|---|---:|---:|
| VCC | 3.3 V | — | 1 |
| GND | Ground | — | 6 |
| MOSI | SPI0 MOSI | 10 | 19 |
| MISO | SPI0 MISO | 9 | 21 |
| SCK | SPI0 SCLK | 11 | 23 |
| SDA / SS | SPI0 CE0 | 8 | 24 |
| RST | Reset GPIO | 25 | 22 |

The RC522 SPI signals above do not use the normal PCM/I2S GPIOs. However, **audio HAT pin usage varies by board**, so verify the chosen HAT's complete GPIO requirements before stacking or wiring both devices.

## Software flow

1. The reader detects a registered tag.
2. `hexplayer.py` resolves its UID in `tiles.json`.
3. The mapped Spotify URI is submitted to the configured playback path.
4. Audio plays through the Pi's configured output device.
5. The mapping file can be updated using `register.py` without rebuilding the application.

## Installation

### 1. Prepare Raspberry Pi OS

Use a supported Raspberry Pi OS release for the Pi Zero 2 W, configure networking and SSH if you want headless administration, then boot the Pi.

### 2. Wire and verify the reader

Connect the RC522 using the reference table above and enable SPI.

```bash
ls /dev/spidev*
```

A normal SPI0 configuration should expose the relevant `/dev/spidev0.*` device(s).

### 3. Clone the project

```bash
git clone https://github.com/thotsl4yer69/Hexplayer.git
cd Hexplayer
```

### 4. Review the setup script before running it

```bash
less setup.sh
chmod +x setup.sh
./setup.sh
```

The setup path installs required software, configures the project environment and installs the systemd service. Audio overlays and third-party playback packages can change over time, so verify the script against the current Raspberry Pi OS release rather than treating it as an immutable appliance image.

Reboot if the setup changed SPI, audio overlays or boot configuration.

### 5. Configure credentials

Copy/configure the example environment file without committing secrets:

```bash
cp .env.example .env
nano .env
```

The project expects the Spotify/application values documented in `.env.example` and the configured playback-device name.

### 6. Complete authentication

Run the application interactively once when needed to establish the OAuth/token state required by the configured Spotify path:

```bash
source venv/bin/activate
python3 hexplayer.py
```

Do not commit cached OAuth tokens or real client secrets.

### 7. Register a tile

```bash
python3 register.py
```

Associate the detected tag UID with the intended Spotify URI. The mapping is stored locally in `tiles.json`.

### 8. Run as a service

```bash
sudo systemctl start hexplayer
sudo systemctl status hexplayer
journalctl -u hexplayer -f
```

## Repository layout

```text
Hexplayer/
├── README.md
├── PROJECT_STATUS.md
├── .env.example
├── requirements.txt
├── setup.sh
├── hexplayer.py
├── register.py
├── systemd/
│   └── hexplayer.service
├── docs/
│   ├── hardware-pinout.md
│   └── 3d-printing-tiles.md
└── LICENSE
```

Runtime secrets, OAuth cache data and personal tile mappings should remain outside version control.

## 3D-printed tiles

The repository documents the tile concept and print guidance under [`docs/3d-printing-tiles.md`](docs/3d-printing-tiles.md). Publishing final STL/3MF assets is still part of the productisation work; the README no longer points to placeholder external listings as if they already exist.

## Troubleshooting

### Reader not responding

```bash
ls /dev/spidev*
sudo dmesg | grep -i spi
```

Check:

- SPI is enabled;
- VCC is 3.3 V;
- CE/SS and reset pins match the software configuration;
- jumper connections are secure;
- the tag is compatible with the reader.

### No playback audio

```bash
aplay -l
cat /proc/asound/cards
```

Confirm the selected playback device appears and that the boot overlay/configuration matches the **exact** DAC/amp board in use. Do not assume one vendor's overlay applies to every I2S amplifier.

### Playback target unavailable

Check the playback service and its logs, for example:

```bash
systemctl status raspotify
journalctl -u raspotify -n 100
```

Then verify that the device name configured for HexPlayer matches the actual playback target.

### Authentication errors

If a cached token is invalid, remove/recreate it only after confirming the path and that it contains no data you need to preserve. Re-run the interactive authentication flow afterward.

### Inconsistent tag reads

- test the tag directly over the reader antenna;
- remove metal or conductive material near the tag/antenna;
- verify supply voltage and wiring;
- test another known-compatible tag;
- tune debounce behaviour only after confirming the hardware path is stable.

## Evidence boundary

HexPlayer is currently a **bench prototype**, not a finished consumer appliance. Playback-account requirements, third-party APIs, Raspotify behaviour and Raspberry Pi OS packaging can change independently of this repository.

Hardware claims should be tied to a tested build, and future enclosure/audio variants should each document their own wiring and power assumptions.

## Development provenance

HexPlayer is an authored MAZLABZ project developed with AI-assisted engineering workflows. AI has supported implementation and troubleshooting; product definition, hardware selection, physical integration and verification remain the project owner's responsibility.

## Portfolio significance

HexPlayer is deliberately small compared with the edge-AI systems. That is useful: it demonstrates the complete loop from **physical interaction → electronics → Linux service → API → media output** in a product idea that is immediately understandable.

## MAZLABZ illustrated goods

For fellow electronics makers: **[Solder Club — Raccoon Electronics Workshop](https://www.redbubble.com/i/hoodie/Solder-Club-Raccoon-Electronics-Workshop-by-ThotSl4yer69/184817513/2j5j)** is a separate MAZLABZ artwork available on Redbubble. Optional art link, not hardware or part of HexPlayer.

## License

[MIT](LICENSE)

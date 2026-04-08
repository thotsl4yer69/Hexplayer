# HexPlayer — Hardware Pinout

## RC522 NFC Reader → Raspberry Pi Zero 2 W

The RC522 communicates over SPI. Use the following connections:

```
RC522 Pin   │ Pi GPIO (BCM)  │ Pi Physical Pin  │ Notes
────────────┼────────────────┼──────────────────┼────────────────────────
VCC (3.3V)  │ 3.3V           │ Pin 1 or 17      │ Do NOT use 5V
GND         │ GND            │ Pin 6, 9, 14…    │ Any ground pin
MOSI        │ GPIO 10        │ Pin 19           │ SPI0 MOSI
MISO        │ GPIO 9         │ Pin 21           │ SPI0 MISO
SCK         │ GPIO 11        │ Pin 23           │ SPI0 SCLK
SDA (SS/CE) │ GPIO 8         │ Pin 24           │ SPI0 CE0
RST         │ GPIO 25        │ Pin 22           │ Configurable via NFC_RESET_PIN in .env
IRQ         │ (not used)     │ —                │ Leave unconnected
```

> **Important:** The RC522 runs on **3.3 V logic**. Never connect VCC to 5 V.

### Visual diagram (GPIO header, top view)

```
                  3V3  [ 1][ 2]  5V
     I2C SDA  GPIO  2  [ 3][ 4]  5V
     I2C SCL  GPIO  3  [ 5][ 6]  GND  ◄── RC522 GND
              GPIO  4  [ 7][ 8]  GPIO 14  UART TX
                   GND  [ 9][10]  GPIO 15  UART RX
              GPIO 17  [11][12]  GPIO 18
              GPIO 27  [13][14]  GND
              GPIO 22  [15][16]  GPIO 23
          3V3 power  [17][18]  GPIO 24
SPI MOSI  GPIO 10  [19][20]  GND
SPI MISO  GPIO  9  [21][22]  GPIO 25  ◄── RC522 RST
SPI CLK   GPIO 11  [23][24]  GPIO  8  ◄── RC522 SDA/SS
                   GND [25][26]  GPIO  7
     I2C  GPIO  0  [27][28]  GPIO  1
              GPIO  5  [29][30]  GND
              GPIO  6  [31][32]  GPIO 12
              GPIO 13  [33][34]  GND
SPI1 MISO GPIO 19  [35][36]  GPIO 16
              GPIO 26  [37][38]  GPIO 20  SPI1 MOSI
                   GND [39][40]  GPIO 21  SPI1 CLK
```

Pins used by RC522: **1** (3V3), **6** (GND), **19** (MOSI), **21** (MISO), **22** (RST), **23** (SCK), **24** (SS/CE0).

---

## I2S Amp HAT (HiFiBerry DAC+ / MAX98357)

I2S audio uses a dedicated set of GPIO pins and is handled entirely by the
`dtoverlay` in `/boot/firmware/config.txt`. No additional wiring is required
beyond plugging the HAT onto the 40-pin header.

| Signal     | GPIO (BCM) | Physical Pin |
|------------|-----------|--------------|
| I2S BCLK   | GPIO 18   | Pin 12       |
| I2S LRCLK  | GPIO 19   | Pin 35       |
| I2S DATA   | GPIO 21   | Pin 40       |

> **HAT conflict note:** The RC522 uses SPI0 (GPIO 8–11). HiFiBerry/I2S uses
> GPIO 18–21. These do **not** overlap, so both can coexist on the same Pi.

---

## Enabling SPI

```bash
sudo raspi-config
# → Interface Options → SPI → Enable
# or add manually:
echo "dtparam=spi=on" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Verify SPI is active after reboot:

```bash
ls /dev/spidev*
# Should show: /dev/spidev0.0  /dev/spidev0.1
```

---

## Shopping List

| Component | Recommended model | Notes |
|-----------|-------------------|-------|
| Pi        | Raspberry Pi Zero 2 W | Wi-Fi + quad-core |
| NFC reader | RC522 breakout board | ~$3–5, widely available |
| NFC stickers | NTAG213 / NTAG215 | 13.56 MHz, ISO/IEC 14443A |
| I2S Amp HAT | HiFiBerry DAC+ Zero | Direct 40-pin HAT |
| Speaker    | Any 4–8 Ω, 3–5 W passive | Wired to HAT output |
| Power      | 5 V / 3 A USB-C supply | Pi Zero 2 W needs ~2.5 A |
| Case       | 3D-printed hex tiles | See `docs/3d-printing-tiles.md` |

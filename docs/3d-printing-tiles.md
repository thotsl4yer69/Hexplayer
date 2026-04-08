# HexPlayer — 3D Printing the Hex Tiles

## Overview

Each HexPlayer tile is a small hexagonal enclosure that holds a single **NFC sticker
(NTAG213 or NTAG215)**. The tile is purely a physical carrier — the NFC sticker stores
no data; the UID on the chip is what HexPlayer reads and maps to a Spotify URI.

---

## Recommended Print Settings

| Parameter       | Value           |
|----------------|-----------------|
| Layer height    | 0.2 mm          |
| Infill          | 20 % (gyroid)   |
| Walls           | 3 perimeters    |
| Material        | PLA or PETG     |
| Support         | Not required    |
| Bed temp        | 60 °C (PLA)     |
| Nozzle temp     | 215 °C (PLA)    |

---

## Tile Geometry

A suggested tile is a **regular hexagon** with:
- **Outer flat-to-flat diameter:** 40 mm
- **Total height:** 8 mm (5 mm base + 3 mm top shell)
- **NFC pocket:** 28 mm diameter, 1 mm deep (fits standard 25 mm NFC sticker)

The pocket is on the **underside** of the tile, keeping the top surface smooth for
label printing or painting.

---

## Files

3D print files (`.stl` and `.3mf`) are hosted separately to keep the git repository
lightweight. Download them from:

- **Printables:** *(link coming soon — search "HexPlayer NFC tile")*
- **Thingiverse:** *(link coming soon)*
- **Files folder:** `3d-models/` in this repo once added

If you want to design your own, the key constraint is that the NFC sticker sits within
**5 mm of the top surface** of the tile so it is within reliable read range of the
RC522 antenna.

---

## Labelling Tiles

Options for labelling each tile:

1. **Print and stick:** Print a small hexagonal label on paper or vinyl, cut it out,
   and stick it to the top. Laminate for durability.
2. **Paint:** Paint the tile a solid colour, let it dry, then use a paint pen for text.
3. **Engraving:** If your slicer supports it, emboss the playlist name into the top
   surface at print time.

---

## NFC Sticker Placement

1. Print the tile with the pocket side up on your printer bed.
2. Peel the NFC sticker backing and press it firmly into the pocket.
3. The sticker should sit flush or 0.5 mm below the pocket rim.
4. Optionally apply a small drop of super glue around the rim to secure it.

> **NFC range tip:** The RC522 reads reliably at 0–30 mm range.
> Keep tiles thin (under 5 mm above the sticker) for best response.

---

## Troubleshooting Read Range

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Tile only reads when pressed hard | Sticker too deep in tile | Move sticker closer to surface |
| Intermittent reads | Sticker is tilted | Re-seat sticker flat |
| No reads at all | Wrong NFC type | Use NTAG213/215 (13.56 MHz ISO 14443A) |
| NFC reader errors in logs | SPI not enabled | Run `sudo raspi-config` → Interface Options → SPI |

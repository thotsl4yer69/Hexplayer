# Android controller

The controller configures card mappings on the HexPlayer daemon. A phone can
read a tag's hardware UID and program supported writable NDEF tags with a
`hexplayer://card/<UID>` URI. This is not RFID cloning: it does not change a
chip's hardware UID, bypass tag locks, or support arbitrary chip protocols.
This build writes already NDEF-formatted tags only. It reports unformatted tags
as unsupported rather than formatting them without a verified rediscovery flow.
The physical UID controls lookup; a conflicting or malformed HexPlayer URI on
the tag is a warning and cannot select another card's action.
The Pi reader resolves mappings by hardware UID; it does not need the URI to
play a mapped card. A manual UID mapping remains useful for tags readable by
the Pi but not writable by the phone.

## Safe setup

Enter the HexPlayer server address and its API key in Settings. Enter Home
Assistant's address and a token created by the account owner only through the
supported settings flow. Credentials are encrypted using Android Keystore and
are not built into the APK. Never paste personal tokens into source code,
committed configuration, issue reports, or build scripts.

Use HTTPS with a certificate trusted by Android for authenticated connections.
For a daemon on a private network, terminate TLS at an authenticated reverse
proxy and keep the daemon's API port private. Do not expose the daemon directly
to the internet. An unreachable server, missing credentials, or an unavailable
playback endpoint must be resolved separately from installing the app.

The server requires `HEXPLAYER_API_KEY` in its private `.env`; an empty value
disables the listener. Generate a fresh random API key during your own setup
(for example, `python -c "import secrets; print(secrets.token_urlsafe(32))"`),
store it privately, and enter the same value in the phone's Settings. Configure
`HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` manually on the server if you
prefer not to provision HA from the phone. See [proxy and reader details](tile-presence.md).

## Card workflow

1. Configure the server, then reload its saved card mappings.
2. Scan a supported tag or enter the UID manually.
3. Give the card a name and select Spotify playback, Home Assistant media,
   a Home Assistant service (including an automation/script), or an HA event.
4. Enter the target and action parameters, then save the mapping to the server.
5. Reload to confirm the mapping persisted. Writing the optional NDEF URI is a
   separate operation: hold the selected tag until read-back verification
completes. A saved mapping does not mean the chip was programmed.

If writing loses contact after sending bytes, the app reports an unverified
write and requires a fresh scan. If a save response is lost, reload mappings
before retrying. Playback and HA requests are never automatically retried by
the phone; an error can follow an action that already executed.

An HA automation can use domain `automation`, service `trigger`, and an entity
such as `automation.example`. A script can use domain `script`, service
`turn_on`, and `script.example`. Service data must be a JSON object. These
examples are configuration only; running them can affect real devices.

## Verification boundaries

Development checks must mock Spotify, Home Assistant, reader hardware, and
consequential device actions. Local software tests cannot establish NFC antenna
compatibility, actual tag write endurance, phone installation, speaker output,
or a home's automation behavior. Those require separate user-supervised tests.

Debug APKs use Android's test certificate and are not production releases.
Production signing and distribution require a separately approved signing and
release process. Never commit a keystore or generate a persistent release key
as part of a routine debug build.

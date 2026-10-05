# Tile presence and controller security

The Oct 2 patch `2a198459` was reviewed and adapted to the v2 action registry,
not applied over unrelated work. A held tag fires once. Continuous absence for
DEBOUNCE_SECONDS confirms removal. Spotify starts and pauses retry after failure;
removal pauses the explicitly selected Spotify target. Reader errors interrupt
absence confirmation. HA events, services and media actions never automatically
retry while held, because a timeout may follow a successful consequential action.
Remove and replace deliberately to retry. Removing HA action tags does not undo
an automation or stop HA media. Unknown tags do not start actions.

The Pi RC522 reader polls without wait_for_tag. Four-byte and seven-byte UIDs use
the official pi-rc522 anticoll/select_tag/anticoll2 sequence, retaining checksum
validation and distinguishing read failures from absence. Ten-byte cascade UIDs
are explicitly unsupported by this adapter. Installed older drivers lacking
anticoll2 report an unsupported-driver error. Android NDEF writing support does
not establish physical compatibility with the installed reader and tags. Driver
request errors can resemble absence, so physical reader acceptance is required.
Reference: https://github.com/ondryaso/pi-rc522/blob/master/pirc522/rfid.py
All controller routes except health require a user-managed API key. For remote
access use an HTTPS reverse proxy and bind HEXPLAYER_API_HOST=127.0.0.1. Set
HEXPLAYER_TRUST_PROXY_TLS=true only when that proxy is configured and local access
is trusted; this enables app HA token provisioning from the loopback proxy.
The proxy must terminate TLS, forward the Authorization header, and must not
expose an HTTP listener that forwards secret provisioning. Keep direct daemon
port inaccessible remotely. Never set this flag on an exposed HTTP deployment.
Without that setup enter HA URL/token in the server .env manually. App provisioned
HA targets require HTTPS (loopback allowed); manual trusted LAN HTTP remains a
server operator choice. Existing environment credentials take precedence and
app provisioning reports a validation error rather than pretending to replace them.
Runtime credentials are atomically written with mode 0600 on POSIX; never commit
runtime files. Windows file ACL protection must be set by the operator if running
this daemon on Windows. Production target is Linux/Pi.

Run offline checks: `python -m unittest discover -s tests -v` and
`python -m py_compile hexplayer.py`. Tests use local ephemeral HTTP listeners and
mock every Spotify/Home Assistant call. Hardware NFC, phone installation, TLS
proxy deployment and audio acceptance remain separate tasks.

The dependency floor is pi-rc522>=2.2.1 (requirements.txt); the adapter uses the
official current cascade APIs and reports missing older-driver support. NFC_RESET_PIN
is BCM numbering (default 25, physical 22), matching the README; IRQ is disabled
because this adapter polls and no IRQ wire is documented. Physical driver/version
acceptance remains required on the player.

Legacy 4-byte-plus-BCC registry keys are listed and saved as canonical 4-byte
UIDs when the BCC is valid. Identical duplicate aliases collapse; conflicting
canonical/legacy entries fail visibly without changing the file, requiring manual
reconciliation of tiles.json. Deleting a migrated mapping cannot reactivate an
old hidden alias. Saved card targets take precedence over dashboard selection;
direct HA service control gives its explicit entity_id precedence over data.


Registry loading fails closed on malformed JSON, unreadable files or invalid
entries. API requests report a registry conflict and require manual file repair;
saving cannot silently overwrite a malformed external edit or discard invalid
rows. Existing bytes remain untouched when validation fails.

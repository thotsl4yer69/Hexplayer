#!/usr/bin/env python3
"""HexPlayer daemon: NFC -> Spotify / Home Assistant, with local control API."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
import signal
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hexplayer")

ROOT = Path(__file__).resolve().parent
TILES_FILE = ROOT / "tiles.json"
SECRETS_FILE = ROOT / ".runtime_secrets.json"
DEBOUNCE_SECONDS = float(os.getenv("DEBOUNCE_SECONDS", "3"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.2"))
DEVICE_NAME = os.getenv("DEVICE_NAME", "HexPlayer")
NFC_RESET_PIN = int(os.getenv("NFC_RESET_PIN", "25"))
API_HOST = os.getenv("HEXPLAYER_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("HEXPLAYER_API_PORT", "8787"))
API_KEY = os.getenv("HEXPLAYER_API_KEY", "").strip()

_running = True


def _handle_signal(signum: int, _frame) -> None:
    global _running
    log.info("Received %s — shutting down", signal.Signals(signum).name)
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def uid_to_string(uid: list[int] | bytes | bytearray) -> str:
    """Canonical UID format shared with the Android app."""
    return "-".join(f"{int(b) & 0xFF:02X}" for b in uid)


def legacy_uid_alias(uid: str) -> Optional[str]:
    """Return old 4-byte+BCC spelling used by previous HexPlayer builds."""
    try:
        values = [int(part, 16) for part in uid.split("-")]
    except ValueError:
        return None
    if len(values) != 4:
        return None
    bcc = values[0] ^ values[1] ^ values[2] ^ values[3]
    return uid_to_string(values + [bcc])


def _atomic_json_write(path: Path, payload: dict[str, Any], mode: int | None = None) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    tmp = Path(name)
    try:
        if mode is not None:
            os.chmod(tmp, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class UnavailableError(RuntimeError):
    """A required integration has not been configured."""


class RegistryConflictError(RuntimeError):
    """Legacy and canonical entries disagree; preserve the file for repair."""


def _text(value: Any, field: str, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 4096 or (required and not value.strip()):
        raise ValueError(f"{field} must be {'a nonempty' if required else 'a'} string")
    return value.strip()


def _identifier(value: Any, field: str, entity: bool = False) -> str:
    value = _text(value, field)
    pattern = r"[a-z0-9_]+\.[a-z0-9_]+" if entity else r"[a-zA-Z0-9_]+"
    if not re.fullmatch(pattern, value):
        raise ValueError(f"invalid {field}")
    return value


def normalise_uid(uid: str) -> str:
    uid = uid.strip().upper()
    if not re.fullmatch(r"[0-9A-F]{2}(?:-[0-9A-F]{2}){3,9}", uid):
        raise ValueError("UID must be 4 to 10 hex bytes separated by '-' characters")
    parts = uid.split("-")
    if len(parts) == 5 and legacy_uid_alias("-".join(parts[:4])) == uid:
        return "-".join(parts[:4])
    return uid


def _normalise_action(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"type": "spotify", "uri": value}
    if not isinstance(value, dict):
        raise ValueError("action must be an object")
    action = dict(value)
    kind = str(action.get("type", "")).strip().lower()
    allowed = {"spotify", "ha_media", "ha_service", "ha_event"}
    if kind not in allowed:
        raise ValueError(f"unsupported action type: {kind or '(empty)'}")
    action["type"] = kind
    if "data" in action and not isinstance(action["data"], dict):
        raise ValueError("data must be a JSON object")
    json.dumps(action, allow_nan=False)
    if kind == "spotify":
        if not re.fullmatch(r"spotify:(track|album|playlist|artist):[A-Za-z0-9]+", _text(action.get("uri"), "uri")):
            raise ValueError("spotify action requires a track, album, playlist or artist Spotify URI")
        if "device_id" in action:
            action["device_id"] = _text(action["device_id"], "device_id", False)
    if kind == "ha_media":
        action["entity_id"] = _identifier(action.get("entity_id"), "entity_id", True)
        if not str(action.get("entity_id", "")).startswith("media_player."):
            raise ValueError("ha_media requires a media_player entity_id")
        if not str(action.get("media_content_id", "")).strip():
            raise ValueError("ha_media requires media_content_id")
        action["media_content_id"] = _text(action["media_content_id"], "media_content_id")
        action["media_content_type"] = _text(action.get("media_content_type", "music"), "media_content_type")
        if set(action.get("data", {})) & {"entity_id", "media_content_id", "media_content_type"}:
            raise ValueError("data cannot override media target or content")
    if kind == "ha_service":
        action["domain"] = _identifier(action.get("domain"), "domain")
        action["service"] = _identifier(action.get("service"), "service")
        if action.get("entity_id"):
            action["entity_id"] = _identifier(action["entity_id"], "entity_id", True)
        if not str(action.get("domain", "")).strip() or not str(action.get("service", "")).strip():
            raise ValueError("ha_service requires domain and service")
    if kind == "ha_event" and not str(action.get("event_type", "")).strip():
        raise ValueError("ha_event requires event_type")
    if kind == "ha_event":
        action["event_type"] = _identifier(action.get("event_type"), "event_type")
    return action


def normalise_card(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"name": "", "action": _normalise_action(value)}
    if not isinstance(value, dict):
        raise ValueError("card must be an object")
    card = dict(value)
    card["name"] = _text(card.get("name", ""), "name", False)
    card["action"] = _normalise_action(card.get("action"))
    return card


class TileRegistry:
    """Thread-safe, backwards-compatible v1/v2 tile registry."""

    def __init__(self, path: Path = TILES_FILE) -> None:
        self.path = path
        self._mtime = -1.0
        self._tiles: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load(force=True)

    def _load(self, force: bool = False) -> None:
        with self._lock:
            if not self.path.exists():
                self._tiles = {}
                self._mtime = 0.0
                return
            mtime = self.path.stat().st_mtime_ns
            if not force and mtime == self._mtime:
                return
            try:
                with self.path.open(encoding="utf-8") as fh:
                    raw = json.load(fh)
                source = raw.get("tiles", {}) if isinstance(raw, dict) and raw.get("version") == 2 else raw
                if not isinstance(source, dict):
                    raise ValueError("tiles.json must contain an object")
                tiles: dict[str, dict[str, Any]] = {}
                for uid, value in source.items():
                    try:
                        key = normalise_uid(str(uid))
                        card = normalise_card(value)
                        if key in tiles and tiles[key] != card:
                            raise RegistryConflictError("Conflicting legacy and canonical card entries; reconcile tiles.json manually")
                        tiles[key] = card
                    except ValueError as exc:
                        raise RegistryConflictError("Invalid card registry entry; reconcile tiles.json manually") from exc
                self._tiles = tiles
                self._mtime = mtime
                log.info("Loaded %d tile(s)", len(self._tiles))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise RegistryConflictError("Cannot read valid card registry; reconcile tiles.json manually") from exc

    def _save(self) -> None:
        payload = {"version": 2, "tiles": self._tiles}
        _atomic_json_write(self.path, payload)
        self._mtime = self.path.stat().st_mtime_ns

    def get(self, uid: str) -> Optional[dict[str, Any]]:
        self._load()
        key = normalise_uid(uid)
        with self._lock:
            card = self._tiles.get(key)
            if card is None:
                alias = legacy_uid_alias(key)
                if alias:
                    card = self._tiles.get(alias)
            return json.loads(json.dumps(card)) if card is not None else None

    def all(self) -> dict[str, dict[str, Any]]:
        self._load()
        with self._lock:
            return json.loads(json.dumps(self._tiles))

    def upsert(self, uid: str, value: Any) -> dict[str, Any]:
        uid = normalise_uid(uid)
        card = normalise_card(value)
        with self._lock:
            self._load()
            previous = dict(self._tiles)
            self._tiles[uid] = card
            try:
                self._save()
            except OSError:
                self._tiles = previous
                raise
        return card

    def delete(self, uid: str) -> bool:
        uid = normalise_uid(uid)
        with self._lock:
            self._load()
            if uid not in self._tiles:
                return False
            previous = dict(self._tiles)
            del self._tiles[uid]
            try:
                self._save()
            except OSError:
                self._tiles = previous
                raise
            return True


class HomeAssistantClient:
    def __init__(self, secrets_path: Path = SECRETS_FILE) -> None:
        self.secrets_path = secrets_path
        self._lock = threading.RLock()

    def _credentials(self) -> tuple[str, str]:
        url = os.getenv("HOME_ASSISTANT_URL", "").strip().rstrip("/")
        token = os.getenv("HOME_ASSISTANT_TOKEN", "").strip()
        if url and token:
            return url, token
        if self.secrets_path.exists():
            try:
                with self.secrets_path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                return str(data.get("url", "")).strip().rstrip("/"), str(data.get("token", "")).strip()
            except (OSError, json.JSONDecodeError):
                pass
        return "", ""

    def configure(self, url: str, token: str) -> None:
        url = _text(url, "url").rstrip("/")
        token = _text(token, "token")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Home Assistant URL must be an http(s) URL without credentials, query or fragment")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Remote Home Assistant token provisioning requires HTTPS; use manual server .env setup for trusted LAN HTTP")
        if os.getenv("HOME_ASSISTANT_URL") or os.getenv("HOME_ASSISTANT_TOKEN"):
            raise ValueError("Home Assistant is managed by server environment; update its manual configuration")
        with self._lock:
            _atomic_json_write(self.secrets_path, {"url": url, "token": token}, mode=0o600)

    def _request(self, method: str, path: str, payload: Any = None) -> Any:
        url, token = self._credentials()
        if not url or not token:
            raise UnavailableError("Home Assistant is not configured")
        response = requests.request(
            method,
            f"{url}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=8,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise RuntimeError("Home Assistant redirect refused; configure its final URL")
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def status(self) -> dict[str, Any]:
        try:
            self._request("GET", "/api/")
            return {"configured": True, "reachable": True}
        except Exception:
            url, token = self._credentials()
            return {"configured": bool(url and token), "reachable": False, "error": "Home Assistant unavailable"}

    def media_players(self) -> list[dict[str, Any]]:
        states = self._request("GET", "/api/states")
        result = []
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if entity_id.startswith("media_player."):
                attrs = state.get("attributes") or {}
                result.append({
                    "entity_id": entity_id,
                    "state": state.get("state"),
                    "name": attrs.get("friendly_name", entity_id),
                    "volume_level": attrs.get("volume_level"),
                    "media_title": attrs.get("media_title"),
                })
        return result

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        return self._request("POST", f"/api/services/{domain}/{service}", data)

    def fire_event(self, event_type: str, data: dict[str, Any]) -> Any:
        return self._request("POST", f"/api/events/{event_type}", data)


class ActionDispatcher:
    def __init__(self, spotify, ha: HomeAssistantClient) -> None:
        self.spotify = spotify
        self.ha = ha

    def dispatch(self, card: dict[str, Any]) -> bool:
        action = card["action"]
        kind = action["type"]
        if kind == "spotify":
            if self.spotify is None:
                raise UnavailableError("Spotify is not configured")
            device_id = str(action.get("device_id", "")).strip() or get_device_id(self.spotify)
            if not device_id:
                raise UnavailableError("No configured Spotify playback target is available")
            return start_playback(self.spotify, str(action["uri"]), device_id)
        if kind == "ha_media":
            data = {
                "entity_id": action["entity_id"],
                "media_content_id": action["media_content_id"],
                "media_content_type": action.get("media_content_type", "music"),
            }
            extra = action.get("data")
            if isinstance(extra, dict):
                data.update(extra)
            self.ha.call_service("media_player", "play_media", data)
            return True
        if kind == "ha_service":
            data = dict(action.get("data") or {})
            entity_id = str(action.get("entity_id", "")).strip()
            if entity_id:
                data["entity_id"] = entity_id
            self.ha.call_service(str(action["domain"]), str(action["service"]), data)
            return True
        if kind == "ha_event":
            self.ha.fire_event(str(action["event_type"]), dict(action.get("data") or {}))
            return True
        return False


def _build_spotify_client():
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.warning("Spotify is not configured; Home Assistant and card configuration remain available")
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        log.critical("spotipy is not installed — run pip install -r requirements.txt")
        sys.exit(1)
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
    scope = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        open_browser=False,
        cache_path=str(ROOT / ".spotify_cache"),
    )
    return spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10, retries=3)


def get_device_id(sp=None) -> Optional[str]:
    explicit_id = os.getenv("DEVICE_ID", "").strip()
    if explicit_id:
        return explicit_id
    if sp is None:
        return None
    try:
        devices = sp.devices().get("devices", [])
    except Exception:
        log.warning("Could not list Spotify devices; check integration connectivity")
        return None
    for device in devices:
        if str(device.get("name", "")).lower() == DEVICE_NAME.lower():
            return str(device["id"])
    return None


def start_playback(sp, uri: str, device_id: Optional[str]) -> bool:
    kwargs: dict[str, Any] = {"device_id": device_id}
    if uri.startswith("spotify:track:"):
        kwargs["uris"] = [uri]
    else:
        kwargs["context_uri"] = uri
    try:
        sp.start_playback(**kwargs)
        log.info("Playing %s", uri)
        return True
    except Exception:
        log.error("Spotify playback failed; check integration connectivity")
        return False


def _build_nfc_reader():
    try:
        from pirc522 import RFID
        import RPi.GPIO as GPIO
    except ImportError:
        log.critical("pirc522 is not installed")
        sys.exit(1)
    try:
        return RFID(pin_rst=NFC_RESET_PIN, pin_mode=GPIO.BCM, pin_irq=None,
                    bus=int(os.getenv("NFC_SPI_BUS", "0")),
                    device=int(os.getenv("NFC_SPI_DEVICE", "0")))
    except Exception as exc:
        log.critical("Failed to initialise NFC reader: %s", exc)
        sys.exit(1)


def read_uid(reader) -> Optional[str]:
    """Poll once and resolve 4/7-byte UIDs using pi-rc522's cascade API."""
    error, _ = reader.request(req_mode=reader.act_reqall)
    if error:
        return None
    error, uid = reader.anticoll()
    if error or not uid or len(uid) != 5:
        raise RuntimeError("NFC anticollision read failed")
    if uid[4] != uid[0] ^ uid[1] ^ uid[2] ^ uid[3]:
        raise RuntimeError("NFC UID checksum failed")
    if uid[0] == 0x88:
        if not callable(getattr(reader, "anticoll2", None)):
            raise RuntimeError("Installed RC522 driver does not support cascade UIDs")
        if reader.select_tag(uid):
            raise RuntimeError("NFC cascade selection failed")
        error, second = reader.anticoll2()
        if error or not second or len(second) != 5:
            raise RuntimeError("NFC cascade read failed")
        if second[4] != second[0] ^ second[1] ^ second[2] ^ second[3]:
            raise RuntimeError("NFC cascade checksum failed")
        if second[0] == 0x88:
            raise RuntimeError("10-byte cascade UIDs require a supported reader driver")
        return uid_to_string(uid[1:4] + second[:4])
    return uid_to_string(uid[:4])


class ControlApi:
    def __init__(self, registry: TileRegistry, dispatcher: ActionDispatcher, spotify, ha: HomeAssistantClient) -> None:
        self.registry = registry
        self.dispatcher = dispatcher
        self.spotify = spotify
        self.ha = ha

    def spotify_devices(self) -> list[dict[str, Any]]:
        if self.spotify is None:
            raise UnavailableError("Spotify is not configured")
        devices = self.spotify.devices().get("devices", [])
        return [
            {
                "id": d.get("id"), "name": d.get("name"), "type": d.get("type"),
                "active": d.get("is_active"), "volume": d.get("volume_percent"),
            }
            for d in devices
        ]

    def spotify_state(self) -> dict[str, Any]:
        if self.spotify is None:
            raise UnavailableError("Spotify is not configured")
        state = self.spotify.current_playback() or {}
        item = state.get("item") or {}
        artists = item.get("artists") or []
        return {
            "playing": bool(state.get("is_playing")),
            "device": (state.get("device") or {}).get("name"),
            "device_id": (state.get("device") or {}).get("id"),
            "title": item.get("name"),
            "artists": [a.get("name") for a in artists if a.get("name")],
            "progress_ms": state.get("progress_ms"),
            "duration_ms": item.get("duration_ms"),
        }

    def spotify_control(self, body: dict[str, Any]) -> None:
        if self.spotify is None:
            raise UnavailableError("Spotify is not configured")
        command = str(body.get("command", "")).lower()
        device_id = str(body.get("device_id", "")).strip() or None
        device_id = device_id or get_device_id(self.spotify)
        if not device_id:
            raise UnavailableError("No configured Spotify playback target is available")
        if command == "play":
            uri = str(body.get("uri", "")).strip()
            if uri:
                _normalise_action({"type": "spotify", "uri": uri})
                if not start_playback(self.spotify, uri, device_id or get_device_id(self.spotify)):
                    raise RuntimeError("Spotify playback failed")
            else:
                self.spotify.start_playback(device_id=device_id)
        elif command == "pause":
            self.spotify.pause_playback(device_id=device_id)
        elif command == "next":
            self.spotify.next_track(device_id=device_id)
        elif command == "previous":
            self.spotify.previous_track(device_id=device_id)
        elif command == "volume":
            volume = body.get("volume")
            if type(volume) is not int or not 0 <= volume <= 100:
                raise ValueError("volume must be an integer from 0 to 100")
            self.spotify.volume(volume, device_id=device_id)
        else:
            raise ValueError("unsupported Spotify command")


def _make_handler(api: ControlApi):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HexPlayer/2"

        def log_message(self, fmt: str, *args) -> None:
            log.debug("api: " + fmt, *args)

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 0 or length > 65536:
                raise ValueError("request too large")
            if not length:
                return {}
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request body")
            value = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _authorised(self) -> bool:
            if not API_KEY:
                return False
            auth = self.headers.get("Authorization", "")
            return secrets.compare_digest(auth.encode(), f"Bearer {API_KEY}".encode()) or secrets.compare_digest(self.headers.get("X-HexPlayer-Key", "").encode(), API_KEY.encode())

        def _route(self) -> tuple[int, Any]:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/api/v1/health" and self.command == "GET":
                return HTTPStatus.OK, {"ok": True, "version": 2, "api_auth": bool(API_KEY)}
            if not self._authorised():
                return HTTPStatus.UNAUTHORIZED, {"error": "unauthorised"}

            if path == "/api/v1/cards" and self.command == "GET":
                return HTTPStatus.OK, {"cards": api.registry.all()}
            if path.startswith("/api/v1/cards/"):
                raw_uid = unquote(path[len("/api/v1/cards/"):])
                if raw_uid.lower().endswith("/trigger") and self.command == "POST":
                    uid = normalise_uid(raw_uid[:-len("/trigger")])
                    card = api.registry.get(uid)
                    if card is None:
                        return HTTPStatus.NOT_FOUND, {"error": "card not found"}
                    ok = api.dispatcher.dispatch(card)
                    return HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY, {"ok": ok}
                uid = normalise_uid(raw_uid)
                if self.command == "PUT":
                    card = api.registry.upsert(uid, self._body())
                    return HTTPStatus.OK, {"uid": uid, "card": card}
                if self.command == "DELETE":
                    deleted = api.registry.delete(uid)
                    return (HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND), {"deleted": deleted}

            if path == "/api/v1/spotify/devices" and self.command == "GET":
                return HTTPStatus.OK, {"devices": api.spotify_devices()}
            if path == "/api/v1/spotify/state" and self.command == "GET":
                return HTTPStatus.OK, api.spotify_state()
            if path == "/api/v1/spotify/control" and self.command == "POST":
                api.spotify_control(self._body())
                return HTTPStatus.OK, {"ok": True}

            if path == "/api/v1/home-assistant/status" and self.command == "GET":
                return HTTPStatus.OK, api.ha.status()
            if path == "/api/v1/home-assistant/media-players" and self.command == "GET":
                return HTTPStatus.OK, {"media_players": api.ha.media_players()}
            if path == "/api/v1/home-assistant/config" and self.command == "PUT":
                trusted_proxy = os.getenv("HEXPLAYER_TRUST_PROXY_TLS", "false").lower() == "true"
                if self.client_address[0] not in {"127.0.0.1", "::1"} or not trusted_proxy:
                    return HTTPStatus.FORBIDDEN, {"error": "Secret provisioning requires a trusted HTTPS proxy bound to loopback; otherwise configure server .env manually"}
                body = self._body()
                api.ha.configure(body.get("url", ""), body.get("token", ""))
                return HTTPStatus.OK, {"ok": True}
            if path == "/api/v1/home-assistant/control" and self.command == "POST":
                body = self._body()
                action = _normalise_action({**body, "type": "ha_service"})
                data = dict(action.get("data", {}))
                if action.get("entity_id"):
                    data["entity_id"] = action["entity_id"]
                result = api.ha.call_service(action["domain"], action["service"], data)
                return HTTPStatus.OK, {"ok": True, "result": result}

            return HTTPStatus.NOT_FOUND, {"error": "not found"}

        def _handle(self) -> None:
            try:
                status, payload = self._route()
            except (ValueError, UnicodeError) as exc:
                status, payload = HTTPStatus.BAD_REQUEST, {"error": str(exc)}
            except UnavailableError as exc:
                status, payload = HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)}
            except RegistryConflictError as exc:
                status, payload = HTTPStatus.CONFLICT, {"error": str(exc)}
            except (requests.RequestException, RuntimeError):
                status, payload = HTTPStatus.BAD_GATEWAY, {"error": "Upstream action failed; verify integration connectivity and permissions"}
            except Exception:
                log.error("API request failed")
                status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"}
            self._send(int(status), payload)

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_DELETE = _handle

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

    return Handler


def start_api(api: ControlApi) -> Optional[ThreadingHTTPServer]:
    if not API_KEY:
        log.warning("HEXPLAYER_API_KEY is empty — remote control API is disabled")
        return None
    server = ThreadingHTTPServer((API_HOST, API_PORT), _make_handler(api))
    thread = threading.Thread(target=server.serve_forever, name="hexplayer-api", daemon=True)
    thread.start()
    log.info("Control API listening on %s:%d", API_HOST, API_PORT)
    return server


class TilePresence:
    """One action per placement, with debounced removal and Spotify retries."""

    def __init__(self, dispatcher, registry):
        self.dispatcher, self.registry = dispatcher, registry
        self.uid = None
        self.absent_since = None
        self.handled = False
        self.next_attempt = 0.0
        self.spotify_target = None

    def read_failed(self):
        self.absent_since = None

    def update(self, uid, now):
        if uid is None:
            if self.uid is not None:
                if self.absent_since is None:
                    self.absent_since = now
                if now - self.absent_since < DEBOUNCE_SECONDS:
                    return
                self.uid = None
                self.handled = False
                self.next_attempt = now
            if self.spotify_target and now >= self.next_attempt:
                self.next_attempt = now + max(DEBOUNCE_SECONDS, POLL_INTERVAL)
                try:
                    self.dispatcher.spotify.pause_playback(device_id=self.spotify_target)
                except Exception:
                    log.warning("Spotify pause failed; will retry")
                else:
                    self.spotify_target = None
            return
        self.absent_since = None
        if uid != self.uid:
            self.uid, self.handled, self.next_attempt = uid, False, now
        if self.handled or now < self.next_attempt:
            return
        card = self.registry.get(uid)
        if card is None:
            self.handled = True
            return
        action = card["action"]
        spotify = action["type"] == "spotify"
        self.next_attempt = now + max(DEBOUNCE_SECONDS, POLL_INTERVAL)
        if spotify:
            target = action.get("device_id") or get_device_id(self.dispatcher.spotify)
            if not target:
                return
            self.spotify_target = target
            card = {**card, "action": {**action, "device_id": target}}
        else:
            # HA events/services are potentially non-idempotent: never replay a
            # timeout automatically. Removal and a deliberate replacement retry.
            self.handled = True
        try:
            self.handled = bool(self.dispatcher.dispatch(card)) or not spotify
        except Exception:
            log.warning("Tile action failed; check integration status")


def main() -> None:
    print("\nHexPlayer v2 — NFC + Android/Home Assistant control\n")
    spotify = _build_spotify_client()
    reader = _build_nfc_reader()
    registry = TileRegistry()
    ha = HomeAssistantClient()
    dispatcher = ActionDispatcher(spotify, ha)
    api_server = start_api(ControlApi(registry, dispatcher, spotify, ha))

    presence = TilePresence(dispatcher, registry)
    log.info("HexPlayer ready; %d card(s) registered", len(registry.all()))

    try:
        while _running:
            try:
                uid = read_uid(reader)
            except Exception as exc:
                log.error("NFC read error: %s", exc)
                presence.read_failed()
                time.sleep(1)
                continue
            presence.update(uid, time.monotonic())
            time.sleep(POLL_INTERVAL)
    finally:
        if api_server is not None:
            api_server.shutdown()
            api_server.server_close()
        try:
            reader.cleanup()
        except Exception:
            pass
        log.info("HexPlayer stopped")


if __name__ == "__main__":
    main()

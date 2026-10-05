"""Offline API, validation and presence regressions. Every integration is mocked."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import hexplayer as hp


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = hp.TileRegistry(Path(self.tmp.name) / 'tiles.json')
        self.sp, self.ha = Mock(), Mock()
        self.api = hp.ControlApi(self.registry, hp.ActionDispatcher(self.sp, self.ha), self.sp, self.ha)
        self.key = patch.object(hp, 'API_KEY', 'test-key')
        self.key.start()
        self.addCleanup(self.key.stop)
        self.server = hp.ThreadingHTTPServer(('127.0.0.1', 0), hp._make_handler(self.api))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        headers = {'Authorization': 'Bearer test-key'} if auth else {}
        conn.request(method, '/api/v1/' + path, json.dumps(body) if body is not None else None, headers)
        res = conn.getresponse()
        result = res.status, json.loads(res.read())
        conn.close()
        return result

    def test_auth_required_and_health_public(self):
        self.assertEqual(self.request('GET', 'cards', auth=False)[0], 401)
        self.assertEqual(self.request('GET', 'health', auth=False)[0], 200)

    def test_save_reload_delete(self):
        card = {'name': 'Kitchen', 'action': {'type': 'ha_event', 'event_type': 'hex_play', 'data': {'room': 'kitchen'}}}
        self.assertEqual(self.request('PUT', 'cards/01-02-03-04', card)[0], 200)
        self.assertEqual(hp.TileRegistry(self.registry.path).get('01-02-03-04'), card)
        self.assertEqual(self.request('GET', 'cards')[1]['cards']['01-02-03-04'], card)
        self.assertEqual(self.request('DELETE', 'cards/01-02-03-04')[0], 200)
        self.assertEqual(self.request('DELETE', 'cards/01-02-03-04')[0], 404)
        self.ha.call_service.assert_not_called()
        self.sp.start_playback.assert_not_called()

    def test_invalid_uid_and_body(self):
        self.assertEqual(self.request('PUT', 'cards/GG-00-00-00', {'action': {'type': 'ha_event', 'event_type': 'x'}})[0], 400)
        self.assertEqual(self.request('PUT', 'cards/01-02-03-04', [1])[0], 400)

    def test_upstream_error_is_safe_and_propagated(self):
        self.ha.media_players.side_effect = hp.requests.ConnectionError('secret-token-in-error')
        code, body = self.request('GET', 'home-assistant/media-players')
        self.assertEqual(code, 502)
        self.assertNotIn('secret-token', json.dumps(body))

    def test_unconfigured_spotify(self):
        self.api.spotify = None
        self.assertEqual(self.request('GET', 'spotify/devices')[0], 503)

    def test_ha_control_rejects_path_injection_and_data_array(self):
        for body in [{'domain': '../x', 'service': 'on'}, {'domain': 'light', 'service': 'turn_on', 'data': []}]:
            self.assertEqual(self.request('POST', 'home-assistant/control', body)[0], 400)
        self.ha.call_service.assert_not_called()

    def test_provision_requires_secure_proxy(self):
        with patch.dict(hp.os.environ, {'HEXPLAYER_TRUST_PROXY_TLS': 'false'}):
            self.assertEqual(self.request('PUT', 'home-assistant/config', {'url': 'https://ha.example', 'token': 'test'})[0], 403)
        self.ha.configure.assert_not_called()

    def test_mocked_trigger_contract(self):
        self.registry.upsert('01-02-03-04', {'action': {'type': 'ha_service', 'domain': 'automation', 'service': 'trigger', 'entity_id': 'automation.example', 'data': {}}})
        self.assertEqual(self.request('POST', 'cards/01-02-03-04/trigger')[0], 200)
        self.ha.call_service.assert_called_once_with('automation', 'trigger', {'entity_id': 'automation.example'})


    def test_ha_control_explicit_target_overrides_data_target(self):
        self.ha.call_service.return_value = []
        code, body = self.request('POST', 'home-assistant/control', {
            'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.target_b',
            'data': {'entity_id': 'light.dashboard_a', 'brightness': 80}})
        self.assertEqual(code, 200)
        self.assertTrue(body['ok'])
        self.ha.call_service.assert_called_once_with('light', 'turn_on', {'entity_id': 'light.target_b', 'brightness': 80})

    def test_trigger_uses_saved_spotify_target_despite_dashboard_target(self):
        self.registry.upsert('01-02-03-04', {'action': {'type': 'spotify', 'uri': 'spotify:track:a', 'device_id': 'target-b'}})
        self.assertEqual(self.request('POST', 'cards/01-02-03-04/trigger', {'device_id': 'dashboard-a'})[0], 200)
        self.sp.start_playback.assert_called_once_with(device_id='target-b', uris=['spotify:track:a'])

    def test_trigger_uses_saved_ha_target_despite_dashboard_target(self):
        self.registry.upsert('01-02-03-04', {'action': {'type': 'ha_service', 'domain': 'automation', 'service': 'trigger', 'entity_id': 'automation.target_b', 'data': {'entity_id': 'automation.old'}}})
        self.assertEqual(self.request('POST', 'cards/01-02-03-04/trigger', {'entity_id': 'automation.dashboard_a'})[0], 200)
        self.ha.call_service.assert_called_once_with('automation', 'trigger', {'entity_id': 'automation.target_b'})

class PersistenceTests(unittest.TestCase):
    def test_failed_write_does_not_mutate_memory(self):
        with tempfile.TemporaryDirectory() as td:
            registry = hp.TileRegistry(Path(td) / 'tiles.json')
            card = {'action': {'type': 'ha_event', 'event_type': 'hello'}}
            registry.upsert('01-02-03-04', card)
            with patch.object(hp, '_atomic_json_write', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    registry.upsert('05-06-07-08', card)
                with self.assertRaises(OSError):
                    registry.delete('01-02-03-04')
            self.assertEqual(set(registry.all()), {'01-02-03-04'})

    def test_invalid_schema(self):
        invalid = [
            {'type': 'spotify', 'uri': 'https://spotify.com/track/x'},
            {'type': 'ha_event', 'event_type': '../bad'},
            {'type': 'ha_service', 'domain': 'light', 'service': 'on', 'data': []},
            {'type': 'ha_media', 'entity_id': 'media_player.x', 'media_content_id': 'x', 'data': {'entity_id': 'media_player.y'}},
            {'type': 'ha_media', 'entity_id': 'media_player.x', 'media_content_id': 12},
        ]
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(ValueError):
                hp.normalise_card({'action': action})

    def test_secure_secret_write_and_no_echo(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(hp.os.environ, {}, clear=True):
            path = Path(td) / 'secret.json'
            ha = hp.HomeAssistantClient(path)
            ha.configure('https://ha.example', 'user-entered-test-token')
            self.assertEqual(json.loads(path.read_text())['token'], 'user-entered-test-token')
            with patch.object(ha, '_request', side_effect=RuntimeError('user-entered-test-token')):
                self.assertNotIn('user-entered-test-token', json.dumps(ha.status()))
            with self.assertRaises(ValueError):
                ha.configure('http://remote.example', 'token')


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.sp, self.ha = Mock(), Mock()
        self.registry = Mock()
        self.registry.get.side_effect = lambda uid: {'action': {'type': 'spotify', 'uri': 'spotify:track:' + uid, 'device_id': 'device'}} if uid in {'A', 'B'} else None
        self.presence = hp.TilePresence(hp.ActionDispatcher(self.sp, self.ha), self.registry)

    def update(self, uid, now):
        self.presence.update(uid, now)

    def test_hold_never_restarts(self):
        for now in [0, .2, 3, 100, 3600]: self.update('A', now)
        self.sp.start_playback.assert_called_once()

    def test_removal_pauses_and_replacement_replays(self):
        self.update('A', 0)
        self.update(None, 1)
        self.update(None, 3.9)
        self.sp.pause_playback.assert_not_called()
        self.update(None, 4)
        self.update(None, 20)
        self.sp.pause_playback.assert_called_once_with(device_id='device')
        self.update('A', 21)
        self.assertEqual(self.sp.start_playback.call_count, 2)

    def test_direct_replacement(self):
        self.update('A', 0)
        self.update('B', 1)
        self.update('B', 100)
        self.assertEqual(self.sp.start_playback.call_count, 2)

    def test_brief_absence_and_read_failure_do_not_restart(self):
        self.update('A', 0)
        self.update(None, 1)
        self.presence.read_failed()
        self.update(None, 10)
        self.update('A', 11)
        self.sp.start_playback.assert_called_once()
        self.sp.pause_playback.assert_not_called()

    def test_failed_start_retries(self):
        self.sp.start_playback.side_effect = [RuntimeError('offline'), None]
        for now in [0, 1, 3, 4, 100]: self.update('A', now)
        self.assertEqual(self.sp.start_playback.call_count, 2)

    def test_removal_cancels_failed_start(self):
        self.sp.start_playback.side_effect = RuntimeError('offline')
        self.update('A', 0)
        self.update(None, 1)
        self.update(None, 4)
        self.update(None, 100)
        self.sp.start_playback.assert_called_once()
        self.sp.pause_playback.assert_called_once()

    def test_failed_pause_retries(self):
        self.sp.pause_playback.side_effect = [RuntimeError('offline'), None]
        self.update('A', 0)
        for now in [1, 4, 5, 7, 100]: self.update(None, now)
        self.assertEqual(self.sp.pause_playback.call_count, 2)

    def test_new_tile_supersedes_failed_pause(self):
        self.sp.pause_playback.side_effect = RuntimeError('offline')
        self.update('A', 0)
        self.update(None, 1)
        self.update(None, 4)
        self.update('B', 5)
        self.update('B', 100)
        self.sp.pause_playback.assert_called_once()
        self.assertEqual(self.sp.start_playback.call_count, 2)

    def test_unknown_and_empty_are_inert(self):
        for uid, now in [(None, 0), ('unknown', 1), ('unknown', 100), (None, 101), (None, 105)]: self.update(uid, now)
        self.sp.start_playback.assert_not_called()
        self.sp.pause_playback.assert_not_called()

    def test_ha_failure_is_not_repeated_while_held(self):
        self.registry.get.side_effect = None
        self.registry.get.return_value = {'action': {'type': 'ha_event', 'event_type': 'test'}}
        self.ha.fire_event.side_effect = RuntimeError('timeout after possible execution')
        for now in [0, 3, 100]: self.update('A', now)
        self.ha.fire_event.assert_called_once()
        self.update(None, 101)
        self.update(None, 104)
        self.update('A', 105)
        self.assertEqual(self.ha.fire_event.call_count, 2)

    def test_reader_nonblocking_canonical_uid(self):
        reader = Mock()
        reader.request.return_value = (False, 16)
        reader.anticoll.return_value = (False, [1, 2, 3, 4, 4])
        self.assertEqual(hp.read_uid(reader), '01-02-03-04')
        reader.wait_for_tag.assert_not_called()
        reader.request.assert_called_once_with(req_mode=reader.act_reqall)

    def test_reader_absence(self):
        reader = Mock()
        reader.request.return_value = (True, None)
        self.assertIsNone(hp.read_uid(reader))
        reader.anticoll.assert_not_called()

    def test_reader_failure_is_not_absence(self):
        reader = Mock()
        reader.request.return_value = (False, 16)
        for result in [(True, []), (False, [1, 2, 3, 4, 0]), (False, [0x88, 1, 2, 3, 0x88])]:
            reader.anticoll.return_value = result
            with self.assertRaises(RuntimeError): hp.read_uid(reader)

class AdditionalContracts(unittest.TestCase):
    def test_missing_spotify_config_does_not_require_sdk_or_network(self):
        with patch.dict(hp.os.environ, {}, clear=True):
            self.assertIsNone(hp._build_spotify_client())

    def test_missing_device_retries_without_active_device_fallback(self):
        sp, ha, registry = Mock(), Mock(), Mock()
        registry.get.return_value = {'action': {'type': 'spotify', 'uri': 'spotify:track:a'}}
        presence = hp.TilePresence(hp.ActionDispatcher(sp, ha), registry)
        with patch.object(hp, 'get_device_id', side_effect=[None, 'device']) as lookup:
            for now in [0, 1, 3, 100]: presence.update('A', now)
        self.assertEqual(lookup.call_count, 2)
        sp.start_playback.assert_called_once_with(device_id='device', uris=['spotify:track:a'])

    def test_ha_media_and_event_dispatch_contracts(self):
        sp, ha = Mock(), Mock()
        dispatcher = hp.ActionDispatcher(sp, ha)
        dispatcher.dispatch(hp.normalise_card({'action': {'type': 'ha_media', 'entity_id': 'media_player.room', 'media_content_id': 'https://example.test/audio', 'data': {'enqueue': 'replace'}}}))
        ha.call_service.assert_called_once_with('media_player', 'play_media', {'entity_id': 'media_player.room', 'media_content_id': 'https://example.test/audio', 'media_content_type': 'music', 'enqueue': 'replace'})
        dispatcher.dispatch(hp.normalise_card({'action': {'type': 'ha_event', 'event_type': 'hexplayer', 'data': {'id': 'abc'}}}))
        ha.fire_event.assert_called_once_with('hexplayer', {'id': 'abc'})
        sp.start_playback.assert_not_called()

    def test_main_reader_error_preserves_presence_and_cleans_up(self):
        sp, reader, registry, server = Mock(), Mock(), Mock(), Mock()
        registry.get.return_value = {'action': {'type': 'spotify', 'uri': 'spotify:track:a', 'device_id': 'device'}}
        registry.all.return_value = {}
        samples = ['A', None, OSError('SPI failure'), None, 'A', None, None]
        sleeps = []
        def sleep(_):
            sleeps.append(1)
            if len(sleeps) == len(samples): hp._running = False
        with patch.object(hp, '_running', True), patch.object(hp, '_build_spotify_client', return_value=sp), patch.object(hp, '_build_nfc_reader', return_value=reader), patch.object(hp, 'TileRegistry', return_value=registry), patch.object(hp, 'start_api', return_value=server), patch.object(hp, 'read_uid', side_effect=samples), patch.object(hp.time, 'monotonic', side_effect=[0, 1, 10, 11, 12, 15]), patch.object(hp.time, 'sleep', side_effect=sleep), patch('builtins.print'):
            hp.main()
        sp.start_playback.assert_called_once()
        sp.pause_playback.assert_called_once_with(device_id='device')
        server.shutdown.assert_called_once()
        reader.cleanup.assert_called_once()

class CascadeReaderTests(unittest.TestCase):
    def reader(self):
        reader = Mock()
        reader.request.return_value = (False, 16)
        reader.anticoll.return_value = (False, [0x88, 1, 2, 3, 0x88])
        reader.select_tag.return_value = False
        reader.anticoll2.return_value = (False, [4, 5, 6, 7, 0])
        return reader

    def test_seven_byte_uid_matches_phone(self):
        reader = self.reader()
        self.assertEqual(hp.read_uid(reader), '01-02-03-04-05-06-07')
        reader.select_tag.assert_called_once_with([0x88, 1, 2, 3, 0x88])

    def test_cascade_read_failures_are_not_absence(self):
        for second in [(True, []), (False, [4, 5, 6, 7, 1]), (False, [0x88, 1, 2, 3, 0x88])]:
            reader = self.reader()
            reader.anticoll2.return_value = second
            with self.assertRaises(RuntimeError): hp.read_uid(reader)

    def test_cascade_selection_failure(self):
        reader = self.reader()
        reader.select_tag.return_value = True
        with self.assertRaises(RuntimeError): hp.read_uid(reader)
        reader.anticoll2.assert_not_called()

class StartupSecurityTests(unittest.TestCase):
    def test_empty_api_key_disables_server_and_denies_auth(self):
        with patch.object(hp, 'API_KEY', ''), patch.object(hp, 'ThreadingHTTPServer') as server:
            self.assertIsNone(hp.start_api(Mock()))
            server.assert_not_called()
        handler_type = hp._make_handler(Mock())
        handler = object.__new__(handler_type)
        handler.headers = {'Authorization': 'Bearer '}
        with patch.object(hp, 'API_KEY', ''):
            self.assertFalse(handler._authorised())

    def test_reader_initialization_matches_documented_bcm_wiring(self):
        import sys
        import types
        driver, gpio = Mock(), types.ModuleType('RPi.GPIO')
        gpio.BCM = 11
        rpi = types.ModuleType('RPi')
        rpi.GPIO = gpio
        module = types.ModuleType('pirc522')
        module.RFID = driver
        with patch.dict(sys.modules, {'RPi': rpi, 'RPi.GPIO': gpio, 'pirc522': module}), patch.dict(hp.os.environ, {'NFC_SPI_BUS': '0', 'NFC_SPI_DEVICE': '0'}):
            hp._build_nfc_reader()
        driver.assert_called_once_with(pin_rst=hp.NFC_RESET_PIN, pin_mode=11, pin_irq=None, bus=0, device=0)

class LegacyMigrationTests(unittest.TestCase):
    def test_load_lists_canonical_uid_and_delete_does_not_revive_alias(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tiles.json'
            path.write_text(json.dumps({'01-02-03-04-04': 'spotify:track:old'}))
            registry = hp.TileRegistry(path)
            self.assertEqual(set(registry.all()), {'01-02-03-04'})
            registry.upsert('01-02-03-04', {'action': {'type': 'spotify', 'uri': 'spotify:track:new'}})
            self.assertEqual(set(json.loads(path.read_text())['tiles']), {'01-02-03-04'})
            self.assertTrue(registry.delete('01-02-03-04'))
            self.assertIsNone(hp.TileRegistry(path).get('01-02-03-04'))
            self.assertIsNone(registry.get('01-02-03-04-04'))

    def test_conflicting_aliases_fail_visibly_without_mutating_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tiles.json'
            original = json.dumps({'01-02-03-04': 'spotify:track:new', '01-02-03-04-04': 'spotify:track:old'})
            path.write_text(original)
            with self.assertRaisesRegex(hp.RegistryConflictError, 'reconcile tiles.json'):
                hp.TileRegistry(path)
            self.assertEqual(path.read_text(), original)

    def test_identical_aliases_collapse_but_invalid_bcc_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tiles.json'
            path.write_text(json.dumps({'01-02-03-04': 'spotify:track:a', '01-02-03-04-04': 'spotify:track:a', '01-02-03-04-05': 'spotify:track:b'}))
            registry = hp.TileRegistry(path)
            self.assertEqual(set(registry.all()), {'01-02-03-04', '01-02-03-04-05'})
            self.assertEqual(registry.get('01-02-03-04-04')['action']['uri'], 'spotify:track:a')

class RegistryRecoveryTests(unittest.TestCase):
    def test_external_corruption_blocks_save_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tiles.json'
            registry = hp.TileRegistry(path)
            card = {'action': {'type': 'ha_event', 'event_type': 'hello'}}
            registry.upsert('01-02-03-04', card)
            damaged = '{"user editing this registry": '
            path.write_text(damaged)
            registry._mtime = -1
            with self.assertRaises(hp.RegistryConflictError):
                registry.upsert('05-06-07-08', card)
            self.assertEqual(path.read_text(), damaged)
            with self.assertRaises(hp.RegistryConflictError):
                registry.delete('01-02-03-04')
            self.assertEqual(path.read_text(), damaged)

    def test_invalid_row_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tiles.json'
            raw = json.dumps({'01-02-03-04': 'spotify:track:a', '05-06-07-08': {'action': {'type': 'user_extension'}}})
            path.write_text(raw)
            with self.assertRaises(hp.RegistryConflictError): hp.TileRegistry(path)
            self.assertEqual(path.read_text(), raw)

    def test_unreadable_registry_blocks_save(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'tiles.json'
            registry = hp.TileRegistry(path)
            card = {'action': {'type': 'ha_event', 'event_type': 'hello'}}
            registry.upsert('01-02-03-04', card)
            original = path.read_text()
            registry._mtime = -1
            with patch.object(Path, 'open', side_effect=PermissionError('denied')):
                with self.assertRaises(hp.RegistryConflictError): registry.upsert('05-06-07-08', card)
            self.assertEqual(path.read_text(), original)

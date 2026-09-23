import audioop
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import httpx
from panel_audio import segment_pcm
from panel_server import Controller, handler_for


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        backend = SimpleNamespace(settings=lambda: {'model': 'test', 'base': 'http://unused'}, SYSTEM='')
        with patch('panel_server.companion_module', return_value=backend):
            self.c = Controller(Path(self.temp.name)/'settings.json')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.c, 0))
        self.server.RequestHandlerClass = handler_for(self.c, self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = httpx.Client(base_url=f'http://127.0.0.1:{self.server.server_port}', trust_env=False)
        self.headers = {'X-Fuzozo-Token': self.c.csrf}

    def tearDown(self):
        self.client.close(); self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def test_foreign_origins_hosts_and_missing_token_cannot_control_robot(self):
        data = {'kind': 'volume', 'payload': {'level': 10}}
        self.assertEqual(self.client.post('/api/action', json=data).status_code, 403)
        self.assertEqual(self.client.post('/api/action', json=data, headers={**self.headers, 'Origin': 'https://example.org'}).status_code, 403)
        self.assertEqual(self.client.get('/api/status', headers={'Host': 'attacker.example'}).status_code, 403)
        self.assertTrue(self.c.work.empty())

    def test_invalid_values_never_enter_hardware_queue(self):
        for level in (-1, 101, True, '20', 12.5):
            response = self.client.post('/api/action', json={'kind': 'volume', 'payload': {'level': level}}, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertTrue(self.c.work.empty())
        self.assertEqual(self.client.get('/api/audio/not-a-job').status_code, 404)

    def test_commands_are_queued_and_stop_cancels_pending_work(self):
        ids = []
        for level in (20, 30):
            response = self.client.post('/api/action', json={'kind': 'volume', 'payload': {'level': level}}, headers=self.headers)
            self.assertEqual(response.status_code, 202); ids.append(response.json()['job_id'])
        self.client.post('/api/stop', json={}, headers=self.headers)
        self.assertTrue(self.c.work.empty())
        self.assertTrue(all(self.c.jobs[i]['status'] == 'cancelled' for i in ids))
        self.assertTrue(self.c.cancel.is_set())

    def test_settings_persist_without_private_ai_configuration(self):
        response = self.client.post('/api/settings', json={'speech_level': 25, 'wake_word': 'buddy'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.c.settings_path.read_text())
        self.assertEqual(saved['speech_level'], 25)
        self.assertEqual(saved['wake_word'], 'buddy')
        self.assertNotIn('key', saved)
        self.assertNotIn('base', saved)

    def test_stop_cancels_queue_and_active_operation_checks_before_next_step(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def execute(identity, kind, payload):
            calls.append(payload['level'])
            entered.set()
            release.wait(3)
            try:
                self.c.check_cancel()
                return {}
            finally:
                finished.set()
        with patch('panel_server.bridge_lock', side_effect=nullcontext), patch.object(self.c, 'execute', side_effect=execute):
            self.c.start()
            first = self.c.enqueue('volume', {'level': 20})
            try:
                self.assertTrue(entered.wait(2))
                second = self.c.enqueue('volume', {'level': 30})
                self.c.stop()
                release.set()
                self.assertTrue(finished.wait(2))
                self.c.work.join()
                self.assertEqual(calls, [20])
                self.assertEqual(self.c.jobs[first]['status'], 'cancelled')
                self.assertEqual(self.c.jobs[second]['status'], 'cancelled')
            finally:
                release.set(); self.c.shutdown.set(); self.c.thread.join(3)

    def test_failed_hardware_operation_requires_new_connection_check(self):
        self.c.device['verified'] = True
        with patch('panel_server.bridge_lock', side_effect=nullcontext), patch.object(self.c, 'execute', side_effect=TimeoutError('No matching debug response')):
            self.c.start()
            identity = self.c.enqueue('volume', {'level': 20})
            try:
                self.c.work.join()
                self.assertEqual(self.c.jobs[identity]['status'], 'error')
                self.assertFalse(self.c.device['verified'])
            finally:
                self.c.shutdown.set(); self.c.thread.join(3)


class AudioSegmentationTests(unittest.TestCase):
    def test_long_audio_preserves_all_samples_in_bounded_ordered_parts(self):
        pcm = (b'\x00\x10'*32000+b'\0\0'*4000)*5
        parts = segment_pcm(pcm)
        self.assertEqual(b''.join(parts), pcm)
        self.assertTrue(all(0 < len(p) <= 128000 and len(p)%2 == 0 for p in parts))
        self.assertGreater(len(parts), 1)


if __name__ == '__main__':
    unittest.main()

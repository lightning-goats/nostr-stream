import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import json
import os

from websockets.sync.server import serve


SCRIPT = Path(__file__).resolve().parents[1] / 'bin/lightning-goats-obs-watch'


def fake_systemd_run(home):
    runner = home / '.local/bin/systemd-run'
    runner.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n'
                      'while [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
    runner.chmod(0o700)
    return str(runner.parent) + ':' + os.environ['PATH']


class RecoveryTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), 'Unexpected OBS exits have no recovery watcher')
        loader = SourceFileLoader('obs_watch', str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_streaming_process_loss_requests_recovery_but_connection_loss_does_not(self):
        state = self.module().Recovery()
        state.status(True, now=0)
        self.assertFalse(state.should_launch(process_present=True, held=False, now=1))
        self.assertTrue(state.should_launch(process_present=False, held=False, now=1))

    def test_idle_obs_and_an_unobserved_stream_are_not_started(self):
        state = self.module().Recovery()
        self.assertFalse(state.should_launch(False, False, now=1))
        state.status(False, now=2)
        self.assertFalse(state.should_launch(False, False, now=3))

    def test_normal_exit_and_manual_stream_stop_disarm_recovery(self):
        for event in [
            {'eventType': 'ExitStarted'},
            {'eventType': 'StreamStateChanged', 'eventData': {
                'outputActive': False, 'outputState': 'OBS_WEBSOCKET_OUTPUT_STOPPING'}},
        ]:
            with self.subTest(event=event):
                state = self.module().Recovery()
                state.status(True, now=0)
                state.event(event)
                self.assertFalse(state.should_launch(False, False, now=1))

    def test_hold_disarms_recovery_even_after_hold_is_removed(self):
        state = self.module().Recovery()
        state.status(True, now=0)
        self.assertFalse(state.should_launch(False, True, now=1))
        self.assertFalse(state.should_launch(False, False, now=2))
        state.status(True, now=3)
        self.assertTrue(state.should_launch(False, False, now=4))

    def test_failed_start_is_retried_with_delay_and_startup_can_be_idle_briefly(self):
        state = self.module().Recovery()
        state.status(True, now=0)
        state.attempted(now=1)
        state.status(False, now=2)
        self.assertFalse(state.should_launch(False, False, now=3))
        self.assertTrue(state.should_launch(False, False, now=32))
        state.status(False, now=33)
        self.assertFalse(state.should_launch(False, False, now=34))

    def test_manual_stop_overrides_the_recovery_startup_grace(self):
        state = self.module().Recovery()
        state.status(True, now=0)
        state.attempted(now=1)
        state.event({'eventType': 'StreamStateChanged', 'eventData': {
            'outputActive': False, 'outputState': 'OBS_WEBSOCKET_OUTPUT_STOPPED'}})
        self.assertFalse(state.should_launch(False, False, now=32))

    def test_buffered_output_still_active_during_manual_stop_does_not_rearm(self):
        state = self.module().Recovery()
        state.status(True, now=0)
        state.event({'eventType': 'StreamStateChanged', 'eventData': {
            'outputActive': False, 'outputState': 'OBS_WEBSOCKET_OUTPUT_STOPPING'}})
        state.status(True, now=10)
        self.assertFalse(state.should_launch(False, False, now=11))
        state.event({'eventType': 'StreamStateChanged', 'eventData': {
            'outputActive': True, 'outputState': 'OBS_WEBSOCKET_OUTPUT_STARTED'}})
        self.assertTrue(state.should_launch(False, False, now=12))

    def test_starting_without_active_stream_does_not_arm_recovery(self):
        state = self.module().Recovery()
        state.event({'eventType': 'StreamStateChanged', 'eventData': {
            'outputActive': False, 'outputState': 'OBS_WEBSOCKET_OUTPUT_STARTING'}})
        self.assertFalse(state.should_launch(False, False, now=1))

    def test_late_reconnect_event_does_not_override_manual_stop(self):
        state = self.module().Recovery()
        state.status(True, now=0)
        state.event({'eventType': 'StreamStateChanged', 'eventData': {
            'outputActive': False, 'outputState': 'OBS_WEBSOCKET_OUTPUT_STOPPING'}})
        state.event({'eventType': 'StreamStateChanged', 'eventData': {
            'outputActive': True, 'outputState': 'OBS_WEBSOCKET_OUTPUT_RECONNECTED'}})
        self.assertFalse(state.should_launch(False, False, now=1))

    def test_process_discovery_excludes_zombies_and_distinguishes_pid_reuse(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for pid, name, status, ticks in [(10, 'obs', 'S', 100), (11, 'obs', 'Z', 101),
                                              (12, 'obs-browser', 'S', 102)]:
                entry = root / str(pid)
                entry.mkdir()
                (entry / 'comm').write_text(name + '\n')
                fields = [status] + ['0'] * 18 + [str(ticks)]
                (entry / 'stat').write_text(f'{pid} ({name}) ' + ' '.join(fields))
            self.assertEqual(module.obs_processes(root), {(10, 100)})
            (root / '10/stat').write_text('10 (obs) S ' + '0 ' * 18 + '200')
            self.assertEqual(module.obs_processes(root), {(10, 200)})

    def test_recovery_launcher_skips_crash_dialog_and_keeps_diagnostics_private(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            launcher = home / '.local/bin/lightning-goats-obs'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            launcher.chmod(0o700)
            with mock.patch.dict(os.environ, {'PATH': fake_systemd_run(home)}):
                child = module.launch(home)
            self.assertEqual(child.wait(timeout=3), 0)
            log = home / '.local/state/obs-recovery/launch.log'
            self.assertIn('--recover', log.read_text())
            self.assertIn('--unit=lightning-goats-obs-recovery', log.read_text())
            self.assertIn('--property=StandardOutput=append:' + str(log), log.read_text())
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_local_protocol_recovers_a_crash_and_respects_shutdown_and_socket_only_failure(self):
        for scenario in ['crash', 'normal-exit', 'socket-only', 'stale-status-after-stop']:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                module = self.module()
                home = Path(directory)
                launcher = home / '.local/bin/lightning-goats-obs'
                launcher.parent.mkdir(parents=True)
                marker = home / 'recovered'
                launcher.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
                launcher.chmod(0o700)
                ready = threading.Event()
                gone = threading.Event()
                failures = []
                children = []
                original_launch = module.launch

                def launch(test_home):
                    child = original_launch(test_home)
                    children.append(child)
                    return child

                def handler(ws):
                    try:
                        if ready.is_set():
                            return
                        ws.send(json.dumps({'op': 0, 'd': {'rpcVersion': 1,
                            'authentication': {'salt': 'salt', 'challenge': 'challenge'}}}))
                        identify = json.loads(ws.recv(timeout=3))
                        self.assertEqual(identify, {'op': 1, 'd': {
                            'rpcVersion': 1, 'eventSubscriptions': 65,
                            'authentication': '3Z430HfPPGk0ZjvYPAB1t4EM70Y2vwxE4vJz3SBbx2I='}})
                        ws.send(json.dumps({'op': 2, 'd': {'negotiatedRpcVersion': 1}}))
                        request = json.loads(ws.recv(timeout=3))
                        self.assertEqual(request['d']['requestType'], 'GetStreamStatus')
                        if scenario == 'stale-status-after-stop':
                            ws.send(json.dumps({'op': 5, 'd': {'eventType': 'StreamStateChanged',
                                'eventIntent': 64, 'eventData': {'outputActive': False,
                                    'outputState': 'OBS_WEBSOCKET_OUTPUT_STOPPING'}}}))
                        ws.send(json.dumps({'op': 7, 'd': {
                            'requestId': request['d']['requestId'],
                            'requestStatus': {'result': True, 'code': 100},
                            'responseData': {'outputActive': True}}}))
                        if scenario == 'normal-exit':
                            ws.send(json.dumps({'op': 5, 'd': {
                                'eventType': 'ExitStarted', 'eventIntent': 1, 'eventData': {}}}))
                        if scenario != 'socket-only':
                            gone.set()
                        ready.set()
                    except BaseException as error:
                        failures.append(error)
                        ready.set()

                class Finished(Exception):
                    pass

                pauses = []
                def pause(_):
                    pauses.append(1)
                    time.sleep(0.02)
                    if ready.is_set() and (marker.exists() or len(pauses) >= 5):
                        for child in children:
                            child.wait(timeout=3)
                        raise Finished()
                    if len(pauses) > 20:
                        raise AssertionError('Watcher failed to handle local OBS fixture')

                with serve(handler, '127.0.0.1', 0) as server:
                    port = server.socket.getsockname()[1]
                    config = home / 'snap/obs-studio/common/.config/obs-studio/plugin_config/obs-websocket/config.json'
                    config.parent.mkdir(parents=True)
                    config.write_text(json.dumps({'server_port': port, 'server_password': 'test-password'}))
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    with mock.patch.object(module, 'obs_processes', side_effect=lambda:
                            set() if gone.is_set() else {(123, 456)}), \
                            mock.patch.dict(os.environ, {'PATH': fake_systemd_run(home)}), \
                            mock.patch.object(module, 'launch', side_effect=launch), \
                            mock.patch.object(module, 'time', SimpleNamespace(
                                monotonic=time.monotonic, sleep=pause)):
                        with self.assertRaises(Finished):
                            module.watch(home)
                    server.shutdown()
                    thread.join(timeout=3)
                self.assertEqual(failures, [])
                self.assertEqual(marker.exists(), scenario == 'crash')


if __name__ == '__main__':
    unittest.main()

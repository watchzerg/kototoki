"""Offline telemetry contracts; never launch hardware queries in routine tests."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from experiments.translation_monitor import NvidiaStream, ResourceMonitor, interval_summary, parse_gpu_line


class FakeGpu:
    intervals = [.25, .251]
    reader_cpu_seconds = .001
    child_cpu_seconds = .002
    command = ['fake-gpu']

    def __init__(self, *args):
        self.closed = False

    def sample(self):
        return {'memory_used_mib': 100, 'memory_free_mib': 200,
                'memory_total_mib': 300, 'age_seconds': .01}

    def close(self):
        self.closed = True


class FakeMemory:
    def __init__(self):
        self.closed = False

    def sample(self, pid):
        return {'pid': pid, 'working_set_bytes': 123, 'private_commit_bytes': 456,
                'shared_gpu_bytes': None, 'null_reasons': {'shared_gpu_bytes': 'No instance'}}

    def close(self):
        self.closed = True


class MonitorTests(unittest.TestCase):
    def test_gpu_units_and_unavailable_fields(self):
        row = parse_gpu_line('0, GPU-uuid, RTX 5080, 617.14, 1215, 14763, 16303, 0, 34.37, 47, [N/A], 405')
        self.assertEqual(row['memory_total_mib'], 16303)
        self.assertEqual(row['power_watts'], 34.37)
        self.assertIsNone(row['sm_clock_mhz'])
        self.assertIn('sm_clock_mhz', row['null_reasons'])
        with self.assertRaises(ValueError):
            parse_gpu_line('driver notice')

    def test_timestamps_phase_pid_and_reusable_summary(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            'experiments.translation_monitor.NvidiaStream', FakeGpu), patch(
            'experiments.translation_monitor.WindowsMemoryProbe', FakeMemory):
            with ResourceMonitor(Path(temp), .2, target_pid=123) as monitor:
                monitor.mark_phase('inference', {'window_id': 'w1'})
                monitor.set_target(456)
                time.sleep(.23)
            rows = [json.loads(line) for line in (Path(temp) / 'resource-samples.jsonl').read_text().splitlines()]
            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual(rows[-1]['memory']['pid'], 456)
            self.assertEqual(rows[-1]['phase'], 'inference')
            self.assertGreater(rows[-1]['utc_epoch_seconds'], rows[0]['utc_epoch_seconds'])
            self.assertTrue(rows[-1]['utc'].endswith('+00:00'))
            events = [json.loads(line) for line in (Path(temp) / 'resource-events.jsonl').read_text().splitlines()]
            self.assertEqual(events[-1]['data']['window_id'], 'w1')
            self.assertEqual(monitor.summary['minimum_device_free_mib'], 200)
            self.assertEqual(monitor.summary['peak_device_memory_mib'], 100)
            self.assertIs(monitor.stop(), monitor.summary)
            self.assertTrue(monitor.gpu.closed)
            self.assertTrue(monitor.memory.closed)

    def test_pid_file_failure_is_explicit_and_no_stale_target(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            'experiments.translation_monitor.NvidiaStream', FakeGpu), patch(
            'experiments.translation_monitor.WindowsMemoryProbe', FakeMemory):
            root = Path(temp)
            pidfile = root / 'server.pid'
            pidfile.write_text('{"pid": 789}')
            with ResourceMonitor(root, .2, pid_file=pidfile) as monitor:
                time.sleep(.03)
                pidfile.write_text('invalid')
                time.sleep(.21)
            rows = [json.loads(line) for line in (root / 'resource-samples.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['memory']['pid'], 789)
            self.assertIsNone(rows[-1]['memory']['pid'])
            self.assertIn('target_pid', rows[-1]['memory']['null_reasons'])

    def test_exception_stops_monitor_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            'experiments.translation_monitor.NvidiaStream', FakeGpu), patch(
            'experiments.translation_monitor.WindowsMemoryProbe', FakeMemory):
            with self.assertRaisesRegex(ValueError, 'test error'):
                with ResourceMonitor(Path(temp), .2, target_pid=123) as monitor:
                    raise ValueError('test error')
            self.assertTrue(monitor.finished.is_set())
            self.assertTrue(monitor.gpu.closed)
            self.assertEqual(monitor.target_pid, 123)

    def test_invalid_config_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            ResourceMonitor(Path('.'), interval_seconds=.1)
        with self.assertRaises(ValueError):
            ResourceMonitor(Path('.'), target_pid=0)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'resource-samples.jsonl').write_text('preserve me')
            with self.assertRaises(FileExistsError):
                ResourceMonitor(Path(temp)).start()
            self.assertEqual((Path(temp) / 'resource-samples.jsonl').read_text(), 'preserve me')

    def test_interval_statistics_empty_and_nonempty(self):
        self.assertIsNone(interval_summary([])['median_seconds'])
        self.assertEqual(interval_summary([.3, .1, .2])['median_seconds'], .2)

    def test_missing_gpu_query_reports_null_reason(self):
        with patch('experiments.translation_monitor.subprocess.Popen', side_effect=FileNotFoundError('missing tool')):
            stream = NvidiaStream(.25)
            row = stream.sample()
            self.assertIsNone(row['memory_used_mib'])
            self.assertIn('missing tool', row['null_reasons']['gpu'])
            stream.close()

    def test_probe_failure_is_saved_and_cleanup_runs(self):
        class BrokenMemory(FakeMemory):
            def sample(self, pid):
                raise RuntimeError('probe failed')

        with tempfile.TemporaryDirectory() as temp, patch(
            'experiments.translation_monitor.NvidiaStream', FakeGpu), patch(
            'experiments.translation_monitor.WindowsMemoryProbe', BrokenMemory):
            with ResourceMonitor(Path(temp)) as monitor:
                monitor.thread.join(timeout=1)
            self.assertIn('probe failed', monitor.summary['worker_error'])
            self.assertTrue(monitor.memory.closed)


if __name__ == '__main__':
    unittest.main()

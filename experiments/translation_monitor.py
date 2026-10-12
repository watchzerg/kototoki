"""Independent, offline resource telemetry for serial local translation runs."""

import argparse
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import threading
import time


GPU_FIELDS = ('index', 'uuid', 'name', 'driver_version', 'memory.used', 'memory.free',
              'memory.total', 'utilization.gpu', 'power.draw', 'temperature.gpu',
              'clocks.current.sm', 'clocks.current.memory')
GPU_NUMERIC = ('memory_used_mib', 'memory_free_mib', 'memory_total_mib',
               'utilization_percent', 'power_watts', 'temperature_celsius',
               'sm_clock_mhz', 'memory_clock_mhz')


def timestamp() -> dict:
    epoch = time.time()
    return {'utc_epoch_seconds': epoch,
            'utc': datetime.fromtimestamp(epoch, timezone.utc).isoformat()}


def parse_gpu_line(line: str) -> dict:
    values = next(csv.reader([line], skipinitialspace=True))
    if len(values) != len(GPU_FIELDS):
        raise ValueError('Unexpected nvidia-smi field count')
    result = dict(zip(('index', 'uuid', 'name', 'driver_version'), values[:4]))
    reasons = {}
    for name, raw in zip(GPU_NUMERIC, values[4:]):
        try:
            result[name] = float(raw)
        except ValueError:
            result[name] = None
            reasons[name] = f'nvidia-smi reported {raw}'
    result['null_reasons'] = reasons
    return result


class NvidiaStream:
    """Own only the nvidia-smi child; never control the observed target process."""

    def __init__(self, interval_seconds: float, gpu_index: int = 0):
        self.command = ['nvidia-smi', f'--id={gpu_index}',
                        '--query-gpu=' + ','.join(GPU_FIELDS),
                        '--format=csv,noheader,nounits', '-lms',
                        str(round(interval_seconds * 1000))]
        self.process = None
        self.latest = None
        self.error = 'nvidia-smi has not produced a sample'
        self.intervals = []
        self.reader_cpu_seconds = 0.0
        self.child_cpu_seconds = None
        self.lock = threading.Lock()
        try:
            self.process = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            self.error = f'nvidia-smi launch failed: {exc}'
            self.thread = None
        else:
            self.thread = threading.Thread(target=self._read, daemon=True)
            self.thread.start()

    def _read(self) -> None:
        cpu_start = time.thread_time()
        previous = None
        try:
            for line in self.process.stdout:
                try:
                    reading = parse_gpu_line(line)
                except (ValueError, csv.Error):
                    # Driver notices are not telemetry rows.
                    continue
                observed = timestamp()
                mono = time.perf_counter()
                with self.lock:
                    if previous is not None:
                        self.intervals.append(mono - previous)
                    previous = mono
                    self.latest = {**reading, **observed, 'observed_monotonic': mono}
                    self.error = None
            if self.process.poll() is not None and self.process.returncode:
                with self.lock:
                    self.error = self.process.stderr.read().strip() or f'nvidia-smi exit {self.process.returncode}'
        finally:
            self.reader_cpu_seconds = time.thread_time() - cpu_start

    def sample(self) -> dict:
        with self.lock:
            if self.latest is None:
                return {**{name: None for name in GPU_NUMERIC},
                        'null_reasons': {'gpu': self.error}}
            result = dict(self.latest)
            result['age_seconds'] = time.perf_counter() - result.pop('observed_monotonic')
            if self.error:
                result['stream_error'] = self.error
            return result

    def close(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.child_cpu_seconds = windows_process_cpu(self.process.pid)
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.thread is not None:
                self.thread.join(timeout=5)
            self.process.stdout.close()
            self.process.stderr.close()


class ProcessMemory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]


class MemoryStatus(ctypes.Structure):
    _fields_ = [('dwLength', wintypes.DWORD), ('dwMemoryLoad', wintypes.DWORD)] + [
        (name, ctypes.c_ulonglong) for name in ('ullTotalPhys', 'ullAvailPhys',
        'ullTotalPageFile', 'ullAvailPageFile', 'ullTotalVirtual', 'ullAvailVirtual',
        'ullAvailExtendedVirtual')]


def _kernel():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    return kernel


def windows_process_cpu(pid: int) -> float | None:
    if os.name != 'nt':
        return None
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(v) for v in values]):
            return None
        return sum((v.dwHighDateTime << 32) | v.dwLowDateTime for v in values[2:]) / 1e7
    finally:
        kernel.CloseHandle(handle)


class CounterUnion(ctypes.Union):
    _fields_ = [('longValue', ctypes.c_int32), ('doubleValue', ctypes.c_double),
                ('largeValue', ctypes.c_longlong)]


class CounterValue(ctypes.Structure):
    _fields_ = [('status', wintypes.DWORD), ('value', CounterUnion)]


class CounterItem(ctypes.Structure):
    _fields_ = [('name', wintypes.LPWSTR), ('formatted', CounterValue)]


class WindowsMemoryProbe:
    """Read process working set/private commit, system RAM and WDDM PDH counters."""

    def __init__(self):
        self.query = ctypes.c_void_p()
        self.counters = {}
        self.counter_error = None
        self.creation_times = {}
        if os.name != 'nt':
            self.counter_error = 'Windows memory APIs unavailable on this platform'
            return
        self.kernel = _kernel()
        self.psapi = ctypes.WinDLL('psapi', use_last_error=True)
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
        self.kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
        self.pdh = ctypes.WinDLL('pdh', use_last_error=True)
        self.pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self.pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        try:
            self._check(self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)))
            for name, counter in [('dedicated_gpu_bytes', 'Dedicated Usage'), ('shared_gpu_bytes', 'Shared Usage')]:
                handle = ctypes.c_void_p()
                self._check(self.pdh.PdhAddEnglishCounterW(
                    self.query, f'\\GPU Process Memory(*)\\{counter}', 0, ctypes.byref(handle)))
                self.counters[name] = handle
        except OSError as exc:
            self.counter_error = str(exc)

    @staticmethod
    def _check(status: int) -> None:
        if status:
            raise OSError(f'PDH status 0x{status & 0xffffffff:08x}')

    def _gpu_counters(self, pid: int) -> tuple[dict, dict]:
        data, reasons = {}, {}
        if self.counter_error:
            return data, {name: self.counter_error for name in ('dedicated_gpu_bytes', 'shared_gpu_bytes')}
        try:
            self._check(self.pdh.PdhCollectQueryData(self.query))
            for name, handle in self.counters.items():
                size, count = wintypes.DWORD(), wintypes.DWORD()
                status = self.pdh.PdhGetFormattedCounterArrayW(handle, 0x400, ctypes.byref(size), ctypes.byref(count), None)
                if status & 0xffffffff != 0x800007d2:
                    self._check(status)
                    reasons[name] = 'No GPU process memory instances returned by PDH'
                    continue
                buffer = ctypes.create_string_buffer(size.value)
                self._check(self.pdh.PdhGetFormattedCounterArrayW(
                    handle, 0x400, ctypes.byref(size), ctypes.byref(count), buffer))
                items = ctypes.cast(buffer, ctypes.POINTER(CounterItem))
                matches = [items[i] for i in range(count.value) if items[i].name.startswith(f'pid_{pid}_')]
                valid = [item.formatted.value.largeValue for item in matches if item.formatted.status in (0, 1)]
                if not matches:
                    reasons[name] = 'Target PID has no GPU Process Memory counter instance; absence is not measured zero'
                elif len(valid) != len(matches):
                    reasons[name] = 'One or more target GPU counter instances have invalid PDH status'
                else:
                    data[name] = sum(valid)
        except OSError as exc:
            reasons.update({name: str(exc) for name in ('dedicated_gpu_bytes', 'shared_gpu_bytes')})
        return data, reasons

    def sample(self, pid: int | None) -> dict:
        result = {'pid': pid, 'working_set_bytes': None, 'private_commit_bytes': None,
                  'dedicated_gpu_bytes': None, 'shared_gpu_bytes': None,
                  'system_ram_total_bytes': None, 'system_ram_available_bytes': None,
                  'system_commit_limit_bytes': None, 'system_commit_available_bytes': None,
                  'null_reasons': {}}
        reasons = result['null_reasons']
        if os.name != 'nt':
            reasons.update({key: self.counter_error for key in result if key not in ('pid', 'null_reasons')})
            return result
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if self.kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
            result.update(system_ram_total_bytes=status.ullTotalPhys,
                          system_ram_available_bytes=status.ullAvailPhys,
                          system_commit_limit_bytes=status.ullTotalPageFile,
                          system_commit_available_bytes=status.ullAvailPageFile)
        else:
            reasons['system_memory'] = f'GlobalMemoryStatusEx error {ctypes.get_last_error()}'
        if pid is None:
            reasons.update({name: 'No target PID configured' for name in
                            ('working_set_bytes', 'private_commit_bytes', 'dedicated_gpu_bytes', 'shared_gpu_bytes')})
            return result
        handle = self.kernel.OpenProcess(0x1010, False, pid)
        if not handle:
            reasons.update({name: f'OpenProcess error {ctypes.get_last_error()}; target exited or access denied'
                            for name in ('working_set_bytes', 'private_commit_bytes', 'dedicated_gpu_bytes', 'shared_gpu_bytes')})
            return result
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle, *[ctypes.byref(v) for v in times]):
                raise OSError(f'GetProcessTimes error {ctypes.get_last_error()}')
            creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            if self.creation_times.setdefault(pid, creation) != creation:
                raise OSError('PID was reused; refusing to attribute a different process to the original target')
            result['process_creation_utc_epoch_seconds'] = creation / 1e7 - 11644473600
            memory = ProcessMemory()
            memory.cb = ctypes.sizeof(memory)
            if not self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                raise OSError(f'GetProcessMemoryInfo error {ctypes.get_last_error()}')
            result['working_set_bytes'] = memory.WorkingSetSize
            result['private_commit_bytes'] = memory.PrivateUsage
            data, gpu_reasons = self._gpu_counters(pid)
            result.update(data)
            reasons.update(gpu_reasons)
        except OSError as exc:
            reasons.update({name: str(exc) for name in
                            ('working_set_bytes', 'private_commit_bytes', 'dedicated_gpu_bytes', 'shared_gpu_bytes')})
        finally:
            self.kernel.CloseHandle(handle)
        return result

    def close(self) -> None:
        if os.name == 'nt' and self.query.value:
            self.pdh.PdhCloseQuery(self.query)


def interval_summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {'count': len(values), 'minimum_seconds': min(values, default=None),
            'median_seconds': statistics.median(values) if values else None,
            'p95_seconds': ordered[min(len(ordered) - 1, int(len(ordered) * .95))] if ordered else None,
            'maximum_seconds': max(values, default=None)}


class ResourceMonitor:
    """Use with a context manager, set_target(Popen.pid), then mark_phase()."""

    def __init__(self, output_dir: Path, interval_seconds: float = .25,
                 target_pid: int | None = None, pid_file: Path | None = None,
                 gpu_index: int = 0):
        if not .2 <= interval_seconds <= 1:
            raise ValueError('Sampling interval must be between 0.2 and 1 seconds')
        if target_pid is not None and target_pid <= 0:
            raise ValueError('Target PID must be positive')
        self.output_dir = Path(output_dir)
        self.interval_seconds = interval_seconds
        self.target_pid = target_pid
        self.pid_file = Path(pid_file) if pid_file else None
        self.gpu_index = gpu_index
        self.phase = 'idle'
        self.lock = threading.Lock()
        self.finished = threading.Event()
        self.started = False
        self.summary = None
        self.intervals, self.durations = [], []
        self.sample_count = 0
        self.worker_cpu_seconds = 0.0
        self.peak_used, self.minimum_free = None, None
        self.phase_summaries = {}

    def start(self):
        if self.started:
            raise RuntimeError('Monitor already started')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.samples = (self.output_dir / 'resource-samples.jsonl').open('x', encoding='utf-8')
        try:
            self.events = (self.output_dir / 'resource-events.jsonl').open('x', encoding='utf-8')
        except OSError:
            self.samples.close()
            raise
        self.started = True
        self.started_at = time.perf_counter()
        self.gpu = NvidiaStream(self.interval_seconds, self.gpu_index)
        self.memory = WindowsMemoryProbe()
        self.mark_phase('idle', {'monitor_started': True})
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def set_target(self, pid: int | None) -> None:
        if pid is not None and pid <= 0:
            raise ValueError('Target PID must be positive')
        with self.lock:
            self.target_pid = pid

    def mark_phase(self, name: str, data: dict | None = None) -> None:
        if not self.started or self.finished.is_set():
            raise RuntimeError('Monitor is not running')
        with self.lock:
            self.phase = name
            self.events.write(json.dumps({**timestamp(), 'phase': name,
                                         'target_pid': self.target_pid, 'data': data or {}}, ensure_ascii=False) + '\n')
            self.events.flush()

    def event(self, phase: str, **details) -> None:
        self.mark_phase(phase, details)

    def _run(self) -> None:
        cpu_start = time.thread_time()
        previous = None
        deadline = time.perf_counter()
        try:
            while not self.finished.is_set():
                sample_start = time.perf_counter()
                if previous is not None:
                    self.intervals.append(sample_start - previous)
                previous = sample_start
                pid_error = None
                if self.pid_file:
                    try:
                        raw = self.pid_file.read_text(encoding='utf-8-sig').strip()
                        decoded = json.loads(raw)
                        self.set_target(int(decoded['pid'] if isinstance(decoded, dict) else decoded))
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        self.set_target(None)
                        pid_error = f'PID file unavailable or invalid: {exc}'
                with self.lock:
                    pid, phase = self.target_pid, self.phase
                gpu = self.gpu.sample()
                memory = self.memory.sample(pid)
                if pid_error:
                    memory['null_reasons']['target_pid'] = pid_error
                row = {**timestamp(), 'elapsed_seconds': sample_start - self.started_at,
                       'phase': phase, 'gpu': gpu, 'memory': memory}
                row['probe_work_seconds'] = time.perf_counter() - sample_start
                self.samples.write(json.dumps(row, ensure_ascii=False) + '\n')
                self.samples.flush()
                self.durations.append(time.perf_counter() - sample_start)
                self.sample_count += 1
                phase_summary = self.phase_summaries.setdefault(
                    phase, {'sample_count': 0, 'peak_device_memory_mib': None,
                            'minimum_device_free_mib': None})
                phase_summary['sample_count'] += 1
                if gpu.get('age_seconds', float('inf')) <= self.interval_seconds * 3:
                    used, free = gpu.get('memory_used_mib'), gpu.get('memory_free_mib')
                    if used is not None:
                        self.peak_used = max(used, self.peak_used or used)
                        phase_summary['peak_device_memory_mib'] = max(
                            used, phase_summary['peak_device_memory_mib'] or used)
                    if free is not None:
                        self.minimum_free = min(free, free if self.minimum_free is None else self.minimum_free)
                        phase_free = phase_summary['minimum_device_free_mib']
                        phase_summary['minimum_device_free_mib'] = min(free, free if phase_free is None else phase_free)
                deadline += self.interval_seconds
                if deadline < time.perf_counter():
                    deadline = time.perf_counter()
                self.finished.wait(max(0, deadline - time.perf_counter()))
        except Exception as exc:
            self.worker_error = repr(exc)
        finally:
            self.worker_cpu_seconds = time.thread_time() - cpu_start

    def stop(self) -> dict:
        if self.summary is not None:
            return self.summary
        if not self.started:
            raise RuntimeError('Monitor has not started')
        self.finished.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError('Monitor worker did not stop')
        self.gpu.close()
        self.memory.close()
        self.samples.close()
        self.events.close()
        self.summary = {**timestamp(), 'requested_interval_seconds': self.interval_seconds,
                        'sample_count': self.sample_count, 'sample_intervals': interval_summary(self.intervals),
                        'gpu_stream_intervals': interval_summary(self.gpu.intervals),
                        'sampling_work': interval_summary(self.durations),
                        'monitor_worker_cpu_seconds': self.worker_cpu_seconds,
                        'gpu_reader_cpu_seconds': self.gpu.reader_cpu_seconds,
                        'nvidia_smi_process_cpu_seconds': self.gpu.child_cpu_seconds,
                        'wall_seconds': time.perf_counter() - self.started_at,
                        'peak_device_memory_mib': self.peak_used, 'minimum_device_free_mib': self.minimum_free,
                        'phase_summaries': self.phase_summaries,
                        'worker_error': getattr(self, 'worker_error', None),
                        'gpu_command': self.gpu.command,
                        'host': {'platform': platform.platform(), 'processor': platform.processor(),
                                 'logical_cpu_count': os.cpu_count(), 'monitor_pid': os.getpid()},
                        'sampling_work_scope': 'Includes probe calls, JSON serialization and file flush; excludes scheduled waiting',
                        'peak_scope': 'Whole-device sampled peak; not model-exclusive or absolute peak',
                        'timestamp_scope': 'UTC epoch at observation; GPU receive time is separate from resource sample time',
                        'limitations': ['Sub-interval peaks may be missed',
                                        'WDDM PDH PID counters aggregate adapters and instances; they are not physical residency proof',
                                        'Target memory uses explicit PID or PID file; no process discovery or target termination',
                                        'Thread/process CPU accounting has OS timer resolution; zero does not imply zero overhead',
                                        'nvidia-smi GPU stream and memory sampling are asynchronous; inspect GPU sample age']}
        (self.output_dir / 'resource-summary.json').write_text(json.dumps(self.summary, indent=2), encoding='utf-8')
        return self.summary

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description='本地翻译资源监测；不启动模型、不停止目标进程')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=.25)
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--pid-file', type=Path)
    parser.add_argument('--gpu-index', type=int, default=0)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error('--duration must be positive')
    with ResourceMonitor(args.output_dir, args.interval, args.pid, args.pid_file, args.gpu_index) as monitor:
        try:
            monitor.finished.wait(args.duration)
        except KeyboardInterrupt:
            monitor.mark_phase('interrupted')
    print(json.dumps(monitor.summary, ensure_ascii=False))
    return 1 if monitor.summary['worker_error'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

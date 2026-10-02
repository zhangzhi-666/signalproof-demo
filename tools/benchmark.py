"""Reproducible native benchmark with frozen labels and per-request isolation timeout.

Run from the repository root:
  python tools/benchmark.py --repeats 3 --output docs/benchmark-results.json

The worker stays alive between requests. Imports and four domain warm-ups are excluded.
latencyMs measures verify() itself, including parsing, reasoning, and result rendering,
but excludes IPC, process start, imports, warm-up, browser/WASM load and network time.
callerLatencyMs is additionally reported, including IPC and expired timeout waits.
Labels are loaded from files, never obtained or updated from actual answers.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker_main(connection):
    """Only the subprocess imports the measured engine; parent remains able to time out."""
    sys.path.insert(0, str(ROOT))
    started = time.perf_counter()
    try:
        from engine import service
        import sympy
    except Exception as exc:
        connection.send({'type': 'fatal', 'error': 'Engine import failed: ' + type(exc).__name__})
        return
    import_ms = (time.perf_counter() - started) * 1000
    warm_start = time.perf_counter()
    warmups = [(['Conv(x(t),delta(t),t)', 'x(t)'], {}),
               (['FT(x(t-1),t,w)', 'exp(-I*w)*X(w)'], {}),
               (['LT(u(t),t,s)', '1/s; ROC: re(s)>0'], {}),
               (['ZT(delta(n),n,z)', '1'], {})]
    try:
        for steps, context in warmups:
            service.verify(steps, context)
    except Exception as exc:
        connection.send({'type': 'fatal', 'error': 'Warm-up failed: ' + type(exc).__name__})
        return
    connection.send({'type': 'ready', 'sympy': sympy.__version__,
                     'importMs': round(import_ms, 4),
                     'warmupMs': round((time.perf_counter() - warm_start) * 1000, 4),
                     'warmupRequests': len(warmups)})
    while True:
        try:
            item = connection.recv()
        except EOFError:
            return
        if item is None:
            return
        begin = time.perf_counter()
        try:
            result = service.verify(item['steps'], item.get('context', {}))
            payload = {'actual': result['status'], 'actualFirstError': result['firstError'],
                       'actualLocalStatuses': [s.get('localStatus', s['status']) for s in result['steps']],
                       'firstErrorCertain': result.get('firstErrorCertain'),
                       'error': '', 'inputRejected': False}
        except Exception as exc:
            # Input rejection is a separate evaluation outcome, not mathematical unknown.
            is_input = isinstance(exc, service.InputError)
            payload = {'actual': 'input_error' if is_input else 'error', 'actualFirstError': None,
                       'actualLocalStatuses': [], 'firstErrorCertain': None,
                       'error': type(exc).__name__ + (': ' + str(exc) if is_input else ''),
                       'inputRejected': is_input}
        payload['latencyMs'] = round((time.perf_counter() - begin) * 1000, 4)
        connection.send(payload)


class IsolatedWorker:
    def __init__(self, timeout, startup_timeout):
        self.timeout, self.startup_timeout = timeout, startup_timeout
        self.context = mp.get_context('spawn')
        self.process, self.pipe = None, None
        self.startups = []
        self.restarts = 0
        self.sympy = None

    def stop(self):
        if self.pipe is not None:
            self.pipe.close()
            self.pipe = None
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=5)
            self.process.close()
            self.process = None

    def start(self):
        parent, child = self.context.Pipe()
        self.pipe = parent
        self.process = self.context.Process(target=worker_main, args=(child,), daemon=True)
        begin = time.perf_counter()
        self.process.start()
        child.close()
        if not parent.poll(self.startup_timeout):
            self.stop()
            raise RuntimeError('Engine worker startup timed out; no accuracy report was fabricated.')
        message = parent.recv()
        if message.get('type') != 'ready':
            self.stop()
            raise RuntimeError(message.get('error', 'Worker failed to initialize.'))
        message.pop('type', None)
        message['totalStartupMs'] = round((time.perf_counter() - begin) * 1000, 4)
        self.startups.append(message)
        self.sympy = message['sympy']

    def run(self, case):
        if self.process is None:
            self.start()
        begin = time.perf_counter()
        try:
            self.pipe.send({'steps': case['steps'], 'context': case.get('context', {})})
            if self.pipe.poll(self.timeout):
                response = self.pipe.recv()
                response['timedOut'] = False
            else:
                response = {'actual': 'timeout', 'actualFirstError': None, 'actualLocalStatuses': [],
                            'firstErrorCertain': None, 'latencyMs': None, 'timedOut': True,
                            'inputRejected': False, 'error': 'Per-case timeout exceeded.'}
                self.restarts += 1
                self.stop()
        except (EOFError, OSError, BrokenPipeError):
            response = {'actual': 'error', 'actualFirstError': None, 'actualLocalStatuses': [],
                        'firstErrorCertain': None, 'latencyMs': None, 'timedOut': False,
                        'inputRejected': False, 'error': 'Worker exited without a completed result.'}
            self.restarts += 1
            self.stop()
        response['callerLatencyMs'] = round((time.perf_counter() - begin) * 1000, 4)
        return response


def ratio(correct, total):
    return {'correct': correct, 'total': total, 'rate': correct / total if total else None}


def latency(values):
    values = sorted(v for v in values if v is not None)
    def quantile(p):
        if not values:
            return None
        index = (len(values)-1)*p
        low = int(index)
        return round(values[low] + (values[min(low+1, len(values)-1)]-values[low])*(index-low), 4)
    return {'count': len(values), 'mean': round(statistics.mean(values), 4) if values else None,
            'p50': quantile(.5), 'p95': quantile(.95),
            'min': values[0] if values else None, 'max': values[-1] if values else None}


def summarize(rows):
    step_confusion, chain_confusion = defaultdict(Counter), defaultdict(Counter)
    steps = step_correct = chain_correct = first_wrong_correct = first_wrong_total = 0
    first_all_correct = exact = 0
    for row in rows:
        wanted, got = row['expected'], row['actual']
        chain_confusion[wanted][got] += 1
        chain_correct += wanted == got
        completed = got not in ('error', 'input_error', 'timeout')
        first_match = completed and row['expectedFirstError'] == row['actualFirstError']
        # End-to-end localization also requires the intended chain verdict;
        # an unknown answer with null location is not a proved correct chain.
        first_all_correct += first_match and wanted == got
        if wanted == 'wrong':
            first_wrong_total += 1
            first_wrong_correct += first_match and got == 'wrong'
        locals_actual = row['actualLocalStatuses']
        for index, expected in enumerate(row['expectedLocalStatuses']):
            actual = locals_actual[index] if index < len(locals_actual) else got if not completed else 'missing'
            step_confusion[expected][actual] += 1
            steps += 1
            step_correct += expected == actual
        exact += row['passed']
    metrics = {'stepAccuracy': ratio(step_correct, steps),
               'chainAccuracy': ratio(chain_correct, len(rows)),
               'firstErrorOnWrong': ratio(first_wrong_correct, first_wrong_total),
               'firstErrorIncludingNone': ratio(first_all_correct, len(rows)),
               'exactCaseAccuracy': ratio(exact, len(rows))}
    return {'metrics': metrics, 'latencyMs': latency([r['latencyMs'] for r in rows]),
            'callerLatencyMs': latency([r['callerLatencyMs'] for r in rows]),
            'decisionCoverage': ratio(sum(r['actual'] in ('correct', 'wrong') for r in rows), len(rows)),
            'outcomeCounts': dict(Counter(r['actual'] for r in rows)),
            'timedOutCount': sum(r['timedOut'] for r in rows),
            'latencyMissingCount': sum(r['latencyMs'] is None for r in rows),
            'confusion': {'step': {k: dict(v) for k, v in sorted(step_confusion.items())},
                          'chain': {k: dict(v) for k, v in sorted(chain_confusion.items())}}}


def suite_report(rows, cases, repeats):
    aggregate = summarize(rows)
    firsts = {}
    signatures = defaultdict(set)
    for row in rows:
        firsts.setdefault(row['id'], row)
        signatures[row['id']].add((row['actual'], row['actualFirstError'], tuple(row['actualLocalStatuses'])))
    aggregate.update({'cases': len(cases), 'steps': sum(len(c['steps'])-1 for c in cases),
                      'repeats': repeats, 'uniqueMetrics': summarize(list(firsts.values()))['metrics'],
                      'inconsistentCaseIds': [key for key, values in signatures.items() if len(values) > 1],
                      'byDomain': {category: summarize([r for r in rows if r['category'] == category])
                                   for category in sorted({r['category'] for r in rows})},
                      'failures': [r for r in rows if not r['passed']], 'rows': rows})
    return aggregate


def load_datasets():
    data_path = ROOT/'data/tests.json'
    oracle_path = ROOT/'data/step-oracles.json'
    oracle = read_json(oracle_path)
    if oracle['datasetSha256'] != sha(data_path):
        raise ValueError('Baseline hash differs from reviewed oracle; review data instead of regenerating expected labels.')
    labels = {c['id']: c for c in oracle['cases']}
    baseline = read_json(data_path)
    if {c['id'] for c in baseline} != set(labels) or len(labels) != len(baseline):
        raise ValueError('Baseline IDs do not exactly match the independent step oracle.')
    for case in baseline:
        case['expectedLocalStatuses'] = labels[case['id']]['expectedLocalStatuses']
    holdout = read_json(ROOT/'data/holdout.json')['cases']
    for group in (baseline, holdout):
        if len({c['id'] for c in group}) != len(group):
            raise ValueError('Duplicate case IDs.')
        for case in group:
            if len(case['expectedLocalStatuses']) != len(case['steps'])-1:
                raise ValueError('Incomplete adjacent-step labels for ' + case['id'])
    return {'baseline': baseline, 'holdout': holdout}


def write_reports(output, report):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    fields = ['suite', 'id', 'category', 'repeat', 'expected', 'actual', 'expectedFirstError',
              'actualFirstError', 'expectedLocalStatuses', 'actualLocalStatuses', 'latencyMs',
              'callerLatencyMs', 'passed', 'timedOut', 'inputRejected', 'error']
    with output.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for name, suite in report['suites'].items():
            for row in suite['rows']:
                value = dict(row, suite=name)
                for field in ('expectedLocalStatuses', 'actualLocalStatuses'):
                    value[field] = '|'.join(value[field])
                writer.writerow(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, default=Path('docs/benchmark-results.json'))
    parser.add_argument('--timeout', type=float, default=20, help='Verification timeout per case in seconds (excludes worker startup).')
    parser.add_argument('--startup-timeout', type=float, default=60)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100 or args.timeout <= 0 or args.startup_timeout <= 0:
        parser.error('Use 1–100 repeats and positive timeouts.')
    datasets = load_datasets()
    engine_files = sorted((ROOT/'engine').glob('*.py'))
    file_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in engine_files}
    digest = hashlib.sha256(json.dumps(file_hashes, sort_keys=True).encode()).hexdigest()
    report = {'schemaVersion': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
              'protocol': {'execution': 'Native Python, persistent isolated worker, serial requests.',
                           'repeats': args.repeats, 'timeoutSeconds': args.timeout, 'warmupExcluded': True,
                           'coldStartIncluded': False, 'browserLoadIncluded': False,
                           'latencyDefinition': 'perf_counter around verify(), including parse/proof/result generation; excluding IPC, startup, imports, four warm-up requests, browser/WASM load and network. Timeout cases have null kernel latency and explicit failure rows; caller latency includes their timeout wait.',
                           'percentiles': 'Linear interpolation at (N-1)*p; milliseconds.',
                           'accuracyAggregation': 'metrics pools all measured repetitions; uniqueMetrics uses first observation per ID; inconsistentCaseIds records nondeterminism.',
                           'localizationDefinition': 'firstErrorOnWrong requires a wrong verdict and exact 1-based destination line on expected-wrong chains. firstErrorIncludingNone requires both the expected chain verdict and exact location, including null; unknown/timeout cannot masquerade as a proved correct chain.',
                           'caseOrder': 'Original fixed order; per-round rotation of one third of each suite to reduce fixed-position effects.',
                           'oracleProvenance': 'AI-assisted, independently mathematically checked labels fixed before execution; no external human certification and no blind evaluation. Supplementary cases are reported separately; results do not establish generalization.'},
              'environment': {'python': platform.python_version(), 'implementation': platform.python_implementation(),
                              'sympy': None, 'os': platform.system(), 'osRelease': platform.release(),
                              'machine': platform.machine(), 'cpu': platform.processor(), 'logicalCpus': os.cpu_count()},
              'source': {'sha256': digest, 'files': file_hashes, 'benchmarkSha256': sha(Path(__file__))},
              'datasets': {'baseline': {'path': 'data/tests.json', 'sha256': sha(ROOT/'data/tests.json'),
                                        'oracleSha256': sha(ROOT/'data/step-oracles.json')},
                           'holdout': {'path': 'data/holdout.json', 'sha256': sha(ROOT/'data/holdout.json')}},
              'suites': {}, 'worker': {}}
    worker = IsolatedWorker(args.timeout, args.startup_timeout)
    try:
        for name, cases in datasets.items():
            rows = []
            for repeat in range(1, args.repeats+1):
                offset = ((repeat-1)*max(1, len(cases)//3)) % len(cases)
                ordered = cases[offset:] + cases[:offset]
                for case in ordered:
                    actual = worker.run(case)
                    row = {'id': case['id'], 'category': case['category'], 'repeat': repeat,
                           'expected': case['expected'], 'expectedFirstError': case['expectedFirstError'],
                           'expectedLocalStatuses': case['expectedLocalStatuses'], **actual}
                    row['passed'] = (row['expected'] == row['actual'] and
                                     row['expectedFirstError'] == row['actualFirstError'] and
                                     row['expectedLocalStatuses'] == row['actualLocalStatuses'])
                    rows.append(row)
                print(f'{name}: completed round {repeat}/{args.repeats}', flush=True)
            report['suites'][name] = suite_report(rows, cases, args.repeats)
    finally:
        worker.stop()
    report['environment']['sympy'] = worker.sympy
    report['worker'] = {'restarts': worker.restarts, 'startups': worker.startups}
    # Source mutation during a run invalidates a reproducibility claim.
    final_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT/'engine').glob('*.py'))}
    report['source']['unchangedDuringRun'] = final_hashes == file_hashes
    if final_hashes != file_hashes:
        report['source']['finalFiles'] = final_hashes
    write_reports(args.output, report)
    for name, suite in report['suites'].items():
        metric = suite['uniqueMetrics']
        step, first = metric['stepAccuracy'], metric['firstErrorOnWrong']
        print(f"{name}: steps {step['correct']}/{step['total']}; first error on wrong chains {first['correct']}/{first['total']}; mean {suite['latencyMs']['mean']} ms; failures {len(suite['failures'])}")
    return 1 if any(s['failures'] for s in report['suites'].values()) or not report['source']['unchangedDuringRun'] else 0


if __name__ == '__main__':
    mp.freeze_support()
    raise SystemExit(main())

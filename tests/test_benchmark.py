"""Checks that reported accuracy/latency do not hide errors or change denominators."""
import unittest
from tools.benchmark import latency, summarize, suite_report


class BenchmarkAccountingTests(unittest.TestCase):
    def test_percentiles_are_interpolated_and_missing_times_are_not_zero(self):
        got = latency([10, 20, 30, 40, None])
        self.assertEqual(got, {'count': 4, 'mean': 25, 'p50': 25, 'p95': 38.5, 'min': 10, 'max': 40})

    def test_unknown_timeout_and_none_location_are_not_false_successes(self):
        rows = [
            {'id': 'a', 'category': 'A', 'repeat': 1, 'expected': 'wrong', 'actual': 'wrong',
             'expectedFirstError': 3, 'actualFirstError': 3,
             'expectedLocalStatuses': ['correct', 'wrong'], 'actualLocalStatuses': ['correct', 'wrong'],
             'latencyMs': 10, 'callerLatencyMs': 12, 'timedOut': False, 'passed': True},
            {'id': 'b', 'category': 'A', 'repeat': 1, 'expected': 'correct', 'actual': 'unknown',
             'expectedFirstError': None, 'actualFirstError': None,
             'expectedLocalStatuses': ['correct'], 'actualLocalStatuses': ['unknown'],
             'latencyMs': 20, 'callerLatencyMs': 22, 'timedOut': False, 'passed': False},
            {'id': 'c', 'category': 'B', 'repeat': 1, 'expected': 'correct', 'actual': 'timeout',
             'expectedFirstError': None, 'actualFirstError': None,
             'expectedLocalStatuses': ['correct'], 'actualLocalStatuses': [],
             'latencyMs': None, 'callerLatencyMs': 1000, 'timedOut': True, 'passed': False}]
        got = summarize(rows)
        self.assertEqual(got['metrics']['stepAccuracy']['correct'], 2)
        self.assertEqual(got['metrics']['stepAccuracy']['total'], 4)
        self.assertEqual(got['metrics']['chainAccuracy']['rate'], 1/3)
        self.assertEqual(got['metrics']['firstErrorOnWrong']['rate'], 1)
        # Returning None with an unknown or timed-out verdict must not count as
        # successful end-to-end localization of a known correct chain.
        self.assertEqual(got['metrics']['firstErrorIncludingNone']['correct'], 1)
        self.assertEqual(got['metrics']['exactCaseAccuracy']['rate'], 1/3)
        self.assertEqual(got['confusion']['step']['correct']['timeout'], 1)
        self.assertEqual(got['latencyMs']['count'], 2)
        self.assertEqual(got['latencyMs']['mean'], 15)
        self.assertEqual(got['callerLatencyMs']['count'], 3)
        self.assertEqual(got['timedOutCount'], 1)

    def test_repeated_runs_do_not_inflate_unique_dataset_size(self):
        good = {'id': 'a', 'category': 'A', 'repeat': 1, 'expected': 'correct', 'actual': 'correct',
                'expectedFirstError': None, 'actualFirstError': None,
                'expectedLocalStatuses': ['correct'], 'actualLocalStatuses': ['correct'],
                'latencyMs': 10, 'callerLatencyMs': 12, 'timedOut': False, 'passed': True}
        bad = dict(good, repeat=2, actual='unknown', actualLocalStatuses=['unknown'], passed=False)
        got = suite_report([good, bad], [{'steps': ['1', '1']}], 2)
        self.assertEqual(got['cases'], 1)
        self.assertEqual(got['metrics']['chainAccuracy']['total'], 2)
        self.assertEqual(got['uniqueMetrics']['chainAccuracy']['total'], 1)
        self.assertEqual(got['inconsistentCaseIds'], ['a'])
        self.assertEqual(len(got['failures']), 1)


if __name__ == '__main__':
    unittest.main()

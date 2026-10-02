"""Prevent publishing measurements against changed source or hidden ROC."""
import copy
import json
import unittest
from tools import generate_report as report


class ReportIntegrityTests(unittest.TestCase):
    def test_measurements_are_bound_to_current_source_and_inputs(self):
        data = json.loads((report.ROOT/'docs/benchmark-results.json').read_text(encoding='utf-8'))
        report.validate_measurement(data)
        for relative in data['source']['files']:
            changed = copy.deepcopy(data)
            changed['source']['files'][relative] = '0' * 64
            with self.subTest(path=relative), self.assertRaises(ValueError):
                report.validate_measurement(changed)
        changed = copy.deepcopy(data)
        changed['datasets']['baseline']['oracleSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            report.validate_measurement(changed)

    def test_report_keeps_roc_and_does_not_fake_missing_latency(self):
        fixtures = json.loads((report.ROOT/'data/tests.json').read_text(encoding='utf-8-sig'))
        markup = report.case_examples(fixtures)
        self.assertIn('ROC', markup)
        self.assertIn('Z09-ERR', markup)
        self.assertNotEqual(report.timing(None), '0.000')

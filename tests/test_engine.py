"""Independent mathematical and safety regressions. Run: python -m unittest discover -s tests -v"""
from pathlib import Path
import hashlib
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import service


def load(name):
    return json.loads((ROOT / 'data' / name).read_text(encoding='utf-8-sig'))


class ParserSafetyTests(unittest.TestCase):
    def test_rejects_executable_python_and_nonmath_constructs(self):
        rejected = ["__import__('os').system('echo unsafe')", "open('blocked.txt','w')",
                    'x(t).__class__', 'x[0]', '(lambda t:t)(1)', '[t for t in (1,2)]',
                    'mystery(t)', 'True', '{1:2}', 't if a else s', 'sin(t, t)',
                    'FT(x(t),t,s)', 'ZT(x(n),t,z)', 'D(x(t),t,3)', '1/0', 't^17']
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(service.InputError):
                service.parse(value)

    def test_rejects_identically_zero_denominator(self):
        with self.assertRaises(service.InputError):
            service.parse('1/(a-a)')

    def test_input_limits_reject_before_heavy_evaluation(self):
        for value in ('', 't+' * 700 + 't', '9' * 500):
            with self.subTest(length=len(value)), self.assertRaises(service.InputError):
                service.parse(value)

    def test_safe_unicode_math_and_explicit_operators(self):
        result = service.verify(['2×t^2 − 1', '2*t*t-1'])
        self.assertEqual(result['status'], 'correct')
        self.assertEqual(service.verify(['sin(π*t)', 'sin(pi*t)'])['status'], 'correct')

    def test_context_values_are_typed_and_finite(self):
        invalid = [{'causal': 'false'}, {'initial': {'x0': float('nan')}},
                   {'initial': {'x0': float('inf')}}, {'initial': {'x0': '__import__("os")'}},
                   {'definitions': {'X(w)': '__import__("os")'}}]
        for context in invalid:
            with self.subTest(context=context), self.assertRaises(service.InputError):
                service.verify(['X(w)', '1'], context)


class MathematicalRegressionTests(unittest.TestCase):
    def assertVerdict(self, steps, expected, context=None, first=None, local=None):
        result = service.verify(steps, context or {})
        self.assertEqual(result['status'], expected, result['summary'])
        self.assertEqual(result['firstError'], first)
        if local is not None:
            self.assertEqual([row['localStatus'] for row in result['steps']], local)
        return result

    def test_substitution_respects_transform_variable(self):
        context = {'definitions': {'X(w)': '1/(1+I*w)', 'X(s)': '2/(s+2)'}}
        self.assertVerdict(['LT(x(t),t,s)', '2/(s+2)'], 'correct', context)
        self.assertVerdict(['X(w-3)', '1/(1+I*(w-3))'], 'correct', context)

    def test_constant_argument_uses_the_unique_declared_spectrum(self):
        context = {'definitions': {'X(w)': 'exp(-w^2)'}}
        self.assertVerdict(['X(0)', '1'], 'correct', context)
        self.assertVerdict(['FT(x(t),t,w)', 'X(w)+X(0)-1'], 'correct', context)

    def test_cross_domain_witness_must_respect_known_transform(self):
        # These equalities hold for exp(-t)u(t). The bounded engine need not infer
        # cross-domain transforms, but cannot refute them with an unrelated signal.
        pairs = [(['LT(x(t),t,s)', '1/(s+1)'], {'X(w)': '1/(1+I*w)'}),
                 (['FT(x(t),t,w)', '1/(1+I*w)'], {'X(s)': '1/(s+1)'})]
        for steps, definitions in pairs:
            with self.subTest(steps=steps):
                result = service.verify(steps, {'definitions': definitions, 'causal': True})
                self.assertIn(result['status'], ('correct', 'unknown'))
                self.assertIsNone(result['firstError'])

    def test_declared_spectrum_is_substituted_before_differentiation(self):
        self.assertVerdict(['z*D(X(z),z)', '-z/(2*(z-1/2)^2)'], 'correct',
                          {'definitions': {'X(z)': 'z/(z-1/2)'}})
        self.assertVerdict(['LT(t*x(t),t,s)', '-D(X(s),s)', '3/(s+3)^2'], 'correct',
                          {'definitions': {'X(s)': '3/(s+3)'}}, local=['correct', 'correct'])

    def test_negative_initial_value_and_later_substitution_error(self):
        result = self.assertVerdict(['LT(D(h(t),t,2),t,s)', 's^2*H(s)-s*h0-h1',
                                    's^2*H(s)+3*s+4'], 'wrong',
                                   {'initial': {'h0': -3, 'h1': 4}}, first=3,
                                   local=['correct', 'wrong'])
        self.assertTrue(result['firstErrorCertain'])

    def test_unproven_prefix_does_not_become_proved_by_later_error(self):
        result = self.assertVerdict(['a/a', '1', '2', '1+1'], 'wrong', first=3,
                                   local=['unknown', 'wrong', 'correct'])
        self.assertFalse(result['firstErrorCertain'])
        self.assertTrue(result['steps'][-1]['inherited'])

    def test_known_wrong_prefix_preserves_locally_correct_suffix(self):
        result = self.assertVerdict(['Conv(Conv(x(t),delta(t-4),t),delta(t+1),t)',
                                    'Conv(x(t+4),delta(t+1),t)', 'x(t+5)'],
                                   'wrong', first=2, local=['wrong', 'correct'])
        self.assertTrue(result['steps'][1]['inherited'])
        self.assertFalse(result['steps'][0]['inherited'])

    def test_missing_conditions_are_not_invented(self):
        steps = ['FT(exp(-a*t)*u(t),t,w)', '1/(a+I*w)']
        self.assertVerdict(steps, 'unknown')
        self.assertVerdict(steps, 'correct', {'positive': ['a']})
        self.assertVerdict(['LT(D(x(t),t),t,s)', 's*X(s)'], 'unknown')
        self.assertVerdict(['LT(x(t-4),t,s)', 'exp(-4*s)*X(s)'], 'unknown')

    def test_domain_restriction_applies_to_rule_matches_too(self):
        steps = ['FT(x(t),t,w)', 'X(w)*a/a']
        self.assertVerdict(steps, 'unknown')
        self.assertVerdict(steps, 'correct', {'nonzero': ['a']})
        self.assertVerdict(['a/a', '1'], 'unknown')

    def test_complex_time_shift_is_not_a_real_signal_shift(self):
        self.assertVerdict(['Conv(x(t),delta(t-I),t)', 'x(t-I)'], 'unknown')
        self.assertVerdict(['FT(delta(t-I),t,w)', 'exp(w)'], 'unknown')

    def test_roc_missing_wrong_and_preserved_are_distinct(self):
        first = 'ZT((1/4)^n*u(n),n,z)'
        self.assertVerdict([first, 'z/(z-1/4)'], 'incomplete')
        self.assertVerdict([first, 'z/(z-1/4); ROC: abs(z)>=1/4'], 'wrong', first=2)
        self.assertVerdict([first, 'z/(z-1/4); ROC: abs(z)>1/4',
                           '4*z/(4*z-1); ROC: abs(z)>1/4'], 'correct')
        self.assertVerdict(['z/(z-1/4); ROC: abs(z)>1/4', '4*z/(4*z-1)'], 'incomplete')

    def test_omitted_roc_cannot_be_reintroduced_in_the_opposite_direction(self):
        result = self.assertVerdict(['LT(exp(-2*t)*u(t),t,s)', '1/(s+2)',
                                    '1/(s+2); ROC: re(s)<-2'], 'wrong', first=3,
                                   local=['incomplete', 'wrong'])
        self.assertFalse(result['firstErrorCertain'])

    def test_an_unproved_added_roc_does_not_receive_a_correct_verdict(self):
        self.assertVerdict(['ZT(delta(n),n,z)', '1; ROC: abs(z)>1'], 'unknown')

    def test_complex_exponential_roc_uses_real_part_of_decay(self):
        self.assertVerdict(['LT(exp(-I*t)*u(t),t,s)', '1/(s+I); ROC: re(s)>0'], 'correct')
        self.assertVerdict(['LT(exp(-(2+I)*t)*u(t),t,s)',
                           '1/(s+2+I); ROC: re(s)>-2'], 'correct')

    def test_nonreal_roc_threshold_is_rejected(self):
        with self.assertRaises(service.InputError):
            service.verify(['LT(exp(-I*t)*u(t),t,s)', '1/(s+I); ROC: re(s)>-I'])
        with self.assertRaises(service.InputError):
            service.verify(['ZT(delta(n),n,z)', '1; ROC: abs(z)<-1'])

    def test_counterexamples_obey_positive_and_causal_assumptions(self):
        # Refutation outside the declared domain is unsound even if proof support
        # remains incomplete; these are non-refutation safety checks, not accuracy labels.
        for steps, context in [(['abs(z+I)^2', 'z^2+1'], {'positive': ['z']}),
                               (['x(-1)', '0'], {'causal': True})]:
            with self.subTest(steps=steps):
                result = service.verify(steps, context)
                self.assertIn(result['status'], ('correct', 'unknown'))
                self.assertIsNone(result['firstError'])

    def test_sampling_agreement_is_not_a_proof(self):
        self.assertVerdict(['t*(t-1)*(t+1)*(t-2)*(t+2)', '0'], 'wrong', first=2)
        self.assertVerdict(['FT(Int0(x(t),t),t,w)', 'X(w)/(I*w)'], 'unknown')


class FixedDatasetTests(unittest.TestCase):
    def test_original_oracle_is_bound_to_unchanged_dataset(self):
        data = load('tests.json')
        oracle = load('step-oracles.json')
        self.assertEqual(hashlib.sha256((ROOT/'data/tests.json').read_bytes()).hexdigest(), oracle['datasetSha256'])
        self.assertEqual(len(data), 100)
        self.assertEqual(sum(c['expected'] == 'correct' for c in data), 50)
        self.assertEqual(sum(c['expected'] == 'wrong' for c in data), 50)
        labels = {c['id']: c for c in oracle['cases']}
        self.assertEqual(len(labels), 100)
        self.assertEqual(set(labels), {c['id'] for c in data})
        self.assertEqual(sum(len(c['steps']) - 1 for c in data), 110)
        for case in data:
            with self.subTest(id=case['id']):
                local = labels[case['id']]['expectedLocalStatuses']
                self.assertEqual(len(local), len(case['steps'])-1)
                self.assertEqual(len(local), len(labels[case['id']]['rationales']))
                first = next((i+2 for i, state in enumerate(local) if state == 'wrong'), None)
                self.assertEqual(first, case['expectedFirstError'])

    def test_baseline_chain_and_independent_step_labels(self):
        labels = {c['id']: c['expectedLocalStatuses'] for c in load('step-oracles.json')['cases']}
        for case in load('tests.json'):
            with self.subTest(id=case['id']):
                actual = service.verify(case['steps'], case.get('context', {}))
                self.assertEqual(actual['status'], case['expected'])
                self.assertEqual(actual['firstError'], case['expectedFirstError'])
                self.assertEqual([s['localStatus'] for s in actual['steps']], labels[case['id']])

    def test_supplementary_composition_and_boundary_set(self):
        cases = load('holdout.json')['cases']
        self.assertEqual(len(cases), 32)
        self.assertEqual(len({c['id'] for c in cases}), 32)
        for case in cases:
            with self.subTest(id=case['id']):
                result = service.verify(case['steps'], case.get('context', {}))
                self.assertEqual(result['status'], case['expected'])
                self.assertEqual(result['firstError'], case['expectedFirstError'])
                self.assertEqual([r['localStatus'] for r in result['steps']], case['expectedLocalStatuses'])

    def test_existing_adversarial_contract(self):
        for case in load('adversarial.json'):
            with self.subTest(id=case['id']):
                if case['id'] == 'A02':
                    # Context parameter declarations are now restricted to variable
                    # names: literal I is rejected, not reported as a math verdict.
                    with self.assertRaises(service.InputError):
                        service.verify(case['steps'], case.get('context', {}))
                    continue
                actual = service.verify(case['steps'], case.get('context', {}))
                self.assertEqual(actual['status'], case['expected'])
                self.assertEqual(actual['firstError'], case['expectedFirstError'])

    def test_teaching_examples_have_realistic_coverage_and_expected_verdicts(self):
        cases = load('examples.json')
        self.assertEqual(len(cases), 24)
        self.assertEqual(len({c['id'] for c in cases}), 24)
        for category in ('卷积', '傅里叶', '拉普拉斯', 'Z变换'):
            self.assertEqual(sum(c['category'] == category for c in cases), 6)
        for case in cases:
            with self.subTest(id=case['id']):
                for field in ('task', 'concept', 'pitfall', 'hint', 'takeaway'):
                    self.assertTrue(case.get(field))
                actual = service.verify(case['steps'], case.get('context', {}))
                self.assertEqual(actual['status'], case['expected'])
                self.assertEqual(actual['firstError'], case['expectedFirstError'])


if __name__ == '__main__':
    unittest.main()

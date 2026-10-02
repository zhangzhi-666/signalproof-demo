# Project working agreement

The user requires a self-review and corrective iteration before each delivery.

- Compare the change against the course requirements in README.md.
- Reproduce substantive defects, establish an independent mathematical expectation,
  then make the smallest coherent fix and run the relevant regression checks.
- Record findings, changes, evidence, and remaining limits in docs/review-record.json.
  Do not invent a teacher's score or equate fixed-set accuracy with general correctness.
- Keep the parser, rules, diagnostics, verification, formatting, and API responsibilities
  separate. Never execute user expressions with eval or unrestricted parsing.
- Numerical agreement is not proof. Counterexamples must respect declared assumptions,
  transform pairs, and domains. Preserve unknown and incomplete outcomes.
- Do not alter test labels to make failures pass. Explain any justified oracle correction.
- Use the pinned dependencies in runtime/ through tools/setup.py. Run
  `python -m unittest discover -s tests -v` with the project environment.
- If the core, benchmark, or measured inputs change, rerun tools/benchmark.py before
  tools/generate_report.py. Preserve byte hashes across platforms using .gitattributes.
  Synchronize README measurements with the generated report.
- For browser changes, check the real Worker, first-error diagnosis, repair/recheck,
  formula rendering, and relevant responsive layouts. Keep static paths relative for Pages.
- Before publishing, inspect the diff and exclude credentials and local environments.
  Verify the deployed revision and public assets after an authorized push.

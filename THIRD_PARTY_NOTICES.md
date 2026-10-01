# Third-party components

The application includes unmodified browser runtime and formula-rendering components:

- Pyodide 0.27.7 — Mozilla / Pyodide contributors, Mozilla Public License 2.0. https://github.com/pyodide/pyodide
- Python 3.12 standard library — Python Software Foundation license. https://docs.python.org/3/license.html
- SymPy 1.13.3 — SymPy contributors, BSD 3-Clause. Its original license is included in the packaged wheel. https://github.com/sympy/sympy
- mpmath 1.3.0 — mpmath contributors, BSD 3-Clause. Its original license is included in the packaged wheel. https://github.com/mpmath/mpmath
- KaTeX 0.16.22 — Khan Academy and other contributors, MIT. License supplied under `katex/LICENSE`.

Pyodide and Python license texts are supplied under `runtime/`. This demo's browser assets make no runtime requests to third-party CDNs.

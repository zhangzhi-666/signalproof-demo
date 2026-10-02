"""Small command-line interface; verification runs in a killable child process."""
import argparse
import functools
import http.server
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MAX_REQUEST_BYTES = 100_000


def read_request(path):
    """The same bounded JSON envelope is accepted from a UTF-8 file or stdin."""
    if path == '-':
        content = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    else:
        with Path(path).open('rb') as stream:
            content = stream.read(MAX_REQUEST_BYTES + 1)
    if len(content) > MAX_REQUEST_BYTES:
        raise ValueError('JSON request exceeds 100000 bytes.')
    request = json.loads(content.decode('utf-8-sig'))
    if not isinstance(request, dict):
        raise ValueError('The request must be a JSON object with a steps array.')
    return request


def evaluate(request, timeout):
    # Input travels through stdin, never through shell interpolation or eval.
    child = subprocess.run(
        [sys.executable, '-m', 'engine', '_request'],
        input=json.dumps(request, ensure_ascii=False, allow_nan=False),
        capture_output=True, text=True, encoding='utf-8',
        cwd=ROOT, timeout=timeout, check=False,
    )
    if child.returncode not in (0, 2):
        raise RuntimeError(child.stderr.strip() or 'Verification process failed.')
    return json.loads(child.stdout), child.returncode


def emit(result, output, pretty):
    text = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2 if pretty else None)
    if output:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + '\n', encoding='utf-8')
    else:
        print(text)


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='SignalProof: bounded signal derivation verification')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('verify', 'format', 'catalog'):
        command = commands.add_parser(name)
        if name != 'catalog':
            command.add_argument('input', help='UTF-8 JSON request, or - for stdin')
        command.add_argument('--output', type=Path, help='save JSON instead of writing stdout')
        command.add_argument('--pretty', action='store_true')
        command.add_argument('--timeout', type=float, default=15, help='wall seconds, including process startup')
        if name == 'verify':
            command.add_argument('--require-correct', action='store_true', help='exit 1 unless the chain is verified correct')
    server = commands.add_parser('serve', help='serve the Web UI locally')
    server.add_argument('--port', type=int, default=8080)
    commands.add_parser('_request', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == 'serve':
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        with http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler) as site:
            print(f'SignalProof: http://127.0.0.1:{args.port}/  (Ctrl+C to stop)', flush=True)
            try:
                site.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    if args.command == '_request':
        from .service import dispatch
        try:
            emit(dispatch(read_request('-')), None, False)
            return 0
        except Exception as error:
            emit({'status': 'error', 'error': str(error)}, None, False)
            return 2
    if not 0 < args.timeout <= 300:
        parser.error('--timeout must be greater than 0 and at most 300 seconds')
    try:
        request = {} if args.command == 'catalog' else read_request(args.input)
        request['action'] = args.command
        result, code = evaluate(request, args.timeout)
        if args.command == 'format' and any(row.get('error') for row in result.get('lines', [])):
            code = 2  # Keep useful per-line output, but signal invalid input to scripts.
    except subprocess.TimeoutExpired:
        result, code = {'status': 'unknown', 'error': 'Request timed out; no mathematical verdict was produced.', 'timedOut': True}, 3
    except (OSError, ValueError, RuntimeError) as error:
        result, code = {'status': 'error', 'error': str(error)}, 2
    emit(result, args.output, args.pretty)
    if not code and getattr(args, 'require_correct', False) and result.get('status') != 'correct':
        return 1
    return code


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Serve the demo site on 127.0.0.1 only (standard library, no dependencies).

    python3 serve.py [--port 8765]

--port 0 picks a free port; the URL is printed either way.
"""
import argparse
import functools
import http.server
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.map': 'application/json', '.js': 'text/javascript'}

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; the URL is printed once at start-up


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--port', type=int, default=8765, help='port to listen on (default 8765; 0 = any free port)')
    args = ap.parse_args()
    if not 0 <= args.port <= 65535:
        ap.error('--port must be between 0 and 65535')
    handler = functools.partial(Handler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler) as srv:
        print(f'Serving the demo site at http://127.0.0.1:{srv.server_address[1]}/ (Ctrl+C to stop)', flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print()


if __name__ == '__main__':
    main()

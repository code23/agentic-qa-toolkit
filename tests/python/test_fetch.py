"""_fetch.py: the polite fetcher shared by the Python content checks."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import qa_support as qs

sys.path.insert(0, str(qs.SITE_SCRIPTS))
import _fetch as fx  # noqa: E402

HTML = {"Content-Type": "text/html; charset=utf-8"}


def fetch(url, **kw):
    kw.setdefault("delay", 0)
    return fx.fetch_page(url, **kw)


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RawServer:
    """Server whose handler writes the raw response itself, for responses FixtureServer cannot express."""

    def __init__(self, respond):
        self.stop = threading.Event()
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                try:
                    respond(self, outer.stop)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]

    def url(self, path="/"):
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def in_thread(fn, limit=15):
    """Run fn in a thread; fail instead of hanging when it takes longer than limit seconds."""
    box = {}
    t = threading.Thread(target=lambda: box.update(result=fn()), daemon=True)
    t.start()
    t.join(limit)
    return box.get("result"), not t.is_alive()


class FetchPage(unittest.TestCase):
    def test_ok_page_is_recorded_with_status_type_and_encoding(self):
        with qs.FixtureServer({"/p": qs.html("<p>Hello garden</p>", title="Hi")}) as s:
            rec = fetch(s.url("/p"))
        self.assertEqual((rec["status"], rec["error"], rec["content_type"], rec["encoding"]), (200, None, "text/html", "utf-8"))
        self.assertIn("Hello garden", rec["html"])
        self.assertEqual(rec["redirects"], [])
        self.assertEqual(rec["final_url"], s.url("/p"))

    def test_request_is_a_plain_tagged_get_without_credentials(self):
        with qs.FixtureServer({"/p": qs.html("<p>x</p>")}) as s:
            with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1"}):
                rec = fetch(s.url("/p"))   # trust_env=False: a bad proxy in the environment is ignored
        self.assertEqual(rec["status"], 200)
        method, path, headers, _ = s.requests[0]
        self.assertEqual(method, "GET")
        self.assertIn("qa-toolkit-audit", headers["User-Agent"])
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_non_200_has_an_error_and_no_html(self):
        with qs.FixtureServer({"/gone": (404, HTML, b"<html>nope</html>"), "/boom": (500, HTML, b"<html>x</html>")}) as s:
            for path, code in (("/gone", 404), ("/boom", 500), ("/missing", 404)):
                rec = fetch(s.url(path))
                self.assertEqual(rec["status"], code)
                self.assertEqual(rec["error"], f"HTTP {code}")
                self.assertEqual(rec["html"], "")

    def test_non_html_content_is_refused(self):
        with qs.FixtureServer({"/data": (200, {"Content-Type": "application/json"}, b"{}"),
                               "/bare": (200, {}, b"hello")}) as s:
            rec = fetch(s.url("/data"))
            self.assertEqual(rec["error"], "not HTML (application/json)")
            self.assertEqual(rec["html"], "")
            self.assertTrue(fetch(s.url("/bare"))["error"].startswith("not HTML"))

    def test_oversize_page_is_cut_off_with_an_error(self):
        big = b"<html><body>" + b"a" * 200_000 + b"</body></html>"
        with qs.FixtureServer({"/big": (200, HTML, big)}) as s:
            rec = fetch(s.url("/big"), max_bytes=100_000)
            self.assertEqual(rec["error"], "larger than 100000 bytes")
            self.assertEqual(rec["html"], "")
            self.assertIsNone(fetch(s.url("/big"), max_bytes=300_000)["error"])

    def test_redirects_are_followed_and_recorded_without_query_strings(self):
        routes = {"/old": (301, {"Location": "/mid?token=abc123"}, b""),
                  "/mid": (302, {"Location": "/new?x=1&secret=zzz"}, b""),
                  "/new": qs.html("<p>arrived</p>")}
        with qs.FixtureServer(routes) as s:
            rec = fetch(s.url("/old") + "?utm=1")
        self.assertEqual(rec["status"], 200)
        self.assertEqual(rec["redirects"], [f"301 {s.url('/old')}", f"302 {s.url('/mid')}"])
        self.assertEqual(rec["final_url"], s.url("/new"))
        self.assertNotIn("?", json.dumps({k: v for k, v in rec.items() if k not in ("html", "final_url_exact", "url")}))
        self.assertIn("x=1", rec["final_url_exact"])   # exact URL stays in memory only

    def test_redirect_off_the_input_host_is_refused_without_a_request(self):
        with qs.FixtureServer({"/secret": qs.html("<p>elsewhere</p>")}) as other:
            target = f"http://localhost:{other.port}/secret/page?token=abc123"   # same machine, but another host:port
            with qs.FixtureServer({"/start": (302, {"Location": target}, b"")}) as s:
                rec = fetch(s.url("/start") + "?utm=1")
            self.assertEqual(other.requests, [], "the refused target must never be contacted")
        self.assertEqual(rec["error"], f"redirect to a host outside the input URLs (not followed): localhost:{other.port}")
        self.assertEqual(rec["html"], "")
        self.assertEqual(rec["status"], 302)
        self.assertEqual(rec["redirects"], [f"302 {s.url('/start')}"])
        self.assertNotIn("secret", json.dumps({k: v for k, v in rec.items() if k != "url"}))   # no path or query of the refused target

    def test_chain_that_leaves_the_allowed_hosts_on_the_second_hop(self):
        with qs.FixtureServer({"/x": qs.html("<p>x</p>")}) as other:
            routes = {"/a": (301, {"Location": "/b"}, b""), "/b": (301, {"Location": other.url("/x")}, b"")}
            with qs.FixtureServer(routes) as s:
                rec = fetch(s.url("/a"))
            self.assertEqual(other.requests, [])
        self.assertIn("outside the input URLs", rec["error"])
        self.assertEqual(rec["redirects"], [f"301 {s.url('/a')}", f"301 {s.url('/b')}"])   # the followed hop and the refused one
        self.assertEqual(rec["html"], "")

    def test_explicit_allowed_hosts_permit_a_second_host(self):
        with qs.FixtureServer({"/x": qs.html("<p>arrived elsewhere</p>")}) as other:
            with qs.FixtureServer({"/a": (302, {"Location": other.url("/x")}, b"")}) as s:
                refused = fetch(s.url("/a"))
                ok = fetch(s.url("/a"), allowed_hosts=fx.allowed_hosts_for([s.url("/a"), other.url("/")]))
        self.assertTrue(refused["error"])
        self.assertIsNone(ok["error"])
        self.assertIn("arrived elsewhere", ok["html"])
        self.assertEqual(len(other.hits("/x")), 1)

    def test_redirect_limit_is_five_hops(self):
        routes = {f"/h{i}": (302, {"Location": f"/h{i + 1}"}, b"") for i in range(8)}
        routes["/h5"] = qs.html("<p>five hops in</p>")
        routes["/h6"] = qs.html("<p>never reached</p>")
        with qs.FixtureServer(routes) as s:
            ok = fetch(s.url("/h0"))
            self.assertIsNone(ok["error"])
            self.assertEqual(len(ok["redirects"]), 5)
            s.routes["/h5"] = (302, {"Location": "/h6"}, b"")   # now six redirects are needed
            too_many = fetch(s.url("/h0"))
            self.assertEqual(too_many["error"], "more than 5 redirects")
            self.assertEqual(len(too_many["redirects"]), 6)
            self.assertEqual(s.hits("/h6"), [])

    def test_redirect_loop_ends_with_an_error(self):
        with qs.FixtureServer({"/loop": (302, {"Location": "/loop"}, b"")}) as s:
            rec = fetch(s.url("/loop"))
        self.assertEqual(rec["error"], "more than 5 redirects")

    def test_redirects_to_other_schemes_or_with_credentials_are_refused(self):
        for target in ("ftp://example.com/file", "mailto:someone@example.com", "javascript:alert(1)", "https://user:pw@example.com/"):
            with self.subTest(target), qs.FixtureServer({"/r": (302, {"Location": target}, b"")}) as s:
                rec = fetch(s.url("/r"))
                self.assertIn("non-http(s)", rec["error"])
                self.assertEqual(rec["html"], "")
                self.assertEqual(len(s.requests), 1)

    def test_relative_and_fragment_redirect_targets(self):
        routes = {"/dir/a": (302, {"Location": "../b/page#section"}, b""), "/b/page": qs.html("<p>landed</p>")}
        with qs.FixtureServer(routes) as s:
            rec = fetch(s.url("/dir/a"))
        self.assertIsNone(rec["error"])
        self.assertEqual(rec["final_url"], s.url("/b/page"))
        self.assertNotIn("#", rec["final_url_exact"])

    def test_redirect_without_a_location_is_a_plain_http_error(self):
        with qs.FixtureServer({"/r": (302, {}, b"")}) as s:
            self.assertEqual(fetch(s.url("/r"))["error"], "HTTP 302")

    def test_a_refused_redirect_is_not_cached(self):
        with qs.FixtureServer({"/x": qs.html("<p>x</p>")}) as other, tempfile.TemporaryDirectory() as cache:
            with qs.FixtureServer({"/a": (302, {"Location": other.url("/x")}, b"")}) as s:
                fetch(s.url("/a"), cache_dir=cache)
                second = fetch(s.url("/a"), cache_dir=cache)
                self.assertNotIn("cached", second)
                self.assertEqual(len(s.hits("/a")), 2)
                self.assertEqual(list(Path(cache).glob("*.json")), [])
            self.assertEqual(other.requests, [])

    def test_host_key_and_www_twins(self):
        self.assertEqual(fx.host_key("HTTPS://Example.com/a?b=1"), "example.com")
        self.assertEqual(fx.host_key("https://example.com:443/"), "example.com")
        self.assertEqual(fx.host_key("http://example.com:80/"), "example.com")
        self.assertEqual(fx.host_key("http://example.com:8080/"), "example.com:8080")
        self.assertNotEqual(fx.host_key("http://127.0.0.1:5000/"), fx.host_key("http://127.0.0.1:5001/"))
        self.assertEqual(fx.with_twin("example.com"), {"example.com", "www.example.com"})
        self.assertEqual(fx.with_twin("www.example.com"), {"example.com", "www.example.com"})
        self.assertEqual(fx.with_twin("example.com:8080"), {"example.com:8080", "www.example.com:8080"})

    def test_allowed_hosts_cover_every_input_host_and_its_twin_only(self):
        allowed = fx.allowed_hosts_for(["https://example.com/a", "https://www.other.example.org/b?x=1", "http://example.com:8080/c"])
        self.assertEqual(allowed, {"example.com", "www.example.com", "other.example.org", "www.other.example.org",
                                   "example.com:8080", "www.example.com:8080"})
        self.assertNotIn("blog.example.com", allowed)   # subdomains other than www are another host

    def test_encoding_detection_header_then_meta_then_utf8_then_cp1252(self):
        text = "<html><head>%s</head><body><p>café à la carte</p></body></html>"
        routes = {
            "/header": (200, {"Content-Type": "text/html; charset=iso-8859-1"}, (text % "").encode("iso-8859-1")),
            "/quoted": (200, {"Content-Type": 'text/html; charset="windows-1252"'}, (text % "").encode("cp1252")),
            "/meta": (200, {"Content-Type": "text/html"}, (text % '<meta charset="windows-1252">').encode("cp1252")),
            "/utf8": (200, {"Content-Type": "text/html"}, (text % "").encode("utf-8")),
            "/unknown-charset": (200, {"Content-Type": "text/html; charset=klingon"}, (text % "").encode("utf-8")),
            "/fallback": (200, {"Content-Type": "text/html"}, (text % "").encode("cp1252")),
        }
        with qs.FixtureServer(routes) as s:
            got = {p.lstrip("/"): fetch(s.url(p)) for p in routes}
        for name in ("header", "quoted", "meta", "utf8", "unknown-charset", "fallback"):
            self.assertIn("café à la carte", got[name]["html"], name)
        self.assertEqual(got["header"]["encoding"], "iso-8859-1")
        self.assertEqual(got["quoted"]["encoding"], "windows-1252")
        self.assertEqual(got["meta"]["encoding"], "windows-1252")
        self.assertEqual(got["utf8"]["encoding"], "utf-8")
        self.assertEqual(got["unknown-charset"]["encoding"], "utf-8")   # unusable header charset is skipped
        self.assertEqual(got["fallback"]["encoding"], "cp1252 (fallback)")

    def test_header_charset_parsing(self):
        for header, expect in (("text/html; charset=utf-8", "utf-8"), ('text/html; charset="shift_jis"', "shift_jis"),
                               ("text/html; charset = 'euc-kr'", "euc-kr"), ("text/html;charset=UTF-8; boundary=x", "UTF-8"),
                               ("text/html", None), ("", None), (None, None)):
            self.assertEqual(fx.header_charset(header), expect, header)

    def test_connection_failure_becomes_an_error_record_with_the_query_hidden(self):
        rec = fetch(f"http://127.0.0.1:{closed_port()}/p?token=supersecretvalue1234567890")
        self.assertIsNone(rec["status"])
        self.assertTrue(rec["error"])
        self.assertNotIn("supersecret", rec["error"])
        self.assertEqual(rec["html"], "")

    def test_cache_reuses_good_pages_and_never_stores_failures(self):
        with qs.FixtureServer({"/p": qs.html("<p>cached</p>")}) as s, tempfile.TemporaryDirectory() as cache:
            first = fetch(s.url("/p"), cache_dir=cache)
            second = fetch(s.url("/p"), cache_dir=cache)
            self.assertNotIn("cached", first)
            self.assertTrue(second["cached"])
            self.assertEqual(second["html"], first["html"])
            self.assertEqual(len(s.hits("/p")), 1)
            fetch(s.url("/404"), cache_dir=cache)
            fetch(s.url("/404"), cache_dir=cache)
            self.assertEqual(len(s.hits("/404")), 2)
            self.assertEqual(len(list(Path(cache).glob("*.json"))), 1)

    def test_delay_between_requests_is_honoured(self):
        with qs.FixtureServer({"/a": qs.html("<p>a</p>")}) as s:
            fx._last[0] = 0.0
            fetch(s.url("/a"), delay=0)
            with mock.patch.object(fx.time, "sleep") as sleep:
                fetch(s.url("/a"), delay=5)
            self.assertTrue(sleep.called)
            self.assertGreater(sleep.call_args[0][0], 0)
            self.assertLessEqual(sleep.call_args[0][0], 5)


class RedirectHandling(unittest.TestCase):
    def test_a_streaming_redirect_body_is_never_read(self):
        def respond(h, stop):
            h.wfile.write(b"HTTP/1.0 302 Found\r\nLocation: http://localhost:9/elsewhere\r\n\r\n")
            h.wfile.flush()
            while not stop.is_set():   # endless body: reading it would never finish
                h.wfile.write(b"x" * 65536)
        with RawServer(respond) as s:
            t0 = time.time()
            rec, finished = in_thread(lambda: fetch(s.url("/endless"), timeout=30))
        self.assertTrue(finished, "fetch_page hung on a redirect body")
        self.assertLess(time.time() - t0, 10)
        self.assertIn("outside the input URLs", rec["error"])
        self.assertEqual(rec["html"], "")

    def test_a_streaming_redirect_to_an_allowed_host_is_followed_without_reading_its_body(self):
        def respond(h, stop):
            if h.path == "/ok":
                body = qs.html("<p>arrived</p>")
                h.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
                return
            h.wfile.write(b"HTTP/1.0 301 Moved\r\nLocation: /ok\r\n\r\n")
            h.wfile.flush()
            while not stop.is_set():
                h.wfile.write(b"y" * 65536)
        with RawServer(respond) as s:
            rec, finished = in_thread(lambda: fetch(s.url("/start")))
        self.assertTrue(finished)
        self.assertIsNone(rec["error"])
        self.assertIn("arrived", rec["html"])

    def test_malformed_location_headers_become_error_records_not_exceptions(self):
        def respond(h, stop):
            loc = {"/latin1": b"/\xff", "/utf8": b"/caf\xc3\xa9", "/bad-ipv6": b"http://[::1"}.get(h.path)
            if loc is None:   # the redirect targets themselves
                h.wfile.write(b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return
            h.wfile.write(b"HTTP/1.0 302 Found\r\nLocation: " + loc + b"\r\nContent-Length: 0\r\n\r\n")
        with RawServer(respond) as s:
            bad = fetch(s.url("/bad-ipv6"))
            self.assertEqual(bad["error"], "redirect with an unusable Location header (not followed)")
            for path in ("/latin1", "/utf8"):
                rec = fetch(s.url(path))   # followed to a path the server does not know: an HTTP error, never a crash
                self.assertTrue(rec["error"], path)
            self.assertIn("/caf%C3%A9", s.requests)   # the UTF-8 Location was read as UTF-8

    def test_the_session_does_not_resolve_redirects_itself(self):
        self.assertIsNone(fx._session().get_redirect_target(object()))

    def test_ipv6_host_keys_are_unambiguous(self):
        a, b = "http://[2001:db8::1]:8080/", "http://[2001:db8::1:8080]/"
        self.assertEqual(fx.host_key(a), "[2001:db8::1]:8080")
        self.assertEqual(fx.host_key(b), "[2001:db8::1:8080]")
        self.assertNotEqual(fx.host_key(a), fx.host_key(b))
        self.assertTrue(fx.host_key(a) in fx.allowed_hosts_for([a]))
        self.assertTrue(fx.host_key(b) not in fx.allowed_hosts_for([a]))

    def test_one_ipv6_address_does_not_pass_the_other_ones_allowlist(self):
        with qs.FixtureServer({"/a": (302, {"Location": "http://[2001:db8::1:8080]/"}, b"")}) as s:
            allowed = fx.allowed_hosts_for([s.url("/a"), "http://[2001:db8::1]:8080/"])
            rec = fetch(s.url("/a"), allowed_hosts=allowed)   # a wrongly allowed target would be dialled, not refused
        self.assertIn("outside the input URLs", rec["error"])
        self.assertIn("[2001:db8::1:8080]", rec["error"])

    def test_only_domain_names_get_www_twins(self):
        for key in ("127.0.0.1", "127.0.0.1:8080", "[2001:db8::1]", "[2001:db8::1]:8080"):
            self.assertEqual(fx.with_twin(key), {key}, key)
        self.assertEqual(fx.with_twin("localhost:3000"), {"localhost:3000", "www.localhost:3000"})
        self.assertEqual(fx.allowed_hosts_for(["http://192.0.2.7/"]), {"192.0.2.7"})


class Redaction(unittest.TestCase):
    def test_safe_url_redacts_emails_and_tokens_in_the_path(self):
        self.assertEqual(fx.safe_url("https://example.com/users/jane.doe@example.com/profile?x=1#f"), "https://example.com/users/<email>/profile")
        self.assertEqual(fx.safe_url("https://example.com/users/jane.doe%40example.com/"), "https://example.com/users/<email>/")
        self.assertEqual(fx.safe_url("https://example.com/reset/QX7R2M9KLP4W8ZC3VB6N5A/done"), "https://example.com/reset/QX7R…<redacted>/done")
        self.assertEqual(fx.safe_url("https://example.com/key/sk-abcdefghijklmnop"), "https://example.com/key/sk-a…<redacted>")

    def test_safe_url_leaves_ordinary_paths_and_the_host_readable(self):
        for u in ("https://www.example.com:8443/services/chain-care-guide.html", "https://example.com/2026-10-13-annual-report-summary/",
                  "https://example.com/"):
            self.assertEqual(fx.safe_url(u + "?q=1"), u)

    def test_safe_url_brackets_ipv6_hosts(self):
        self.assertEqual(fx.safe_url("http://[2001:db8::1]:8080/a?b=1"), "http://[2001:db8::1]:8080/a")

    def test_redirect_chain_and_final_url_use_the_redacted_path(self):
        routes = {"/r/QX7R2M9KLP4W8ZC3VB6N5A": (302, {"Location": "/jane.doe@example.com"}, b""), "/jane.doe@example.com": qs.html("<p>x</p>")}
        with qs.FixtureServer(routes) as s:
            rec = fetch(s.url("/r/QX7R2M9KLP4W8ZC3VB6N5A"))
        self.assertNotIn("QX7R2M9KLP4W8ZC3VB6N5A", json.dumps({k: v for k, v in rec.items() if k not in ("url", "final_url_exact")}))
        self.assertNotIn("jane.doe", rec["final_url"])

    def test_credential_formats_without_digits_are_redacted(self):
        samples = ["sk-proj-abcdefghijklmnop", "ghp_abcdefghijklmnopqrstuv", "gho_abcdefghijklmnop", "xoxb-abcdefghijkl-mnop",
                   "AKIAABCDEFGHIJKLMNOP", "Bearer abcdefghijklmnopqrst",
                   "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYmNkZWYifQ.abcdefghijklmnop"]
        for sample in samples:
            with self.subTest(sample):
                out = fx.red(f"header was {sample} end")
                self.assertIn("…<redacted>", out)
                self.assertNotIn(sample[4:], out)
                self.assertIn("header was", out)

    def test_ordinary_words_are_not_redacted(self):
        text = "Our task-force skills: Bearer of good news, ghp is not a token, AKIA alone is a word."
        self.assertEqual(fx.red(text), text)

    def test_content_type_is_stored_as_a_normalised_media_type_only(self):
        routes = {"/ok": (200, {"Content-Type": "Text/HTML; charset=utf-8; session=abc123secretvalue"}, qs.html("<p>x</p>")),
                  "/json": (200, {"Content-Type": "application/json; token=zzz123secret"}, b"{}"),
                  "/junk": (200, {"Content-Type": "not a media type; secret=hunter2"}, b"x")}
        with qs.FixtureServer(routes) as s:
            ok, js, junk = fetch(s.url("/ok")), fetch(s.url("/json")), fetch(s.url("/junk"))
        self.assertEqual((ok["content_type"], ok["error"]), ("text/html", None))
        self.assertEqual((js["content_type"], js["error"]), ("application/json", "not HTML (application/json)"))
        self.assertEqual((junk["content_type"], junk["error"]), ("", "not HTML (invalid content-type)"))
        for rec in (ok, js, junk):
            blob = json.dumps({k: v for k, v in rec.items() if k not in ("html", "url", "final_url_exact")})
            self.assertNotIn("secret", blob)
            self.assertNotIn("hunter2", blob)

    def test_media_type_helper(self):
        for raw, expect in (("text/html", "text/html"), (" Application/XHTML+xml ; q=1", "application/xhtml+xml"), ("", ""), (None, ""),
                            ("html", ""), ("text/", ""), ("a b/c", "")):
            self.assertEqual(fx.media_type(raw), expect, raw)


class DependencyPreflight(unittest.TestCase):
    def test_a_missing_package_exits_2_before_any_url_is_fetched(self):
        with tempfile.TemporaryDirectory() as d, qs.FixtureServer({"/p": qs.html("<p>x</p>")}) as s:
            blocker = Path(d) / "blocker" / "lxml"
            blocker.mkdir(parents=True)
            (blocker / "__init__.py").write_text('raise ImportError("blocked for this test", name="lxml")\n', encoding="utf-8")
            for script in ("similarity.py", "copy_freshness.py"):
                with self.subTest(script):
                    out = Path(d) / f"{script}.json"
                    r = qs.run_script(qs.SITE_SCRIPTS / script, s.url("/p") + "," + s.url("/p2"), "--out", out,
                                      env={"PYTHONPATH": str(blocker.parent)}, cwd=d)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("lxml", r.stderr)
                    self.assertNotIn("Traceback", r.stderr)
                    self.assertFalse(out.exists())
            self.assertEqual(s.requests, [])


class ReadUrls(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def errors(self, arg):
        seen = []

        def error(msg):
            seen.append(msg)
            raise SystemExit(2)

        with self.assertRaises(SystemExit):
            fx.read_urls(arg, error)
        return seen[0]

    def test_comma_separated_list(self):
        self.assertEqual(fx.read_urls("https://example.com/a, http://example.com/b ,,"), ["https://example.com/a", "http://example.com/b"])

    def test_file_with_comments_and_blank_lines(self):
        p = self.tmp / "urls.txt"
        p.write_text("# sitemap sample\nhttps://example.com/\n\n  https://example.com/about  \n#https://example.com/skipped\n", encoding="utf-8")
        self.assertEqual(fx.read_urls(str(p)), ["https://example.com/", "https://example.com/about"])

    def test_invalid_urls_call_the_error_handler_without_leaking_query_strings(self):
        for bad in ("ftp://example.com/x", "example.com", "https://user:pass@example.com/", "https://example.com:notaport/",
                    "https://[::1/", "javascript:alert(1)"):
            with self.subTest(bad):
                msg = self.errors(f"https://example.com/ok,{bad}")
                self.assertIn("invalid URL", msg)
        self.assertNotIn("sekret", self.errors("https://example.com/?key=sekret,ftp://example.com/?key=sekret"))

    def test_empty_list_is_an_error(self):
        p = self.tmp / "empty.txt"
        p.write_text("# nothing\n\n", encoding="utf-8")
        self.assertIn("empty", self.errors(str(p)))

    def test_default_error_handler_exits_2(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as cm:
            fx.read_urls("ftp://example.com/")
        self.assertEqual(cm.exception.code, 2)


class Helpers(unittest.TestCase):
    def test_safe_url_drops_query_fragment_and_credentials(self):
        self.assertEqual(fx.safe_url("https://user:pw@example.com:8443/a/b?token=1#frag"), "https://example.com:8443/a/b")
        self.assertEqual(fx.safe_url("https://example.com"), "https://example.com")

    def test_redaction_of_emails_tokens_and_urls(self):
        out = fx.red("mail jane@example.com or info@example.com, key abcd1234efgh5678ijkl9012 see https://example.com/p?token=x#y")
        self.assertNotIn("jane@", out)
        self.assertNotIn("ijkl9012", out)
        self.assertNotIn("token=x", out)
        self.assertIn("https://example.com/p", out)
        self.assertIn("abcd…<redacted>", out)
        kept = fx.red("info@example.com and jane@example.com", keep_email=lambda e: e.startswith("info@"))
        self.assertIn("info@example.com", kept)
        self.assertIn("<email>", kept)

    def test_main_text_prefers_main_and_strips_chrome_otherwise(self):
        _, text, root = fx.main_text("<body><header>Menu</header><main><p>Core text</p><script>var x=1</script></main><footer>Foot</footer></body>")
        self.assertEqual((text, root), ("Core text", "main"))
        _, text, root = fx.main_text("<body><header>Menu</header><nav>Links</nav><p>Body text</p><aside>Side</aside><footer>Foot</footer></body>")
        self.assertEqual((text, root), ("Body text", "body"))

    def test_csr_hint(self):
        shell = '<body><div id="root"></div></body>'
        self.assertTrue(fx.csr_hint(shell, 3))
        self.assertTrue(fx.csr_hint("<body>" + '<script src="/a.js"></script>' * 3 + "</body>", 3))
        self.assertFalse(fx.csr_hint(shell, 400))                      # plenty of served words
        self.assertFalse(fx.csr_hint("<body><p>plain</p></body>", 3))   # no app root, few scripts

    def test_coverage_rule(self):
        self.assertEqual(fx.coverage(100, 100, False), "full")
        self.assertEqual(fx.coverage(60, 100, False), "limited (client-rendered)")   # under 70% of rendered
        self.assertEqual(fx.coverage(70, 100, False), "full")
        self.assertEqual(fx.coverage(10, None, True), "limited (client-rendered)")
        self.assertEqual(fx.coverage(10, None, False), "full")
        self.assertEqual(fx.coverage(100, 100, True), "full")   # rendered figure beats the hint

    def test_rendered_words_takes_max_over_widths_and_keys_by_safe_url(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "overflow.json"
            p.write_text(json.dumps({"results": [{"url": "https://example.com/a", "renderedWords": 120},
                                                 {"url": "https://example.com/a", "renderedWords": 300},
                                                 {"url": "https://example.com/b", "renderedWords": None}]}), encoding="utf-8")
            self.assertEqual(fx.rendered_words(str(p)), {"https://example.com/a": 300})
        self.assertEqual(fx.rendered_words(None), {})

    def test_write_json_creates_folders_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "evidence" / "out.json"
            fx.write_json(str(p), {"a": 1})
            self.assertEqual(json.loads(p.read_text()), {"a": 1})
            self.assertEqual([x.name for x in p.parent.iterdir()], ["out.json"])


if __name__ == "__main__":
    unittest.main()

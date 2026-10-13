"""qa-send: refusals through the real CLI, and the send path against a local server (urllib patched, https not needed)."""
import contextlib
import gc
import io
import json
import os
import stat
import sys
import socket
import ssl
import tempfile
import unittest
import urllib.error
import warnings
from pathlib import Path
from unittest import mock

import qa_support as qs

SCRIPT = qs.QA_SEND
Q = qs.load_module("qa_send_module", SCRIPT)
GOOD_URL = "https://preview.example.com/page"
# A configured webhook that cannot be reached: a refusal test that wrongly gets past validation would fail with "send failed".
DEAD_HOOK = "https://127.0.0.1:1/hook"


class SendCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.home = self.tmp / "home"
        self.home.mkdir()

    def config(self, content=None, mode=0o600, name="config.json"):
        content = {"url": DEAD_HOOK, "headers": {"Authorization": "Bearer test-key-123"}} if content is None else content
        p = self.tmp / name
        p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        os.chmod(p, mode)
        return p

    def cli(self, *args, config=None, stdin=None, env=None):
        e = {"HOME": str(self.home)}
        e["QA_SEND_CONFIG"] = str(config if config is not None else self.config())
        e.update(env or {})
        return qs.run_script(SCRIPT, *args, env=e, stdin=stdin)

    def refused(self, *args, expect, **kw):
        r = self.cli(*args, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stderr.startswith("qa-send: "), r.stderr)
        self.assertIn(expect, r.stderr)
        self.assertNotIn("send failed", r.stderr)   # it was refused before anything was sent
        return r


class TargetRefusals(SendCase):
    def test_bad_scheme_or_no_host(self):
        for url in ("ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "example.com", "https://", "//example.com"):
            with self.subTest(url):
                self.refused("--url", url, expect="--url must be an http(s) URL")

    def test_credentials_in_the_url(self):
        for url in ("https://user:pw@example.com/", "https://user@example.com/"):
            with self.subTest(url):
                self.refused("--url", url, expect="must not contain a username or password")

    def test_local_private_and_numeric_hosts(self):
        hosts = ["localhost", "LOCALHOST", "app.localhost", "devbox.local", "db.internal", "127.0.0.1", "127.1.2.3", "10.0.0.5",
                 "192.168.1.20", "172.16.4.4", "169.254.10.10", "0.0.0.0", "[::1]", "[fe80::1]", "[fd00::1]",
                 "2130706433", "0x7f000001", "017700000001"]
        for host in hosts:
            with self.subTest(host):
                self.refused("--url", f"https://{host}/", expect="local or private address")

    def test_other_spellings_of_local_addresses(self):
        # short dotted, hex and octal forms and the trailing-dot form all reach the same machine
        for host in ("127.1", "127.0.1", "0x7f.0.0.1", "0177.0.0.1", "localhost.", "[::ffff:127.0.0.1]", "10.1"):
            with self.subTest(host):
                self.refused("--url", f"https://{host}/", expect="local or private address")

    def test_token_like_query_parameters(self):
        for q in ("token=abc", "access_token=abc", "API_KEY=abc", "apikey=abc", "api-key=abc", "secret=1", "password=1", "passwd=1",
                  "auth=1", "Authorization=x", "signature=1", "x-amz-signature=1", "page=2&token="):
            with self.subTest(q):
                self.refused("--url", f"{GOOD_URL}?{q}", expect="carries a key or token")

    def test_ordinary_query_strings_and_public_hosts_are_accepted(self):
        for url in (GOOD_URL + "?utm_source=mail&page=2", "http://example.com/", "https://preview.example.com:8443/x", "https://8.8.8.8/",
                    "https://172.32.0.1/", "https://[2001:4860:4860::8888]/"):
            with self.subTest(url):
                Q.check_target(url)   # returns without exiting


class HardenedTargetChecks(SendCase):
    def test_hosts_with_percent_encoding_or_odd_characters_are_refused(self):
        for host in ("%31%32%37.0.0.1", "%6cocalhost", "local%68ost", "exa_mple.com", "ex%61mple.com", "exam ple.com", "[fe80::1%25eth0]", "b\u00fccher.example"):
            with self.subTest(host):
                self.refused("--url", f"https://{host}/", expect="letters, digits")

    def test_ordinary_and_bracketed_ipv6_hosts_pass_the_character_check(self):
        for url in ("https://sub-domain.example.com/", "https://a.b.c.example.org:8443/x", "https://[2001:4860:4860::8888]/", "https://8.8.8.8/"):
            with self.subTest(url):
                Q.check_target(url)

    def test_refusal_and_docstring_say_it_is_only_a_convenience_check(self):
        self.assertIn("convenience", Q.__doc__)
        self.assertIn("enforce its own network rules", Q.__doc__)
        r = self.refused("--url", "https://localhost/", expect="local or private address")
        self.assertIn("convenience check", r.stderr)
        self.assertIn("network rules", r.stderr)

    def test_generic_secret_like_query_names_are_refused(self):
        for q in ("key=abc", "access_key=abc", "access-key=abc", "sig=abc", "session=abc", "sessionid=abc", "password=abc", "code=abc",
                  "sid=abc", "pwd=abc", "credential=abc", "Key=abc", "page=2&code=9"):
            with self.subTest(q):
                self.refused("--url", f"{GOOD_URL}?{q}", expect="carries a key or token")

    def test_ordinary_query_names_are_still_allowed(self):
        for q in ("page=2", "utm_source=x", "utm_campaign=spring&page=3", "q=chain+oil", "lang=en", "keyword=bikes", "sort=asc", "decode=1", "sigma=2", "monkey=1"):
            with self.subTest(q):
                Q.check_target(f"{GOOD_URL}?{q}")


class ConfigRefusals(SendCase):
    def test_missing_config(self):
        self.refused("--url", GOOD_URL, config=self.tmp / "absent.json", expect="not configured, missing")

    def test_default_config_path_is_under_home(self):
        r = qs.run_script(SCRIPT, "--url", GOOD_URL, env={"HOME": str(self.home), "QA_SEND_CONFIG": ""})
        self.assertEqual(r.returncode, 1)
        self.assertIn(str(self.home / ".config" / "qa-send" / "config.json"), r.stderr)

    def test_config_readable_by_other_users(self):
        for mode in (0o644, 0o640, 0o604, 0o660, 0o666):
            with self.subTest(oct(mode)):
                self.refused("--url", GOOD_URL, config=self.config(mode=mode), expect="readable by other users")
        r = self.cli("--url", GOOD_URL, config=self.config(mode=0o400))
        self.assertNotIn("readable by other users", r.stderr)

    def test_unparseable_and_non_object_config(self):
        self.refused("--url", GOOD_URL, config=self.config("{nope"), expect="is not valid JSON")
        for body in ("[]", '"text"', "42", "null"):
            with self.subTest(body):
                self.refused("--url", GOOD_URL, config=self.config(body), expect="must hold a JSON object")

    def test_placeholder_or_insecure_webhook(self):
        for url in ("https://<your-webhook-host>/<path>", "http://hooks.example.com/x", "ftp://hooks.example.com/x", "", None, 5, "HTTPS://hooks.example.com"):
            with self.subTest(url):
                self.refused("--url", GOOD_URL, config=self.config({"url": url, "headers": {}}), expect="https webhook url")
        self.refused("--url", GOOD_URL, config=self.config({"headers": {}}), expect="https webhook url")

    def test_placeholder_or_malformed_headers(self):
        for headers in ({"Authorization": "Bearer <your key>"}, ["not", "a", "dict"], "text"):
            with self.subTest(headers):
                self.refused("--url", GOOD_URL, config=self.config({"url": DEAD_HOOK, "headers": headers}), expect="headers are missing or still hold")


class HeaderAndFailureSafety(SendCase):
    SECRET = "Bearer sup3r-secret-key-value"

    def test_header_values_with_control_characters_are_refused_up_front_without_echoing_them(self):
        for value in (self.SECRET + "\n", self.SECRET + "\r\nX-Evil: 1", "bad\x00value " + self.SECRET, "caf\u20ac " + self.SECRET):
            with self.subTest(repr(value)[-12:]):
                cfg = self.config({"url": DEAD_HOOK, "headers": {"Authorization": value}})
                r = self.refused("--url", GOOD_URL, config=cfg, expect="header #1 (Authorization) has an invalid value")
                self.assertNotIn("sup3r-secret", r.stdout + r.stderr)

    def test_header_names_are_validated(self):
        for name in ("Bad Name", "X:Y", "", "X\nY"):
            with self.subTest(repr(name)):
                cfg = self.config({"url": DEAD_HOOK, "headers": {name: "value"}})
                self.refused("--url", GOOD_URL, config=cfg, expect="header #1 has an invalid name")

    def test_normal_header_values_are_accepted(self):
        with mock.patch.dict(os.environ, {"QA_SEND_CONFIG": str(self.config({"url": DEAD_HOOK, "headers": {"X-Api-Key": "abc 123\tdef", "Authorization": self.SECRET}}))}):
            self.assertEqual(Q.load_config()[1]["X-Api-Key"], "abc 123\tdef")

    def test_send_failures_print_a_classification_not_the_exception_text(self):
        cases = [
            (urllib.error.HTTPError("https://h", 500, "Server Error " + self.SECRET, {}, io.BytesIO()), "HTTP status 500"),
            (urllib.error.HTTPError("https://h", 302, "Found " + self.SECRET, {}, io.BytesIO()), "redirect refused (HTTP 302)"),
            (urllib.error.URLError(ssl.SSLCertVerificationError(1, "bad cert " + self.SECRET)), "TLS error"),
            (urllib.error.URLError(ConnectionRefusedError(61, "refused " + self.SECRET)), "connection refused"),
            (urllib.error.URLError(socket.timeout("timed out " + self.SECRET)), "timeout"),
            (TimeoutError("read timed out " + self.SECRET), "timeout"),
            (urllib.error.URLError(socket.gaierror(8, "nodename " + self.SECRET)), "host name not found"),
            (urllib.error.URLError(OSError("weird " + self.SECRET)), "connection error"),
            (ValueError("Invalid header value b'" + self.SECRET + "\\n'"), "request could not be sent (ValueError)"),
        ]
        for exc, _ in cases:
            if isinstance(exc, urllib.error.HTTPError):
                self.addCleanup(exc.close)
        for exc, expect in cases:
            with self.subTest(expect):
                self.assertEqual(Q.describe_failure(exc), expect)
                self.assertNotIn("sup3r", Q.describe_failure(exc))

    def test_main_prints_only_the_classification_when_the_transport_raises(self):
        class Boom:
            def open(self, req, timeout=None):
                raise ValueError("Invalid header value b'" + HeaderAndFailureSafety.SECRET + "'")

        with mock.patch.object(sys, "argv", ["qa-send", "--url", GOOD_URL]), \
                mock.patch.object(Q, "load_config", return_value=("https://hooks.example.com/in", {"Authorization": self.SECRET})), \
                mock.patch("urllib.request.build_opener", lambda *h: Boom()), self.assertRaises(SystemExit) as cm:
            Q.main()
        self.assertEqual(cm.exception.code, "qa-send: send failed: request could not be sent (ValueError)")

    def test_cli_connection_failure_message_is_a_plain_classification(self):
        r = self.cli("--url", GOOD_URL)   # the configured webhook points at a closed local port
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.strip(), "qa-send: send failed: connection refused")
        self.assertNotIn("test-key-123", r.stdout + r.stderr)


class BriefRefusals(SendCase):
    def test_brief_and_brief_file_together(self):
        f = self.tmp / "brief.txt"
        f.write_text("text", encoding="utf-8")
        self.refused("--url", GOOD_URL, "--brief", "a", "--brief-file", f, expect="give --brief or --brief-file, not both")

    def test_unreadable_brief_file(self):
        self.refused("--url", GOOD_URL, "--brief-file", self.tmp / "missing.txt", expect="cannot read the brief file")
        self.refused("--url", GOOD_URL, "--brief-file", self.tmp, expect="cannot read the brief file")   # a directory
        bad = self.tmp / "binary.txt"
        bad.write_bytes(b"\xff\xfe\x00bad")
        self.refused("--url", GOOD_URL, "--brief-file", bad, expect="cannot read the brief file")

    def test_over_long_brief(self):
        self.refused("--url", GOOD_URL, "--brief", "x" * 4001, expect="longer than 4000 characters")
        f = self.tmp / "long.txt"
        f.write_text("y" * 4001, encoding="utf-8")
        self.refused("--url", GOOD_URL, "--brief-file", f, expect="longer than 4000 characters")
        self.refused("--url", GOOD_URL, "--brief-file", "-", stdin="z" * 4001, expect="longer than 4000 characters")

    def test_brief_length_is_measured_after_trimming(self):
        r = self.cli("--url", GOOD_URL, "--brief", "  " + "x" * 4000 + "  \n")
        self.assertIn("send failed", r.stderr)   # got past validation to the (dead) webhook

    def test_refusals_come_before_the_config_is_read(self):
        r = self.cli("--url", "http://localhost/", config=self.tmp / "absent.json")
        self.assertIn("local or private address", r.stderr)


class UsageErrors(SendCase):
    def test_argparse_errors_exit_2(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("--url", GOOD_URL, "--depth", "thorough").returncode, 2)
        self.assertEqual(self.cli("--url", GOOD_URL, "--bogus").returncode, 2)

    def test_help_works_without_config(self):
        r = qs.run_script(SCRIPT, "--help", env={"HOME": str(self.home)})
        self.assertEqual(r.returncode, 0)
        self.assertIn("--brief-file", r.stdout)


class LoadConfig(SendCase):
    def load(self, config):
        with mock.patch.dict(os.environ, {"QA_SEND_CONFIG": str(config)}):
            return Q.load_config()

    def test_valid_config_is_returned_with_string_headers(self):
        hook, headers = self.load(self.config({"url": "https://hooks.example.com/in", "headers": {"X-Key": 123, "Authorization": "Bearer k"}}))
        self.assertEqual(hook, "https://hooks.example.com/in")
        self.assertEqual(headers, {"X-Key": "123", "Authorization": "Bearer k"})

    def test_headers_may_be_omitted_or_null(self):
        for cfg in ({"url": "https://hooks.example.com/in"}, {"url": "https://hooks.example.com/in", "headers": None}):
            self.assertEqual(self.load(self.config(cfg))[1], {})

    def test_failures_exit_with_a_qa_send_message(self):
        with self.assertRaises(SystemExit) as cm:
            self.load(self.config(mode=0o644))
        self.assertTrue(str(cm.exception.code).startswith("qa-send: "))


class SendPath(SendCase):
    """main() against a local HTTP server. load_config is patched to point at it (the real one insists on https)."""

    def send(self, server, *args, headers=None, stdin_text=None):
        hook = server.url("/hook")
        argv = ["qa-send", *map(str, args)]
        out = io.StringIO()
        patches = [mock.patch.object(sys, "argv", argv), mock.patch.object(Q, "load_config", return_value=(hook, headers or {"Authorization": "Bearer test-key-123"})),
                   mock.patch("urllib.request.getproxies", return_value={})]
        if stdin_text is not None:
            patches.append(mock.patch.object(sys, "stdin", io.StringIO(stdin_text)))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(out))
            err = None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)   # the script exits right after an HTTPError, so it never closes it
                try:
                    Q.main()
                except SystemExit as e:
                    err = e.code
                gc.collect()
        return out.getvalue(), err

    def test_minimal_job_posts_exact_json_and_headers(self):
        with qs.FixtureServer({"/hook": (200, {"Content-Type": "text/plain"}, b"ok")}) as s:
            out, err = self.send(s, "--url", GOOD_URL)
        self.assertIsNone(err)
        self.assertIn("sent (200)", out)
        self.assertEqual(len(s.requests), 1)
        method, path, headers, body = s.requests[0]
        self.assertEqual((method, path), ("POST", "/hook"))
        self.assertEqual(json.loads(body), {"url": GOOD_URL, "depth": "quick"})   # empty fields are left out
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Authorization"], "Bearer test-key-123")

    def test_full_job(self):
        with qs.FixtureServer({"/hook": b"ok"}) as s:
            out, err = self.send(s, "--url", GOOD_URL, "--depth", "release", "--brief", "  Checkout changed; check the basket.  ",
                                 "--project", "Example Shop", "--branch", "feat/basket", "--commit", "abc1234")
        self.assertIsNone(err)
        self.assertEqual(json.loads(s.requests[0][3]), {"url": GOOD_URL, "depth": "release", "brief": "Checkout changed; check the basket.",
                                                         "project": "Example Shop", "branch": "feat/basket", "commit": "abc1234"})

    def test_brief_from_file_and_from_stdin(self):
        f = self.tmp / "brief.txt"
        f.write_text("From a file\nsecond line\n", encoding="utf-8")
        with qs.FixtureServer({"/hook": b"ok"}) as s:
            self.send(s, "--url", GOOD_URL, "--brief-file", f)
            self.send(s, "--url", GOOD_URL, "--brief-file", "-", stdin_text="From stdin\n")
        self.assertEqual(json.loads(s.requests[0][3])["brief"], "From a file\nsecond line")
        self.assertEqual(json.loads(s.requests[1][3])["brief"], "From stdin")

    def test_brief_at_the_limit_is_sent(self):
        with qs.FixtureServer({"/hook": b"ok"}) as s:
            out, err = self.send(s, "--url", GOOD_URL, "--brief", "x" * 4000)
        self.assertIsNone(err)
        self.assertEqual(len(json.loads(s.requests[0][3])["brief"]), 4000)

    def test_refused_jobs_send_nothing(self):
        with qs.FixtureServer({"/hook": b"ok"}) as s:
            for args in (["--url", "http://localhost:3000/"], ["--url", GOOD_URL + "?token=x"], ["--url", GOOD_URL, "--brief", "x" * 4001]):
                out, err = self.send(s, *args)
                self.assertIsInstance(err, str)
            self.assertEqual(s.requests, [])

    def test_a_redirect_from_the_webhook_is_not_followed_and_the_key_goes_nowhere_else(self):
        with qs.FixtureServer({"/capture": b"captured"}) as elsewhere:
            target = elsewhere.url("/capture")
            for status in (301, 302, 303, 307, 308):
                with self.subTest(status), qs.FixtureServer({"/hook": (status, {"Location": target}, b"")}) as s:
                    out, err = self.send(s, "--url", GOOD_URL)
                    self.assertIsInstance(err, str)
                    self.assertIn("send failed", err)
                    self.assertIn(str(status), err)
                    self.assertEqual(len(s.requests), 1)
            self.assertEqual(elsewhere.requests, [], "the redirect target must never be contacted")

    def test_server_errors_and_connection_failures_are_reported_not_retried(self):
        with qs.FixtureServer({"/hook": (500, {}, b"boom")}) as s:
            out, err = self.send(s, "--url", GOOD_URL)
            self.assertIn("send failed", err)
            self.assertEqual(len(s.requests), 1)
        out, err = self.send(s, "--url", GOOD_URL)   # server now closed
        self.assertIn("send failed", err)

    def test_no_redirect_handler_refuses_every_redirect(self):
        self.assertIsNone(Q.NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/x"))

    def test_the_real_opener_uses_the_no_redirect_handler(self):
        seen = {}

        class Fake:
            def open(self, req, timeout=None):
                seen["timeout"] = timeout
                raise OSError("stop here")

        def build(*handlers):
            seen["handlers"] = handlers
            return Fake()

        with mock.patch.object(sys, "argv", ["qa-send", "--url", GOOD_URL]), \
                mock.patch.object(Q, "load_config", return_value=("https://hooks.example.com/in", {})), \
                mock.patch("urllib.request.build_opener", build), self.assertRaises(SystemExit):
            Q.main()
        self.assertIn(Q.NoRedirect, seen["handlers"])
        self.assertEqual(seen["timeout"], 20)


if __name__ == "__main__":
    unittest.main()

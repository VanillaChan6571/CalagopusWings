import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MODULE_PATH = pathlib.Path(__file__).parents[1] / "contract_probe.py"
SPEC = importlib.util.spec_from_file_location("contract_probe", MODULE_PATH)
assert SPEC and SPEC.loader
contract_probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract_probe
SPEC.loader.exec_module(contract_probe)


class ContractProbeTest(unittest.TestCase):
    def test_schema_paths_exclude_values(self):
        shape = contract_probe.schema_paths(
            {"version": "secret-version", "system": {"cpu_threads": 8}, "servers": []}
        )

        self.assertIn("$.version:string", shape)
        self.assertIn("$.system.cpu_threads:number", shape)
        self.assertIn("$.servers:array", shape)
        self.assertNotIn("secret-version", "\n".join(shape))

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(4, contract_probe.percentile([1, 2, 3, 4], 0.95))
        self.assertIsNone(contract_probe.percentile([], 0.95))

    def test_non_loopback_http_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            contract_probe.validate_base_url("http://node.example.test:8080")

    def test_url_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not contain credentials"):
            contract_probe.validate_base_url("https://user:pass@node.example.test")

    def test_report_is_private_and_contains_no_target_or_token(self):
        report = {
            "safety": {"tokens_retained": False},
            "engines": {"catwings": [], "calagopus": []},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "report.json"
            contract_probe.atomic_write_json(path, report)

            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(report, json.loads(path.read_text(encoding="utf-8")))

    def test_comparison_detects_schema_difference(self):
        common = {
            "method": "GET",
            "path": "/api/system?v=2",
            "expected_statuses": [200],
            "statuses": [200],
            "passed": True,
            "samples": 1,
            "successes": 1,
            "failures": 0,
            "min_ms": 1,
            "p50_ms": 1,
            "p95_ms": 1,
            "max_ms": 1,
            "content_type": "application/json",
            "json_type": "object",
            "error_types": [],
        }
        catwings = contract_probe.Observation(
            case="system", json_schema=["$:object", "$.system:object"], **common
        )
        calagopus = contract_probe.Observation(
            case="system", json_schema=["$:object", "$.cpu_count:number"], **common
        )

        result = contract_probe.comparison(
            {"catwings": [catwings], "calagopus": [calagopus]}
        )

        self.assertFalse(result["all_contracts_passed"])
        self.assertFalse(result["cases"]["system"]["same_json_schema"])
        self.assertFalse(result["cases"]["system"]["catwings_schema_supported"])

    def test_probe_exercises_auth_and_retains_only_shape(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                authorization = self.headers.get("Authorization")
                if authorization != "Bearer test-token":
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"credential value must not be retained"}')
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if self.path.startswith("/api/system"):
                    self.wfile.write(
                        b'{"version":"private-version","system":{"cpu_threads":8}}'
                    )
                else:
                    self.wfile.write(b"[]")

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            target = contract_probe.Target(
                "test", f"http://127.0.0.1:{server.server_port}", "test-token"
            )
            observations = contract_probe.probe_target(target, samples=2, timeout=1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertTrue(all(item.passed for item in observations))
        serialized = json.dumps([contract_probe.asdict(item) for item in observations])
        self.assertNotIn("test-token", serialized)
        self.assertNotIn("private-version", serialized)
        self.assertNotIn("credential value", serialized)
        self.assertIn("$.system.cpu_threads:number", serialized)

    def test_redirects_are_not_followed(self):
        class Handler(BaseHTTPRequestHandler):
            redirected_requests = 0

            def do_GET(self):
                if self.path == "/redirected":
                    Handler.redirected_requests += 1
                    self.send_response(200)
                    self.end_headers()
                    return

                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{self.server.server_port}/redirected",
                )
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            target = contract_probe.Target(
                "test", f"http://127.0.0.1:{server.server_port}", "test-token"
            )
            status, _, _, _, _ = contract_probe.request_once(
                target, "GET", "/start", "valid", 1
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(302, status)
        self.assertEqual(0, Handler.redirected_requests)


if __name__ == "__main__":
    unittest.main()

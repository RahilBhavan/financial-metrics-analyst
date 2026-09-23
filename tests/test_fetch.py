import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from financial_metrics.fetch import SECClient, ENDPOINTS, MAX_BYTES, fetch_snapshot, NoRedirect, endpoints_for
from financial_metrics.policy import Refusal


class Response(io.BytesIO):
    def geturl(self):
        return ENDPOINTS["companyfacts.json"]


class FetchTests(unittest.TestCase):
    def client(self, effects):
        self.opener = Mock()
        self.opener.open.side_effect = effects
        self.sleep = Mock()
        return SECClient("TestAgent test@example.test", opener=self.opener, sleep=self.sleep)

    def test_success_and_identifying_header(self):
        client = self.client([Response(b'{"cik":320193}')])
        self.assertEqual(json.loads(client.get("companyfacts.json"))["cik"], 320193)
        request = self.opener.open.call_args[0][0]
        self.assertEqual(request.get_header("User-agent"), "TestAgent test@example.test")
        self.assertEqual(self.opener.open.call_args[1]["timeout"], 10)

    def test_microsoft_uses_only_its_fixed_endpoints(self):
        response = Response(b'{"cik":789019}')
        response.geturl = Mock(return_value=endpoints_for("0000789019")["companyfacts.json"])
        client = SECClient(
            "TestAgent test@example.test",
            "0000789019",
            opener=Mock(open=Mock(return_value=response)),
            sleep=Mock(),
        )
        self.assertEqual(json.loads(client.get("companyfacts.json"))["cik"], 789019)

    def test_unreviewed_refresh_issuer_refused(self):
        with self.assertRaises(Refusal):
            SECClient("TestAgent test@example.test", "0001018724")

    def test_403_fails_without_retry(self):
        client = self.client([urllib.error.HTTPError("", 403, "Forbidden", {}, None)])
        with self.assertRaises(Refusal) as e:
            client.get("companyfacts.json")
        self.assertEqual(e.exception.code, "sec_http_error")
        self.assertEqual(self.opener.open.call_count, 1)

    def test_429_retries_then_succeeds(self):
        client = self.client([urllib.error.HTTPError("", 429, "limit", {}, None), Response(b'{"cik":320193}')])
        self.assertTrue(client.get("companyfacts.json"))
        self.assertEqual(self.opener.open.call_count, 2)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [0.5, 1, 0.5])

    def test_timeout_bounded_to_three_attempts(self):
        client = self.client([TimeoutError()] * 3)
        with self.assertRaises(Refusal) as e:
            client.get("companyfacts.json")
        self.assertEqual(e.exception.code, "sec_unavailable")
        self.assertEqual(self.opener.open.call_count, 3)

    def test_arbitrary_endpoint_blocked_before_network(self):
        client = self.client([])
        with self.assertRaises(Refusal):
            client.get("https://attacker")
        self.opener.open.assert_not_called()

    def test_redirect_blocked(self):
        with self.assertRaises(Refusal):
            NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/secrets")

    def test_response_size_bounded(self):
        client = self.client([Response(b' ' * (MAX_BYTES + 1))])
        with self.assertRaises(Refusal) as e:
            client.get("companyfacts.json")
        self.assertEqual(e.exception.code, "response_too_large")

    def test_invalid_data_refused(self):
        for body in (b'<html>Blocked</html>', b'{"cik":1}', b'[]'):
            with self.subTest(body=body), self.assertRaises(Refusal):
                self.client([Response(body)]).get("companyfacts.json")

    def test_existing_cache_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(Refusal) as e:
                fetch_snapshot(root, "TestAgent test@example.test")
            self.assertEqual(e.exception.code, "target_exists")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_partial_download_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root, patch("financial_metrics.fetch.SECClient") as client:
            output = Path(root) / "snapshot"
            client.return_value.get.side_effect = [b'{"cik":320193}', Refusal("sec_unavailable", "offline")]
            with self.assertRaises(Refusal):
                fetch_snapshot(output, "TestAgent test@example.test")
            self.assertFalse(output.exists())

    def test_invalid_user_agent(self):
        for user_agent in ("", "anonymous", "evil\r\nX: user@example.test"):
            with self.subTest(user_agent=user_agent), self.assertRaises(Refusal):
                SECClient(user_agent)


if __name__ == "__main__":
    unittest.main()

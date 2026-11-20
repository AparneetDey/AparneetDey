import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("update_readme.py")
SPEC = importlib.util.spec_from_file_location("update_readme", SCRIPT_PATH)
update_readme = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_readme)


class MockResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class ApiAuthenticationTests(unittest.TestCase):
    @patch.object(update_readme, "TOKEN", "test-token")
    @patch("urllib.request.urlopen")
    def test_api_get_uses_bearer_authentication(self, urlopen):
        urlopen.return_value = MockResponse([])
        update_readme.api_get("/user/repos")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "test-token")

    @patch.object(update_readme, "TOKEN", "test-token")
    @patch("urllib.request.urlopen")
    def test_api_post_uses_bearer_authentication(self, urlopen):
        urlopen.return_value = MockResponse({"id": 1})
        update_readme.api_post("/repos/example/project/issues", {"title": "Test"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "test-token")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest import mock

from services.page_clicker.dom import extract_clickable_candidates
from services.page_clicker.models import OptionalDependencyMissingError


class _FakeNode:
    def __init__(self, text, attributes=None):
        self._text = text
        self.attributes = attributes or {}

    def text(self):
        return self._text


class _FakeHTMLParser:
    def __init__(self, html):
        self.html = html

    def css(self, tag_name):
        mapping = {
            "button": [_FakeNode("Submit", {"id": "submit-btn"})],
            "a": [_FakeNode("Next")],
            "input": [],
            "summary": [],
        }
        return mapping.get(tag_name, [])


class PageClickerDomTests(unittest.TestCase):
    def test_extract_clickable_candidates_returns_common_interactive_elements(self):
        html = "<button id='submit-btn'>Submit</button><a href='/next'>Next</a>"
        fake_module = mock.Mock(HTMLParser=_FakeHTMLParser)

        with mock.patch.dict("sys.modules", {"selectolax.parser": fake_module}):
            candidates = extract_clickable_candidates(html)

        self.assertEqual(candidates[0]["selector"], "#submit-btn")
        self.assertEqual(candidates[0]["text"], "Submit")
        self.assertEqual(candidates[1]["selector"], "a")
        self.assertEqual(candidates[1]["text"], "Next")

    def test_extract_clickable_candidates_raises_clear_error_when_selectolax_missing(self):
        original_import = __import__

        def _fake_import(name, *args, **kwargs):
            if name == "selectolax.parser":
                raise ModuleNotFoundError("No module named 'selectolax'")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_fake_import):
            with self.assertRaises(OptionalDependencyMissingError):
                extract_clickable_candidates("<button>Go</button>")


if __name__ == "__main__":
    unittest.main()

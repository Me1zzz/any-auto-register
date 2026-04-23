import unittest

from services.page_clicker.dom import extract_clickable_candidates


class PageClickerDomTests(unittest.TestCase):
    def test_extract_clickable_candidates_returns_common_interactive_elements(self):
        html = "<button id='submit-btn'>Submit</button><a href='/next'>Next</a>"
        candidates = extract_clickable_candidates(html)

        self.assertEqual(candidates[0]["selector"], "#submit-btn")
        self.assertEqual(candidates[0]["text"], "Submit")
        self.assertEqual(candidates[1]["selector"], "a")
        self.assertEqual(candidates[1]["text"], "Next")

    def test_extract_clickable_candidates_supports_input_and_summary_without_optional_dependency(self):
        html = "<input id='email' /><summary>Expand</summary>"
        candidates = extract_clickable_candidates(html)

        self.assertEqual(
            candidates,
            [
                {"tag": "input", "selector": "#email", "text": ""},
                {"tag": "summary", "selector": "summary", "text": "Expand"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

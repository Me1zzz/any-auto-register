import unittest

from core.alias_pool.interactive_state_repository import InteractiveStateRepository
from core.alias_pool.interactive_provider_state import InteractiveProviderState
from core.alias_pool.verification_runtime import VerificationRuntimeRequest, classify_verification_requirement


class _MemoryStore:
    def __init__(self, state=None):
        self.state = state

    def load(self, state_key=None):
        return self.state

    def save(self, state, state_key=None):
        self.state = state


class VerificationRuntimeTests(unittest.TestCase):
    def test_classify_account_email_requirement(self):
        request = classify_verification_requirement("account_email", "confirmation_inbox")

        self.assertIsInstance(request, VerificationRuntimeRequest)
        self.assertEqual(request.kind, "account_email")
        self.assertEqual(request.inbox_role, "confirmation_inbox")
        self.assertEqual(request.expected_link_type, "verification")

    def test_classify_magic_link_requirement(self):
        request = classify_verification_requirement("magic_link_login", "confirmation_inbox")

        self.assertEqual(request.kind, "magic_link_login")
        self.assertEqual(request.expected_link_type, "magic_link")

    def test_interactive_provider_state_keeps_browser_runtime_snapshot(self):
        state = InteractiveProviderState()
        state.browser_session = {
            "current_url": "https://example.com/dashboard",
            "cookies": [{"name": "sid", "value": "abc"}],
        }

        self.assertEqual(state.browser_session["current_url"], "https://example.com/dashboard")
        self.assertEqual(state.browser_session["cookies"][0]["name"], "sid")

    def test_repository_preserves_browser_and_verification_state_fields(self):
        persisted = InteractiveProviderState(
            browser_session={"current_url": "https://example.com/dashboard"},
            verification_state={"last_link": "https://example.com/verify?token=abc"},
        )
        repo = InteractiveStateRepository(store=_MemoryStore(state=persisted), state_key="provider-1")

        loaded = repo.load()

        self.assertEqual(loaded.state_key, "provider-1")
        self.assertEqual(loaded.browser_session["current_url"], "https://example.com/dashboard")
        self.assertEqual(loaded.verification_state["last_link"], "https://example.com/verify?token=abc")

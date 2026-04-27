import unittest
from unittest import mock

from services.proxy_switch import switch_proxy_after_account


class CloudmailProxySwitchTests(unittest.TestCase):
    def test_disabled_config_skips_http_request(self):
        request_put = mock.Mock()
        logs: list[str] = []

        result = switch_proxy_after_account(
            {"cloudmail_proxy_switch_enabled": False},
            log_fn=logs.append,
            request_put=request_put,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "disabled")
        request_put.assert_not_called()
        self.assertEqual(logs, [])

    def test_enabled_config_randomly_switches_to_one_configured_node(self):
        response = mock.Mock(status_code=204, text="")
        request_put = mock.Mock(return_value=response)
        chooser = mock.Mock(return_value="proxy-node-b")
        logs: list[str] = []

        result = switch_proxy_after_account(
            {
                "cloudmail_proxy_switch_enabled": True,
                "cloudmail_proxy_switch_proxy_name": "proxy_name",
                "cloudmail_proxy_switch_token": "secret-token",
                "cloudmail_proxy_switch_nodes": "proxy-node-a\nproxy-node-b",
            },
            log_fn=logs.append,
            request_put=request_put,
            chooser=chooser,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.proxy_name, "proxy_name")
        self.assertEqual(result.node_name, "proxy-node-b")
        chooser.assert_called_once_with(["proxy-node-a", "proxy-node-b"])
        request_put.assert_called_once_with(
            "http://127.0.0.1:9097/proxies/proxy_name",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token",
            },
            json={"name": "proxy-node-b"},
            timeout=10,
        )
        self.assertIn(
            "requests.put('http://127.0.0.1:9097/proxies/proxy_name', "
            "headers={'Content-Type': 'application/json', \"Authorization\": f\"Bearer token\"}, "
            'json={"name": "proxy-node-b"})',
            logs,
        )

    def test_missing_required_fields_are_logged_and_do_not_raise(self):
        request_put = mock.Mock()
        logs: list[str] = []

        result = switch_proxy_after_account(
            {
                "cloudmail_proxy_switch_enabled": True,
                "cloudmail_proxy_switch_proxy_name": "proxy_name",
            },
            log_fn=logs.append,
            request_put=request_put,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "missing_config")
        request_put.assert_not_called()
        self.assertIn("[ProxySwitch] 跳过代理切换: token 或节点列表为空", logs)


if __name__ == "__main__":
    unittest.main()

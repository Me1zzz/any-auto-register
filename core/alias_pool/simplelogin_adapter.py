from __future__ import annotations

import re

from core.alias_pool.interactive_provider_models import AliasCreatedRecord, AliasDomainOption
from core.alias_pool.service_adapter_protocol import SiteSessionContext


class SimpleLoginAdapter:
    def __init__(self, *, site_url: str):
        self.site_url = site_url

    def _read_runtime_snapshot(self, runtime) -> dict:
        snapshot = getattr(runtime, "snapshot", lambda: None)()
        if snapshot is None:
            return {}
        return {
            "current_url": getattr(snapshot, "current_url", "") or "",
            "cookies": list(getattr(snapshot, "cookies", []) or []),
            "local_storage": dict(getattr(snapshot, "local_storage", {}) or {}),
            "session_storage": dict(getattr(snapshot, "session_storage", {}) or {}),
        }

    def open_entrypoint(self, runtime):
        login_url = "https://app.simplelogin.io/auth/login"
        if hasattr(runtime, "open"):
            runtime.open(login_url)
        return SiteSessionContext(
            current_url=login_url,
            page_state=self._read_runtime_snapshot(runtime),
            capture_keys=["simplelogin_open_entrypoint"],
        )

    def authenticate_or_register(self, runtime, context):
        page_state = dict(context.page_state or {})
        account_email = str(page_state.get("account_email") or "")
        account_password = str(page_state.get("account_password") or "")
        if hasattr(runtime, "fill") and account_email:
            runtime.fill("#email", account_email)
        if hasattr(runtime, "fill") and account_password:
            runtime.fill("#password", account_password)
        if hasattr(runtime, "click_role"):
            runtime.click_role("button", "Log in")
        elif hasattr(runtime, "click"):
            runtime.click("button:has-text('Log in')")
        if hasattr(runtime, "wait_for_url"):
            runtime.wait_for_url("**/dashboard/**")
        return SiteSessionContext(
            current_url=getattr(runtime, "current_url", lambda: context.current_url)(),
            page_state={**page_state, **self._read_runtime_snapshot(runtime)},
            capture_keys=[*list(context.capture_keys or []), "simplelogin_authenticated"],
        )

    def resolve_blocking_gate(self, runtime, gate, context):
        return context

    def load_alias_surface(self, runtime, context):
        if hasattr(runtime, "open"):
            runtime.open("https://app.simplelogin.io/dashboard/custom_alias")
        if hasattr(runtime, "wait_for_selector"):
            runtime.wait_for_selector("select[name='signed-alias-suffix']")
        page_state = {**dict(context.page_state or {}), **self._read_runtime_snapshot(runtime)}
        if hasattr(runtime, "content"):
            page_state["signed_options_html"] = str(runtime.content() or "")
        return SiteSessionContext(
            current_url=getattr(runtime, "current_url", lambda: "https://app.simplelogin.io/dashboard/custom_alias")(),
            page_state=page_state,
            capture_keys=[*list(context.capture_keys or []), "simplelogin_custom_alias_loaded"],
        )

    def extract_signed_options_from_html(self, html: str) -> list[AliasDomainOption]:
        pattern = re.compile(r'<option[^>]*value="(?P<value>[^"]+)"[^>]*>(?P<text>.*?)</option>', re.IGNORECASE | re.DOTALL)
        options: list[AliasDomainOption] = []
        for match in pattern.finditer(html):
            signed_value = str(match.group("value") or "").strip()
            if not signed_value:
                continue
            domain_segment = signed_value.split(".aeSMmw.", 1)[0]
            at_index = domain_segment.rfind("@")
            if at_index < 0:
                continue
            domain = domain_segment[at_index + 1 :].strip(" .").lower()
            if not domain:
                continue
            options.append(
                AliasDomainOption(
                    key=signed_value,
                    domain=domain,
                    label=f"@{domain}",
                    raw={"signed_value": signed_value, "text": str(match.group("text") or "").strip()},
                )
            )
        if not options:
            raise RuntimeError("signed domain options unavailable")
        return options

    def extract_domain_options(self, runtime, context):
        html = str((context.page_state or {}).get("signed_options_html") or "")
        if not html and hasattr(runtime, "content"):
            html = str(runtime.content() or "")
        return self.extract_signed_options_from_html(html)

    def submit_alias_creation(self, runtime, context, domain_option, alias_index):
        if domain_option is None:
            raise RuntimeError("simplelogin alias creation requires signed domain options")
        prefix = f"real-{alias_index}"
        try:
            if hasattr(runtime, "wait_for_selector"):
                runtime.wait_for_selector("input[placeholder*='Alias prefix']")
            if hasattr(runtime, "fill"):
                runtime.fill("input[placeholder*='Alias prefix']", prefix)
            signed_value = str((domain_option.raw or {}).get("signed_value") or domain_option.key or "")
            if signed_value and hasattr(runtime, "select_option"):
                runtime.select_option("select[name='signed-alias-suffix']", signed_value)
            if hasattr(runtime, "click_role"):
                runtime.click_role("button", "Create")
            elif hasattr(runtime, "click"):
                runtime.click("button:has-text('Create')")
            if hasattr(runtime, "wait_for_text"):
                runtime.wait_for_text(f"Alias {prefix}")
            created_alias = ""
            if hasattr(runtime, "text_content"):
                created_text = str(runtime.text_content("body") or "")
                match = re.search(rf"Alias\s+({re.escape(prefix)}[A-Za-z0-9._@-]+)\s+has been created", created_text)
                if match:
                    created_alias = str(match.group(1) or "")
        except Exception as exc:
            current_url = str(getattr(runtime, "current_url", lambda: context.current_url)() or context.current_url or "")
            raise RuntimeError(f"{exc} [create_stage_url={current_url}]") from exc
        return AliasCreatedRecord(
            email=created_alias or f"{prefix}{domain_option.label}",
            metadata={
                "signed_value": signed_value,
                "runtime_capture_key": "simplelogin_alias_created",
            },
        )

from __future__ import annotations

import random
import re

from .interactive_provider_base import ExistingAccountAliasProviderBase
from .interactive_provider_models import AliasCreatedRecord, AliasDomainOption, AuthenticatedProviderContext


class SimpleLoginProvider(ExistingAccountAliasProviderBase):
    source_kind = "simplelogin"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            confirmation_inbox_email=account["email"],
            real_mailbox_email=account["email"],
            service_password=account["password"],
            username=account["label"],
        )

    def _extract_domain_from_signed_value(self, signed_value: str) -> str:
        value = str(signed_value or "").strip()
        if not value:
            return ""

        domain_segment = value.split(".aeSMmw.", 1)[0]
        at_index = domain_segment.rfind("@")
        if at_index < 0:
            return ""
        return domain_segment[at_index + 1 :].strip(" .").lower()

    def _parse_signed_domain_options(self, html: str) -> list[AliasDomainOption]:
        pattern = re.compile(
            r'<option[^>]*value="(?P<value>[^"]+)"[^>]*>(?P<text>.*?)</option>',
            re.IGNORECASE | re.DOTALL,
        )
        options: list[AliasDomainOption] = []
        for match in pattern.finditer(html):
            signed_value = str(match.group("value") or "").strip()
            text = re.sub(r"\s+", " ", str(match.group("text") or "")).strip()
            domain = self._extract_domain_from_signed_value(signed_value)
            if not signed_value or not domain:
                continue
            options.append(
                AliasDomainOption(
                    key=signed_value,
                    domain=domain,
                    label=f"@{domain}",
                    raw={"signed_value": signed_value, "text": text},
                )
            )
        if not options:
            raise RuntimeError("signed domain options unavailable")
        return options

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return random.choice(domains)

    def _resolve_signed_options_payload(self, context: AuthenticatedProviderContext) -> str:
        session_state = dict(context.session_state or {})
        for value in (
            session_state.get("signed_alias_suffix_html"),
            session_state.get("signed_options_html"),
            session_state.get("signed_alias_suffix_payload"),
            session_state.get("signed_options_payload"),
            self._spec.provider_config.get("signed_alias_suffix_html"),
            self._spec.provider_config.get("signed_options_html"),
            self._spec.provider_config.get("signed_alias_suffix_payload"),
            self._spec.provider_config.get("signed_options_payload"),
        ):
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def discover_alias_domains(self, context: AuthenticatedProviderContext):
        return self._parse_signed_domain_options(self._resolve_signed_options_payload(context))

    def create_alias(self, *, context: AuthenticatedProviderContext, domain, alias_index: int) -> AliasCreatedRecord:
        if domain is None:
            raise RuntimeError("simplelogin alias creation requires signed domain options")
        local = f"simplelogin-{alias_index}"
        return AliasCreatedRecord(email=f"{local}{domain.label}", metadata={"signed_value": domain.raw.get("signed_value", "")})


class SimpleLoginAliasProvider(SimpleLoginProvider):
    pass


def build_simplelogin_provider(spec, context):
    return SimpleLoginProvider(spec=spec, context=context)


def build_simplelogin_alias_provider(spec, context):
    return build_simplelogin_provider(spec, context)

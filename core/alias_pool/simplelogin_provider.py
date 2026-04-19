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

    def _parse_signed_domain_options(self, html: str) -> list[AliasDomainOption]:
        pattern = re.compile(
            r'<option[^>]*value="(?P<value>[^"]+)"[^>]*>(?P<text>.*?)</option>',
            re.IGNORECASE | re.DOTALL,
        )
        options: list[AliasDomainOption] = []
        for match in pattern.finditer(html):
            signed_value = str(match.group("value") or "").strip()
            text = re.sub(r"\s+", " ", str(match.group("text") or "")).strip()
            domain_match = re.search(r"@([A-Za-z0-9.-]+)", text)
            if not signed_value or domain_match is None:
                continue
            domain = domain_match.group(1).lower()
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

    def discover_alias_domains(self, context: AuthenticatedProviderContext):
        raise RuntimeError("simplelogin signed domain discovery requires authenticated custom alias page parsing")

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

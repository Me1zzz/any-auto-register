from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationRuntimeRequest:
    kind: str
    inbox_role: str
    expected_link_type: str


def classify_verification_requirement(kind: str, inbox_role: str) -> VerificationRuntimeRequest:
    expected_link_type = {
        "account_email": "verification",
        "forwarding_email": "forwarding_verification",
        "magic_link_login": "magic_link",
    }.get(kind, "verification")
    return VerificationRuntimeRequest(
        kind=kind,
        inbox_role=inbox_role,
        expected_link_type=expected_link_type,
    )

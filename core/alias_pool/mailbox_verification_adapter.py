from typing import Any


_LINK_BOUNDARY_CHARACTERS = ' \t\r\n\"\'<> '


def build_mailbox_login_request(
    *,
    mailbox_base_url: str,
    mailbox_email: str,
    mailbox_password: str,
) -> dict[str, Any]:
    base_url = str(mailbox_base_url or "").rstrip("/")
    return {
        "method": "POST",
        "url": f"{base_url}/api/login",
        "json": {
            "email": str(mailbox_email),
            "password": str(mailbox_password),
        },
    }


def with_token_in_session_storage(session_storage: dict[str, Any], token: str) -> dict[str, Any]:
    updated_storage = dict(session_storage)
    updated_storage["token"] = str(token)
    return updated_storage


def extract_token_from_storage(session_storage: dict[str, Any]) -> str:
    token = session_storage.get("token")
    if isinstance(token, str):
        return token
    return ""


def build_mailbox_email_list_request(*, mailbox_base_url: str, token: str) -> dict[str, Any]:
    base_url = str(mailbox_base_url or "").rstrip("/")
    return {
        "method": "GET",
        "url": f"{base_url}/api/email/list",
        "params": {
            "accountId": 1,
            "allReceive": 1,
            "emailId": 0,
            "timeSort": 0,
            "size": 100,
            "type": 0,
        },
        "headers": {
            "authorization": str(token),
        },
    }


def _find_link_end_index(message_content: str, start_index: int) -> int:
    end_index = len(message_content)
    for boundary_character in _LINK_BOUNDARY_CHARACTERS:
        boundary_index = message_content.find(boundary_character, start_index)
        if boundary_index >= 0:
            end_index = min(end_index, boundary_index)
    return end_index


def extract_anchored_link_from_message_content(
    message_content: str,
    *,
    link_anchor: str,
) -> str:
    anchor = str(link_anchor or "").strip()
    if not anchor:
        return ""

    content = str(message_content or "")
    start_index = content.find(anchor)
    if start_index < 0:
        return ""

    end_index = _find_link_end_index(content, start_index)
    return content[start_index:end_index]

"""ChatGPT 注册模式适配器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.base_platform import Account, AccountStatus

CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN = "refresh_token"
CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY = "access_token_only"
CHATGPT_REGISTRATION_MODE_CODEX_GUI = "codex_gui"
DEFAULT_CHATGPT_REGISTRATION_MODE = CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN
GUI_CONTROL_EXECUTOR = "gui_control"
CODEX_GUI_VARIANT_DEFAULT = "default"
CODEX_GUI_VARIANT_OFFICIAL_SIGNUP = "official_signup"


@dataclass(frozen=True)
class CodexGUIVariantResolution:
    requested_variant: str
    effective_variant: str
    fallback_reason: str = ""


def normalize_codex_gui_variant(value) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {
        CODEX_GUI_VARIANT_OFFICIAL_SIGNUP,
        "official",
        "official_oauth_signup",
        "official_signup_oauth",
    }:
        return CODEX_GUI_VARIANT_OFFICIAL_SIGNUP
    return CODEX_GUI_VARIANT_DEFAULT


def _has_non_empty_mapping_value(config: dict, key: str, required_keys: tuple[str, ...]) -> bool:
    value = config.get(key)
    if not isinstance(value, dict):
        return False
    return all(str(value.get(required_key) or "").strip() for required_key in required_keys)


def has_cloudmail_team_account_email(extra: Optional[dict]) -> bool:
    extra = extra or {}
    return bool(str(extra.get("cloudmail_team_account_email") or "").strip())


def has_complete_team_workspace_config(extra: Optional[dict]) -> bool:
    extra = extra or {}
    workspace_id = str(
        extra.get("chatgpt_team_workspace_id")
        or extra.get("codex_gui_team_workspace_id")
        or extra.get("team_workspace_id")
        or ""
    ).strip()
    cloudmail_team_email = str(extra.get("cloudmail_team_account_email") or "").strip()
    if cloudmail_team_email:
        return True
    if _has_non_empty_mapping_value(extra, "chatgpt_team_member_account", ("email", "credential")):
        return bool(workspace_id)
    if _has_non_empty_mapping_value(extra, "codex_gui_team_member_account", ("email", "credential")):
        return bool(workspace_id)
    email = str(extra.get("chatgpt_team_member_email") or extra.get("codex_gui_team_member_email") or "").strip()
    credential = str(
        extra.get("chatgpt_team_member_credential")
        or extra.get("codex_gui_team_member_credential")
        or ""
    ).strip()
    return bool(workspace_id and email and credential)


def resolve_codex_gui_variant(extra: Optional[dict]) -> CodexGUIVariantResolution:
    extra = extra or {}
    requested = normalize_codex_gui_variant(
        extra.get("codex_gui_variant")
        or extra.get("chatgpt_gui_oauth_variant")
        or extra.get("codex_gui_oauth_variant")
    )
    if requested != CODEX_GUI_VARIANT_OFFICIAL_SIGNUP:
        return CodexGUIVariantResolution(
            requested_variant=CODEX_GUI_VARIANT_DEFAULT,
            effective_variant=CODEX_GUI_VARIANT_DEFAULT,
        )
    return CodexGUIVariantResolution(
        requested_variant=CODEX_GUI_VARIANT_OFFICIAL_SIGNUP,
        effective_variant=CODEX_GUI_VARIANT_OFFICIAL_SIGNUP,
    )


def normalize_chatgpt_registration_mode(value) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {
        CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
        "access_token",
        "at_only",
        "without_rt",
        "without_refresh_token",
        "no_rt",
        "0",
        "false",
    }:
        return CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY
    if normalized in {
        CHATGPT_REGISTRATION_MODE_CODEX_GUI,
        "codex",
        "codexgui",
        "codex_gui_flow",
        "codex_register_login_gui",
    }:
        return CHATGPT_REGISTRATION_MODE_CODEX_GUI
    if normalized in {
        CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
        "rt",
        "with_rt",
        "has_rt",
        "1",
        "true",
    }:
        return CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN
    return DEFAULT_CHATGPT_REGISTRATION_MODE


def resolve_chatgpt_registration_mode(extra: Optional[dict]) -> str:
    extra = extra or {}
    if "chatgpt_registration_mode" in extra:
        return normalize_chatgpt_registration_mode(extra.get("chatgpt_registration_mode"))
    if "chatgpt_has_refresh_token_solution" in extra:
        return (
            CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN
            if bool(extra.get("chatgpt_has_refresh_token_solution"))
            else CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY
        )
    if str(extra.get("default_executor") or "").strip().lower() == GUI_CONTROL_EXECUTOR:
        return CHATGPT_REGISTRATION_MODE_CODEX_GUI
    return DEFAULT_CHATGPT_REGISTRATION_MODE


@dataclass(frozen=True)
class ChatGPTRegistrationContext:
    email_service: object
    proxy_url: Optional[str]
    callback_logger: Callable[[str], None]
    email: Optional[str]
    password: Optional[str]
    browser_mode: str
    max_retries: int
    extra_config: dict


class BaseChatGPTRegistrationModeAdapter(ABC):
    mode: str

    @abstractmethod
    def _create_engine(self, context: ChatGPTRegistrationContext) -> Any:
        """按模式构造底层注册引擎。"""

    def run(self, context: ChatGPTRegistrationContext):
        engine = self._create_engine(context)
        if engine is None:
            raise RuntimeError(f"未能创建注册引擎: mode={self.mode}")
        if context.email is not None:
            engine.email = context.email
        if context.password is not None:
            engine.password = context.password
        return engine.run()

    def build_account(self, result, fallback_password: str) -> Account:
        return Account(
            platform="chatgpt",
            email=getattr(result, "email", ""),
            password=getattr(result, "password", "") or fallback_password,
            user_id=getattr(result, "account_id", ""),
            token=getattr(result, "access_token", ""),
            status=AccountStatus.REGISTERED,
            extra=self._build_account_extra(result),
        )

    def _build_account_extra(self, result) -> dict:
        extra = {
            "access_token": getattr(result, "access_token", ""),
            "refresh_token": getattr(result, "refresh_token", ""),
            "id_token": getattr(result, "id_token", ""),
            "session_token": getattr(result, "session_token", ""),
            "workspace_id": getattr(result, "workspace_id", ""),
            "chatgpt_registration_mode": self.mode,
            "chatgpt_has_refresh_token_solution": self.mode == CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
            "chatgpt_token_source": getattr(result, "source", "register"),
        }
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            extra.update(metadata)
        return extra


class RefreshTokenChatGPTRegistrationAdapter(BaseChatGPTRegistrationModeAdapter):
    mode = CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN

    def _create_engine(self, context: ChatGPTRegistrationContext):
        from platforms.chatgpt.refresh_token_registration_engine import RefreshTokenRegistrationEngine

        return RefreshTokenRegistrationEngine(
            email_service=context.email_service,
            proxy_url=context.proxy_url,
            callback_logger=context.callback_logger,
            browser_mode=context.browser_mode,
            max_retries=context.max_retries,
            extra_config=context.extra_config,
        )


class AccessTokenOnlyChatGPTRegistrationAdapter(BaseChatGPTRegistrationModeAdapter):
    mode = CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY

    def _create_engine(self, context: ChatGPTRegistrationContext):
        from platforms.chatgpt.access_token_only_registration_engine import AccessTokenOnlyRegistrationEngine

        return AccessTokenOnlyRegistrationEngine(
            email_service=context.email_service,
            proxy_url=context.proxy_url,
            browser_mode=context.browser_mode,
            callback_logger=context.callback_logger,
            max_retries=context.max_retries,
            extra_config=context.extra_config,
        )


class CodexGuiChatGPTRegistrationAdapter(BaseChatGPTRegistrationModeAdapter):
    mode = CHATGPT_REGISTRATION_MODE_CODEX_GUI

    def _create_engine(self, context: ChatGPTRegistrationContext):
        from platforms.chatgpt.codex_gui_registration_engine import CodexGUIRegistrationEngine

        return CodexGUIRegistrationEngine(
            email_service=context.email_service,
            proxy_url=context.proxy_url,
            browser_mode=context.browser_mode,
            callback_logger=context.callback_logger,
            max_retries=context.max_retries,
            extra_config=context.extra_config,
        )


def build_chatgpt_registration_mode_adapter(
    extra: Optional[dict],
) -> BaseChatGPTRegistrationModeAdapter:
    mode = resolve_chatgpt_registration_mode(extra)
    if mode == CHATGPT_REGISTRATION_MODE_CODEX_GUI:
        return CodexGuiChatGPTRegistrationAdapter()
    if mode == CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY:
        return AccessTokenOnlyChatGPTRegistrationAdapter()
    return RefreshTokenChatGPTRegistrationAdapter()

from __future__ import annotations

import time
from typing import Callable


class EmailCodeServiceAdapter:
    """Shared email OTP adapter for GUI register/login workflows."""

    def __init__(self, email_service, email: str, log_fn: Callable[[str], None]):
        """保存邮箱服务、目标邮箱和 OTP 去重所需的状态。"""
        self.email_service = email_service
        self.email = email
        self.log_fn = log_fn
        self._used_codes: set[str] = set()
        self._used_message_ids: set[str] = set()
        self._last_code: str = ""
        self._last_code_at: float = 0.0
        self._last_success_code: str = ""
        self._last_success_code_at: float = 0.0
        self._last_message_id: str = ""
        self._last_success_message_id: str = ""

    @property
    def last_code(self) -> str:
        """返回最近一次成功验证码，若没有则返回最近收到的验证码。"""
        return self._last_success_code or self._last_code

    def _remember_code(self, code: str, *, successful: bool = False) -> None:
        """记录验证码及对应消息 ID，供后续去重和复用。"""
        code = str(code or "").strip()
        if not code:
            return
        now = time.time()
        message_id = str(getattr(self.email_service, "_last_message_id", "") or "").strip()
        self._last_code = code
        self._last_code_at = now
        self._used_codes.add(code)
        self._last_message_id = message_id
        if message_id:
            self._used_message_ids.add(message_id)
        if successful:
            self._last_success_code = code
            self._last_success_code_at = now
            self._last_success_message_id = message_id

    @property
    def uses_cloudmail_message_dedupe(self) -> bool:
        """是否启用按消息 ID 去重，而不是按验证码文本去重。"""
        return bool(getattr(self.email_service, "_cloudmail_message_dedupe", False))

    def build_exclude_codes(self) -> set[str]:
        """构建本次拉码时需要排除的验证码或消息 ID 集合。"""
        if self.uses_cloudmail_message_dedupe:
            return set(self._used_message_ids)
        return set(self._used_codes)

    def remember_successful_code(self, code: str) -> None:
        """显式标记某个验证码已经被验证为成功。"""
        self._remember_code(code, successful=True)

    def get_recent_code(
        self,
        max_age_seconds: int = 180,
        *,
        prefer_successful: bool = True,
    ) -> str:
        """获取最近一段时间内可复用的验证码。"""
        now = time.time()
        if (
            prefer_successful
            and self._last_success_code
            and now - self._last_success_code_at <= max_age_seconds
        ):
            return self._last_success_code
        if self._last_code and now - self._last_code_at <= max_age_seconds:
            return self._last_code
        return ""

    def wait_for_verification_code(
        self,
        email: str,
        timeout: int = 90,
        otp_sent_at: float | None = None,
        exclude_codes=None,
    ):
        """调用底层邮箱服务阻塞等待验证码。"""
        excluded = set(exclude_codes or set())
        self.log_fn(f"正在等待邮箱 {email} 的验证码 ({timeout}s)...")
        code = self.email_service.get_verification_code(
            email=email,
            timeout=timeout,
            otp_sent_at=otp_sent_at,
            exclude_codes=excluded,
        )
        if code:
            code = str(code).strip()
            self._remember_code(code, successful=False)
            self.log_fn(f"成功获取验证码: {code}")
        return code

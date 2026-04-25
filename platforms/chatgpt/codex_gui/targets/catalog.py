from __future__ import annotations


def builtin_dom_target_strategies(name: str) -> list[tuple[str, str]]:
    mapping = {
        "register_button": [("text", "注册"), ("css", "text=注册")],
        "email_input": [("css", "input[placeholder*='电子邮件地址']"), ("css", "input[type='email']")],
        "continue_button": [("role", "继续"), ("text", "继续")],
        "personal_account_option": [("text", "个人帐户"), ("text", "个人账户"), ("text", "Personal account")],
        "password_input": [("css", "input[placeholder*='密码']"), ("css", "input[type='password']")],
        "verification_code_input": [("css", "input[placeholder*='验证码']"), ("css", "input[inputmode='numeric']")],
        "fullname_input": [("css", "input[placeholder*='全名']")],
        "age_input": [("css", "input[placeholder*='年龄']"), ("css", "input[inputmode='numeric']")],
        "complete_account_button": [("role", "完成帐户创建"), ("text", "完成帐户创建")],
        "otp_login_button": [("text", "使用一次性验证码登录")],
        "official_signup_register_button": [("text", "注册"), ("text", "Sign up")],
        "official_signup_email_input": [("css", "input[type='email']"), ("css", "input[name='email']")],
        "official_signup_password_input": [("css", "input[type='password']"), ("css", "input[name='password']")],
        "official_signup_continue_button": [("role", "继续"), ("text", "继续"), ("text", "Continue")],
        "resend_email_button": [("text", "重新发送电子邮件")],
        "retry_button": [("text", "重试")],
    }
    strategies = mapping.get(name)
    if not strategies:
        raise RuntimeError(f"缺少 Codex GUI DOM 目标定义: {name}")
    return strategies


def builtin_uia_target_keywords(name: str) -> list[str]:
    mapping = {
        "register_button": ["注册"],
        "email_input": ["电子邮件地址", "邮箱", "email"],
        "continue_button": ["继续"],
        "personal_account_option": ["个人帐户", "个人账户", "Personal account"],
        "password_input": ["密码", "password"],
        "verification_code_input": ["验证码", "code"],
        "fullname_input": ["全名", "name"],
        "age_input": ["年龄", "age"],
        "complete_account_button": ["完成帐户创建", "完成账户创建"],
        "otp_login_button": ["使用一次性验证码登录"],
        "official_signup_register_button": ["注册", "Sign up"],
        "official_signup_email_input": ["电子邮件地址", "邮箱", "email"],
        "official_signup_password_input": ["密码", "password"],
        "official_signup_continue_button": ["继续", "Continue"],
        "resend_email_button": ["重新发送电子邮件", "重新发送邮件"],
        "retry_button": ["重试"],
    }
    keywords = mapping.get(name)
    if not keywords:
        raise RuntimeError(f"缺少 Codex GUI pywinauto 目标定义: {name}")
    return keywords

"""
通用工具函数模块
"""

from dataclasses import dataclass, field
import logging
import random
import string
import secrets
import hashlib
import base64
import uuid
import re
import time
from urllib.parse import urlparse
from typing import Any, Dict

from .constants import MAX_REGISTRATION_AGE, MIN_REGISTRATION_AGE


logger = logging.getLogger(__name__)


@dataclass
class FlowState:
    """OpenAI Auth/Registration 流程中的页面状态。"""

    page_type: str = ""
    continue_url: str = ""
    method: str = "GET"
    current_url: str = ""
    source: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


def generate_device_id():
    """生成设备唯一标识（oai-did），UUID v4 格式"""
    return str(uuid.uuid4())


def generate_random_password(length=16):
    """生成符合 OpenAI 要求的随机密码"""
    chars = string.ascii_letters + string.digits + "!@#$%"
    pwd = list(
        random.choice(string.ascii_uppercase)
        + random.choice(string.ascii_lowercase)
        + random.choice(string.digits)
        + random.choice("!@#$%")
        + "".join(random.choice(chars) for _ in range(length - 4))
    )
    random.shuffle(pwd)
    return "".join(pwd)


def generate_random_name():
    """随机生成自然的英文姓名，返回 (first_name, last_name)"""
    first = [
        "James", "Robert", "John", "Michael", "David", "William", "Richard", "Joseph", "Thomas", "Charles",
        "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen",
        "Emily", "Emma", "Olivia", "Sophia", "Liam", "Noah", "Oliver", "Ethan", "Ava", "Isabella",
        "Mason", "Logan", "Lucas", "Elijah", "Aiden", "Amelia", "Mia", "Harper", "Evelyn", "Abigail",
        "Alexander", "Benjamin", "Daniel", "Matthew", "Henry", "Samuel", "Jackson", "Sebastian", "Jack", "Owen",
        "Victoria", "Madison", "Scarlett", "Grace", "Chloe", "Penelope", "Riley", "Zoey", "Lily", "Eleanor",
        "Wyatt", "Jayden", "Carter", "Gabriel", "Julian", "Luke", "Anthony", "Isaac", "Dylan", "Leo",
        "Hannah", "Natalie", "Addison", "Aubrey", "Stella", "Bella", "Nora", "Lucy", "Savannah", "Maya",
        "Levi", "David", "Christopher", "Joshua", "Andrew", "Theodore", "Caleb", "Ryan", "Asher", "Nathan",
        "Aria", "Ellie", "Aaliyah", "Aurora", "Paisley", "Nova", "Willow", "Hazel", "Audrey", "Claire",
        "Kareem", "Ray", "Giannis", "Carmelo", "Nate", "Paul", "Charles", "Rick",
        "Elgin", "Dave", "Larry", "Kobe", "Wilt", "Bob", "Dave", "Billy", "Stephen",
        "Anthony", "Dave", "Clyde", "Tim", "Kevin", "Julius", "Patrick", "Walt",
        "Kevin", "George", "Hal", "James", "John", "Elvin", "Allen", "LeBron",
        "Magic", "Sam", "Michael", "Jason", "Kawhi", "Damian", "Jerry", "Karl",
        "Moses", "Pete", "Bob", "Kevin", "George", "Reggie", "Earl", "Steve",
        "Dirk", "Hakeem", "Shaquille", "Robert", "Chris", "Gary", "Bob", "Paul",
        "Scottie", "Willis", "Oscar", "David", "Dennis", "Bill", "Dolph", "Bill",
        "John", "Isiah", "Nate", "Wes", "Dwyane", "Bill", "Jerry", "Russell",
        "Lenny", "Dominique", "James"
    ]
    last = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Wilson", "Anderson", "Taylor", "Thomas", "Hernandez", "Moore", "Martin", "Jackson", "Thompson", "White",
        "Lopez", "Lee", "Gonzalez", "Harris", "Clark", "Lewis", "Robinson", "Walker", "Perez", "Hall",
        "Young", "Allen", "Sanchez", "Wright", "King", "Scott", "Green", "Baker", "Adams", "Nelson",
        "Hill", "Ramirez", "Campbell", "Mitchell", "Roberts", "Carter", "Phillips", "Evans", "Turner", "Torres",
        "Parker", "Collins", "Edwards", "Stewart", "Flores", "Morris", "Nguyen", "Murphy", "Rivera", "Cook",
        "Rogers", "Morgan", "Peterson", "Cooper", "Reed", "Bailey", "Bell", "Gomez", "Kelly", "Howard",
        "Ward", "Cox", "Diaz", "Richardson", "Wood", "Watson", "Brooks", "Bennett", "Gray", "James",
        "Reyes", "Cruz", "Hughes", "Price", "Myers", "Long", "Foster", "Sanders", "Ross", "Morales",
        "Powell", "Sullivan", "Russell", "Ortiz", "Jenkins", "Gutierrez", "Perry", "Butler", "Barnes", "Fisher",
        "Abdul-Jabbar", "Allen", "Antetokounmpo", "Anthony", "Archibald", "Arizin",
        "Barkley", "Barry", "Baylor", "Bing", "Bird", "Bryant", "Chamberlain", "Cousy",
        "Cowens", "Cunningham", "Curry", "Davis", "DeBusschere", "Drexler", "Duncan",
        "Durant", "Erving", "Ewing", "Frazier", "Garnett", "Gervin", "Greer", "Harden",
        "Havlicek", "Hayes", "Iverson", "James", "Johnson", "Jones", "Jordan", "Kidd",
        "Leonard", "Lillard", "Lucas", "Malone", "Malone", "Maravich", "McAdoo",
        "McHale", "Mikan", "Miller", "Monroe", "Nash", "Nowitzki", "Olajuwon",
        "O'Neal", "Parish", "Paul", "Payton", "Pettit", "Pierce", "Pippen", "Reed",
        "Robertson", "Robinson", "Rodman", "Russell", "Schayes", "Sharman",
        "Stockton", "Thomas", "Thurmond", "Unseld", "Wade", "Walton", "West",
        "Westbrook", "Wilkens", "Wilkins", "Worthy"
    ]
    return random.choice(first), random.choice(last)


def generate_random_birthday():
    """生成随机生日字符串，格式 YYYY-MM-DD（20~45岁）"""
    from datetime import datetime

    current_year = datetime.now().year
    year = random.randint(
        current_year - MAX_REGISTRATION_AGE,
        current_year - MIN_REGISTRATION_AGE,
    )
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{year:04d}-{month:02d}-{day:02d}"


def generate_random_age(min_age=20, max_age=60):
    """生成随机年龄整数，默认范围 20~60 岁。"""
    minimum = int(min_age)
    maximum = int(max_age)
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return random.randint(minimum, maximum)


def generate_datadog_trace():
    """生成 Datadog APM 追踪头"""
    trace_id = str(random.getrandbits(64))
    parent_id = str(random.getrandbits(64))
    trace_hex = format(int(trace_id), "016x")
    parent_hex = format(int(parent_id), "016x")
    return {
        "traceparent": f"00-0000000000000000{trace_hex}-{parent_hex}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }


def generate_pkce():
    """生成 PKCE code_verifier 和 code_challenge"""
    code_verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    )
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def decode_jwt_payload(token):
    """解析 JWT token 的 payload 部分"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        import json
        return json.loads(decoded)
    except Exception:
        return {}


def extract_code_from_url(url):
    """从 URL 中提取 authorization code"""
    if not url or "code=" not in url:
        return None
    try:
        from urllib.parse import urlparse, parse_qs
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    except Exception:
        return None


def normalize_page_type(value):
    """将 page.type 归一化为便于分支判断的 snake_case。"""
    return str(value or "").strip().lower().replace("-", "_").replace("/", "_").replace(" ", "_")


def normalize_flow_url(url, auth_base="https://auth.openai.com"):
    """将 continue_url / payload.url 归一化成绝对 URL。"""
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{auth_base.rstrip('/')}{value}"
    return value


def infer_page_type_from_url(url):
    """从 URL 推断流程状态，用于服务端未返回 page.type 时兜底。"""
    if not url:
        return ""

    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()

    if "code=" in (parsed.query or ""):
        return "oauth_callback"
    if "chatgpt.com" in host and "/api/auth/callback/" in path:
        return "callback"
    if "create-account/password" in path:
        return "create_account_password"
    if "email-verification" in path or "email-otp" in path:
        return "email_otp_verification"
    if "about-you" in path:
        return "about_you"
    if "log-in/password" in path:
        return "login_password"
    if "sign-in-with-chatgpt" in path and "consent" in path:
        return "consent"
    if "workspace" in path and "select" in path:
        return "workspace_selection"
    if "organization" in path and "select" in path:
        return "organization_selection"
    if "add-phone" in path:
        return "add_phone"
    if "callback" in path:
        return "callback"
    if "chatgpt.com" in host and path in {"", "/"}:
        return "chatgpt_home"
    if path:
        return normalize_page_type(path.strip("/").replace("/", "_"))
    return ""


def extract_flow_state(data=None, current_url="", auth_base="https://auth.openai.com", default_method="GET"):
    """从 API 响应或 URL 中提取统一的流程状态。"""
    raw = data if isinstance(data, dict) else {}
    page = raw.get("page") or {}
    payload = page.get("payload") or {}

    continue_url = normalize_flow_url(
        raw.get("continue_url") or payload.get("url") or "",
        auth_base=auth_base,
    )
    effective_current_url = continue_url if raw and continue_url else current_url
    current = normalize_flow_url(effective_current_url or continue_url, auth_base=auth_base)
    page_type = normalize_page_type(page.get("type")) or infer_page_type_from_url(continue_url or current)
    method = str(raw.get("method") or payload.get("method") or default_method or "GET").upper()

    return FlowState(
        page_type=page_type,
        continue_url=continue_url,
        method=method,
        current_url=current,
        source="api" if raw else "url",
        payload=payload if isinstance(payload, dict) else {},
        raw=raw,
    )


def describe_flow_state(state: FlowState):
    """生成简短的流程状态描述，便于记录日志。"""
    target = state.continue_url or state.current_url or "-"
    return f"page={state.page_type or '-'} method={state.method or '-'} next={target[:80]}..."


def random_delay(low=0.3, high=1.0):
    """随机延迟"""
    time.sleep(random.uniform(low, high))


_OPENAI_DELAY_HOSTS = (
    "chatgpt.com",
    "auth.openai.com",
    "sentinel.openai.com",
    "api.openai.com",
)

_SESSION_HTTP_METHOD_URL_INDEX = {
    "request": 1,
    "get": 0,
    "post": 0,
    "put": 0,
    "delete": 0,
    "patch": 0,
    "head": 0,
    "options": 0,
}


def is_openai_chatgpt_host(url):
    """判断 URL 是否属于需要施加随机延时的 OpenAI/ChatGPT 域名。"""
    value = str(url or "").strip()
    if not value:
        return False

    try:
        hostname = (urlparse(value).hostname or "").strip().lower()
    except Exception:
        return False

    if not hostname:
        return False

    return any(
        hostname == candidate or hostname.endswith(f".{candidate}")
        for candidate in _OPENAI_DELAY_HOSTS
    )


def sample_openai_post_call_delay():
    """采样 OpenAI/ChatGPT 请求后的随机等待秒数。"""
    return random.uniform(8, 15)


def describe_openai_delay_target(url):
    """将等待日志中的目标 URL 压缩成可读形式。"""
    value = str(url or "").strip()
    if not value:
        return "<unknown>"

    try:
        parsed = urlparse(value)
    except Exception:
        return value

    host = (parsed.netloc or parsed.hostname or "").strip()
    path = (parsed.path or "/").strip() or "/"
    return f"{host}{path}"


def sleep_after_openai_call(url, *, sleeper=time.sleep, sampler=sample_openai_post_call_delay):
    """在 OpenAI/ChatGPT 请求完成后注入 3-6 秒随机等待。"""
    if not is_openai_chatgpt_host(url):
        return

    try:
        delay_seconds = float(sampler())
    except Exception:
        delay_seconds = 15

    message = "OpenAI/ChatGPT 接口等待 %.2f 秒: %s" % (
        delay_seconds,
        describe_openai_delay_target(url),
    )
    logger.info(message)
    print(message)
    sleeper(delay_seconds)


def request_with_openai_post_delay(request_callable, url, *args, **kwargs):
    """执行一次请求，并在 OpenAI/ChatGPT 请求完成后统一等待。"""
    bound_target = getattr(request_callable, "__self__", None)
    if getattr(bound_target, "_openai_post_delay_wrapped", False):
        return request_callable(url, *args, **kwargs)

    response = request_callable(url, *args, **kwargs)
    response_url = getattr(response, "url", None) or url
    sleep_after_openai_call(response_url)
    return response


def wrap_session_request_with_openai_post_delay(session):
    """为 session 常用 HTTP 方法注入 OpenAI/ChatGPT 请求后的随机等待。"""
    if session is None or getattr(session, "_openai_post_delay_wrapped", False):
        return session

    session._openai_post_delay_call_depth = 0

    for method_name, url_arg_index in _SESSION_HTTP_METHOD_URL_INDEX.items():
        original_method = getattr(session, method_name, None)
        if not callable(original_method):
            continue

        def delayed_method(*args, __original_method=original_method, __url_arg_index=url_arg_index, **kwargs):
            prior_depth = int(getattr(session, "_openai_post_delay_call_depth", 0) or 0)
            session._openai_post_delay_call_depth = prior_depth + 1
            response = None
            try:
                response = __original_method(*args, **kwargs)
            finally:
                session._openai_post_delay_call_depth = prior_depth
            if response is None:
                return response
            request_url = ""
            if len(args) > __url_arg_index:
                request_url = args[__url_arg_index]
            response_url = getattr(response, "url", None) or request_url
            if prior_depth == 0:
                sleep_after_openai_call(response_url)
            return response

        setattr(session, method_name, delayed_method)

    session._openai_post_delay_wrapped = True
    return session


def extract_chrome_full_version(user_agent):
    """从 UA 中提取完整的 Chrome 版本号。"""
    if not user_agent:
        return ""
    match = re.search(r"Chrome/([0-9.]+)", user_agent)
    return match.group(1) if match else ""


def _registrable_domain(hostname):
    """粗略提取可注册域名，用于推断 Sec-Fetch-Site。"""
    if not hostname:
        return ""
    host = hostname.split(":")[0].strip(".").lower()
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return ".".join(parts)
    return ".".join(parts[-2:])


def infer_sec_fetch_site(url, referer=None, navigation=False):
    """根据目标 URL 和 Referer 推断 Sec-Fetch-Site。"""
    if not referer:
        return "none" if navigation else "same-origin"

    try:
        target = urlparse(url or "")
        source = urlparse(referer or "")

        if not target.scheme or not target.netloc or not source.netloc:
            return "none" if navigation else "same-origin"

        if (target.scheme, target.netloc) == (source.scheme, source.netloc):
            return "same-origin"

        if _registrable_domain(target.hostname) == _registrable_domain(source.hostname):
            return "same-site"
    except Exception:
        pass

    return "cross-site"


def build_sec_ch_ua_full_version_list(sec_ch_ua, chrome_full_version):
    """根据 sec-ch-ua 生成 sec-ch-ua-full-version-list。"""
    if not sec_ch_ua or not chrome_full_version:
        return ""

    entries = []
    for brand, version in re.findall(r'"([^"]+)";v="([^"]+)"', sec_ch_ua):
        full_version = chrome_full_version if brand in {"Chromium", "Google Chrome"} else f"{version}.0.0.0"
        entries.append(f'"{brand}";v="{full_version}"')

    return ", ".join(entries)


def build_browser_headers(
    *,
    url,
    user_agent,
    sec_ch_ua=None,
    chrome_full_version=None,
    accept=None,
    accept_language="en-US,en;q=0.9",
    referer=None,
    origin=None,
    content_type=None,
    navigation=False,
    fetch_mode=None,
    fetch_dest=None,
    fetch_site=None,
    headed=False,
    extra_headers=None,
):
    """构造更接近真实 Chrome 有头浏览器的请求头。"""
    chrome_full = chrome_full_version or extract_chrome_full_version(user_agent)
    full_version_list = build_sec_ch_ua_full_version_list(sec_ch_ua, chrome_full)

    headers = {
        "User-Agent": user_agent or "Mozilla/5.0",
        "Accept-Language": accept_language,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-arch": '"x86"',
        "sec-ch-ua-bitness": '"64"',
    }

    if accept:
        headers["Accept"] = accept
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    if content_type:
        headers["Content-Type"] = content_type
    if sec_ch_ua:
        headers["sec-ch-ua"] = sec_ch_ua
    if chrome_full:
        headers["sec-ch-ua-full-version"] = f'"{chrome_full}"'
        headers["sec-ch-ua-platform-version"] = '"15.0.0"'
    if full_version_list:
        headers["sec-ch-ua-full-version-list"] = full_version_list

    if navigation:
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-User"] = "?1"
        headers["Upgrade-Insecure-Requests"] = "1"
        headers["Cache-Control"] = "max-age=0"
    else:
        headers["Sec-Fetch-Dest"] = fetch_dest or "empty"
        headers["Sec-Fetch-Mode"] = fetch_mode or "cors"

    headers["Sec-Fetch-Site"] = fetch_site or infer_sec_fetch_site(url, referer, navigation=navigation)

    if headed:
        headers.setdefault("Priority", "u=0, i" if navigation else "u=1, i")
        headers.setdefault("DNT", "1")
        headers.setdefault("Sec-GPC", "1")

    if extra_headers:
        for key, value in extra_headers.items():
            if value is not None:
                headers[key] = value

    return headers


def seed_oai_device_cookie(session, device_id):
    """在 ChatGPT / OpenAI 相关域上同步设置 oai-did。"""
    for domain in (
        "chatgpt.com",
        ".chatgpt.com",
        "openai.com",
        ".openai.com",
        "auth.openai.com",
        ".auth.openai.com",
    ):
        try:
            session.cookies.set("oai-did", device_id, domain=domain)
        except Exception:
            continue

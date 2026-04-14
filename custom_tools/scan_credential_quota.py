#!/usr/bin/env python3
"""Scan JSON credential files and print quota-related information.

This script is intentionally read-only. It does not call undocumented remote
OpenAI/Codex quota endpoints. Instead, it prints the quota-related information
that can be derived reliably from local credential/auth JSON files:

- provider/type
- email / label / file name
- JWT-derived plan/account identity when present
- token expiry when present
- locally tracked quota/cooldown state when present in the JSON file

It supports both one-shot scanning and polling via --watch.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def safe_console_text(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def safe_print(text: str = "") -> None:
    print(safe_console_text(text))


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        value = json.loads(decoded.decode("utf-8"))
        if isinstance(value, dict):
            return value
    except Exception:
        return {}
    return {}


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_unix_timestamp(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    except (OverflowError, OSError, ValueError):
        return "-"


def safe_get(mapping: Any, key: str, default: Any = None) -> Any:
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return default


@dataclass
class CredentialSummary:
    path: Path
    provider: str = "unknown"
    cred_type: str = "unknown"
    label: str = ""
    email: str = ""
    account_id: str = ""
    plan_type: str = ""
    expired_at: Optional[datetime] = None
    id_token_exp: Optional[int] = None
    access_token_exp: Optional[int] = None
    quota_exceeded: Optional[bool] = None
    quota_reason: str = ""
    next_recover_at: Optional[datetime] = None
    backoff_level: Optional[int] = None
    model_quotas: List[Tuple[str, bool, str, Optional[datetime], Optional[int]]] = field(
        default_factory=list
    )
    raw_has_quota: bool = False
    remote_status: str = "NOT_PROBED"
    remote_http_status: Optional[int] = None
    remote_error_type: str = ""
    remote_error_message: str = ""
    remote_reset_at: Optional[datetime] = None
    remote_reset_in_seconds: Optional[int] = None
    remote_latency_ms: Optional[int] = None
    remote_output_text: str = ""
    probe_attempts: int = 0
    initially_usable: bool = False
    error: str = ""


def summarize_credential(path: Path) -> CredentialSummary:
    summary = CredentialSummary(path=path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        summary.error = f"读取或解析失败: {exc}"
        return summary

    if not isinstance(raw, dict):
        summary.error = "JSON 顶层不是对象"
        return summary

    summary.provider = str(raw.get("provider") or raw.get("type") or "unknown")
    summary.cred_type = str(raw.get("type") or raw.get("provider") or "unknown")
    summary.label = str(raw.get("label") or "")
    summary.email = str(raw.get("email") or "")

    metadata = safe_get(raw, "metadata", {})
    if not summary.email:
        summary.email = str(safe_get(metadata, "email", "") or "")

    summary.account_id = str(raw.get("account_id") or "")
    summary.expired_at = parse_iso_datetime(raw.get("expired"))

    quota = safe_get(raw, "quota")
    if isinstance(quota, dict):
        summary.raw_has_quota = True
        exceeded = quota.get("exceeded")
        summary.quota_exceeded = bool(exceeded) if isinstance(exceeded, bool) else None
        summary.quota_reason = str(quota.get("reason") or "")
        summary.next_recover_at = parse_iso_datetime(quota.get("next_recover_at"))
        backoff = quota.get("backoff_level")
        summary.backoff_level = backoff if isinstance(backoff, int) else None

    model_states = safe_get(raw, "model_states", {})
    if isinstance(model_states, dict):
        for model_name, model_state in sorted(model_states.items()):
            if not isinstance(model_state, dict):
                continue
            model_quota = safe_get(model_state, "quota", {})
            if not isinstance(model_quota, dict):
                continue
            exceeded = model_quota.get("exceeded")
            reason = str(model_quota.get("reason") or "")
            next_recover = parse_iso_datetime(model_quota.get("next_recover_at"))
            backoff = model_quota.get("backoff_level")
            summary.model_quotas.append(
                (
                    str(model_name),
                    bool(exceeded) if isinstance(exceeded, bool) else False,
                    reason,
                    next_recover,
                    backoff if isinstance(backoff, int) else None,
                )
            )

    id_token = str(raw.get("id_token") or "")
    access_token = str(raw.get("access_token") or "")

    id_claims = decode_jwt_payload(id_token) if id_token else {}
    access_claims = decode_jwt_payload(access_token) if access_token else {}

    auth_claims = safe_get(id_claims, "https://api.openai.com/auth", {})
    if not isinstance(auth_claims, dict):
        auth_claims = {}

    if not summary.email:
        summary.email = str(id_claims.get("email") or access_claims.get("email") or "")
    if not summary.account_id:
        summary.account_id = str(
            auth_claims.get("chatgpt_account_id")
            or safe_get(access_claims, "https://api.openai.com/auth", {}).get(
                "chatgpt_account_id", ""
            )
            or ""
        )
    summary.plan_type = str(
        auth_claims.get("chatgpt_plan_type")
        or safe_get(access_claims, "https://api.openai.com/auth", {}).get(
            "chatgpt_plan_type", ""
        )
        or ""
    )

    id_exp = id_claims.get("exp")
    access_exp = access_claims.get("exp")
    summary.id_token_exp = int(id_exp) if isinstance(id_exp, (int, float)) else None
    summary.access_token_exp = int(access_exp) if isinstance(access_exp, (int, float)) else None

    return summary


def render_quota_state(summary: CredentialSummary) -> str:
    if summary.quota_exceeded is True:
        return "EXCEEDED"
    if summary.quota_exceeded is False:
        return "OK"
    if summary.raw_has_quota:
        return "UNKNOWN"
    return "NO_LOCAL_QUOTA_FIELD"

x = [
"你好", "早安", "午安", "晚安", "你好呀", "好久不见", "最近好吗", "回头见", "拜拜", "保重",
    "干杯", "加油", "幸会", "祝好", "平安", "在此", "哈喽", "嘿嘿", "吃了没", "去哪",

    # --- 韩语 (Korean - 罗马音/意译参考) ---
    "안녕 (安宁)", "잘 가 (走好)", "반가워 (见到你很高兴)", "잘 자 (晚安)", "하이 (Hi)",
    "열공 (努力学习)", "화이팅 (加油)", "잘 지내? (过得好吗)", "축하해 (祝贺)", "식사해 (吃饭吧)",
    "대박 (大发)", "진짜? (真的吗)", "여보세요 (喂)", "고마워 (谢谢)", "미안 (抱歉)",

    # --- 日语 (Japanese - 罗马音参考) ---
    "おっす (哟)", "おはよ (早)", "ちわ (午好简写)", "ばんわ (晚好简写)", "じゃね (再见)",
    "またね (回头见)", "元気? (还好吗)", "お疲れ (辛苦了)", "よろしく (请多指教)", "おやすみ (晚安)",
    "どうも (谢了/你好)", "やあ (呀)", "もしもし (喂)", "いいよ (可以哟)", "最高 (最高)",

    # --- 英语 (English) ---
    "Hello", "Hi there", "Hey you", "Good day", "Morning", "Night", "See ya", "Take care",
    "Cheers", "What's up", "Howdy", "Peace", "Stay safe", "Big hug", "Well done",
    "So long", "Bye bye", "Catch ya", "Be well", "All good",

    # --- 法语 (French) ---
    "Salut", "Coucou", "Bonjour", "Bonsoir", "Bonne nuit", "À plus", "À bientôt", "Ça va?",
    "Au revoir", "Merci", "De rien", "Pardon", "Courage", "Santé", "Bienvenue",
    "Bisous", "Adieu", "C'est ça", "D'accord", "Tiens",

    # --- 德语 (German) ---
    "Hallo", "Moin Moin", "Servus", "Grüß Gott", "Guten Tag", "Gute Nacht", "Bis dann", "Tschüss",
    "Mach's gut", "Alles klar?", "Hau rein", "Schönen Tag", "Viel Glück", "Prost", "Danke",
    "Bitte", "Willkommen", "Na?", "Bis bald", "Ciao",
    "Hi", "你好", "早上好", "最近怎么样？", "在吗？",
"在吗", "幸会", "久仰", "久违", "别来无恙", "回见", "慢走", "多保重", "祝顺遂", "瑞思拜",
    "借过", "请教", "客气了", "哪里话", "失陪", "多谢", "劳驾", "您好", "给力", "挺好",
    "不错", "万福", "安好", "共勉", "握手", "点赞", "好梦", "醒啦", "在忙吗", "出来玩",
    "喝一杯", "有空聚", "等下见", "这就来", "收到了", "没问题", "必须的", "承让", "受教", "回聊",

    # --- 英语 (English) - 41-80 ---
    "Yo", "Sup", "Stay gold", "Best", "Regards", "Later", "Take it easy", "Good luck", "Keep it up", "My bad",
    "No worries", "You bet", "Anytime", "Stay cool", "Keep real", "Farewell", "Cheerio", "Peace out", "Long time", "How's life",
    "G'day", "Alright", "Nice one", "Stay busy", "Rest up", "Feel better", "Safe travels", "Sweet dreams", "High five", "Warm wishes",
    "Big love", "Miss ya", "Text me", "Call me", "Rock on", "Godspeed", "Be brave", "Stay strong", "Keep smiling", "Happy days",

    # --- 日语 (Japanese) - 81-120 ---
    "失礼します", "お待たせ", "久しぶり", "元気出して", "お大事に", "また明日", "頑張れ", "了解です", "おめでとう", "さすが",
    "楽しみ", "いい天気", "いってら", "おかえり", "お邪魔します", "また後で", "お先に", "ゆっくり", "落ち着いて", "よかった",
    "最高です", "いいよ", "もちろん", "任せて", "大丈夫", "助かる", "いかが？", "どうぞ", "よろしくね", "ごめんね",
    "それな", "お疲れ様", "おは", "こんちゃ", "ういっす", "あざす", "おめ", "乙です", "やっほー", "元気？",

    # --- 韩语 (Korean) - 121-160 ---
    "축하 (祝贺)", "힘내 (加油)", "잘했어 (做的好)", "대박 (大发)", "진짜 (真的)", "정말 (确实)", "좋아 (好啊)", "싫어 (不要)", "가자 (走吧)", "빨리 (快点)",
    "기다려 (等下)", "보고싶어 (想你)", "반가워요 (高兴)", "잘있어 (再见)", "다음에 (下次)", "내일 봐 (明天见)", "아자아자 (加油声)", "행복해 (幸福)", "사랑해 (爱你)", "감사 (感谢)",
    "괜찮아 (没事)", "어머 (哎呀)", "그래 (是嘛)", "맞아 (对的)", "여보 (亲爱的)", "자기야 (宝贝)", "친구 (朋友)", "형 (哥)", "누나 (姐)", "언니 (姐)",
    "오빠 (哥)", "동생 (弟妹)", "선배 (前辈)", "후배 (后辈)", "쌤 (老师)", "헐 (晕)", "굿 (Good)", "오예 (Oh Yeah)", "하이루 (Hi-ru)", "방가 (Bang-ga)",

    # --- 法语 (French) - 161-180 ---
    "Enchanté", "À tout", "À l'aide", "Ça roule?", "Pas mal", "Bien sûr", "C'est bon", "Tout va bien", "Bon courage", "Bon voyage",
    "À demain", "Bonne fête", "Tchin-tchin", "Quelle joie", "Bien dit", "T'inquiète", "Gros bisous", "À ce soir", "Salut toi", "Allez",

    # --- 德语 (German) - 181-200 ---
    "Guten Morgen", "Guten Abend", "Alles Gute", "Viel Erfolg", "Mach's flott", "Sehr gut", "Na klar", "Freut mich", "Schönes WE", "Passt schon",
    "Bis gleich", "Bis später", "Schlaf gut", "Gesundheit", "Viel Spaß", "Willkommen", "Liebe Grüße", "Mahlzeit", "Servus", "Grüß dich",
    "你是谁", "你叫什么名字？", "你是机器人吗？", "你的开发者是谁？", "你能帮我做什么？",
    "助理是什么？", "AI 的定义是什么？", "什么是大语言模型？", "你会写代码吗？", "你会翻译吗？",
    "Python是什么", "Java 和 Python 有什么区别？", "怎么学习编程？", "什么是 API？", "什么是数据库？",
    "what is java", "how to code", "hello world", "C++ 难吗？", "什么是前端开发？",
    "今天天气怎么样？", "现在几点了？", "给我讲个笑话", "推荐一部电影", "怎么做红烧肉？",
    "什么是区块链？", "元宇宙是什么意思？", "什么是量子计算？", "解释一下相对论", "黑洞是什么？",
    "如何提高工作效率？", "怎么克服拖延症？", "冥想有什么好处？", "如何保持健康？", "什么是情绪价值？",
    "笑死", "绝了", "真的", "确实", "可以", "好滴", "求撩", "面基", "扩列", "蹲个",
    "心碎", "给力", "开黑", "带飞", "躺平", "内卷", "硬核", "种草", "拔草", "安利",
    "Hey yo", "What's new", "Got it", "Try it", "For real", "No biggie", "On it", "Not yet", "Go on", "Move on",
    "Stay cool", "Be real", "Love it", "Nice job", "Well done", "Keep calm", "So far", "Day one", "Best way", "Look up",
    "すみません", "どうぞ", "だめだ", "おもしろい", "かわいい", "やばい", "おいしい", "大好き", "知らん", "うそだ",
    "うれしい", "がんばれ", "しあわせ", "ちょっと", "きれい", "最高だ", "安心し", "まじで", "やっぱり", "そうだね",
    "정말요", "좋아요", "싫어요", "힘내요", "고마워요", "미안해요", "괜찮아", "알았어", "빨리", "천천히",
    "기다려", "보여줘", "사랑해", "보고파", "대박나", "진심", "깜짝", "어머나", "심쿵", "행복해",
    "C'est la vie", "Pas de quoi", "Ça marche", "Bien sûr", "À table", "Je t'aime", "D'accord", "C'est top", "À demain", "Vite vite",
    "Miam miam", "Bon courage", "Ça suffit", "C'est faux", "Tout va", "Sans blague", "Dis donc", "Bon voyage", "Petit à", "Tout doux",
    "Viel Erfolg", "Keine Angst", "Bis gleich", "Alles klar", "Freut mich", "Schönen Tag", "Wie geht's", "Gute Fahrt", "Viel Spaß", "Auf geht's",
    "Einfach so", "Komm her", "Nicht wahr", "Ganz gut", "Schon gut", "Na klar", "Was ist", "Sehr gut", "Keine Ahnung"
    "帮我写一封感谢信", "如何写个人简历？", "周报怎么写？", "请假条范本", "帮我润色这段文字",
    "北京有哪些景点？", "去日本旅游需要注意什么？", "最快的交通工具是什么？", "什么是签证？", "推荐一个度假胜地",
    "什么是通货膨胀？", "股票和基金的区别？", "如何理财？", "什么是复利？", "比特币是什么？",
    "地球的周长是多少？", "光速是多少？", "谁发现了万有引力？", "恐龙为什么灭绝？", "人类的起源是什么？",
    "你会说英语吗？", "法语的你好怎么说？", "帮我翻译成德语", "日语入门难吗？", "韩语怎么写？",
    "什么是碳中和？", "全球变暖的影响？", "如何保护环境？", "什么是垃圾分类？", "可再生能源有哪些？",
    "你会玩游戏吗？", "什么是 NPC？", "推荐几款好玩的游戏", "电竞是什么？", "虚拟现实是什么？",
    "什么是人工智能伦理？", "AI 会取代人类吗？", "什么是深度学习？", "神经网络的工作原理？", "什么是图灵测试？",
    "如何写诗？", "给我一段励志名言", "鲁迅是谁？", "什么是浪漫主义？", "莎士比亚的作品有哪些？",
    "什么是 5G？", "芯片是怎么制造的？", "什么是物联网？", "自动驾驶技术成熟吗？", "什么是云计算？",
    "今天心情不好怎么办？", "如何缓解压力？", "什么是心理咨询？", "晚安", "再见", "期待下次聊天",
    "不客气", "没事", "好的", "收到", "明白", "请教", "救命", "帮我", "谁呀", "在哪",
    "干嘛", "怎么了", "真的吗", "太棒了", "厉害", "加油", "抱抱", "点赞", "闭嘴", "求助",
    "查天气", "讲笑话", "写诗", "翻译", "唱歌", "跳舞", "画画", "算账", "搜索", "提醒",
    "Python", "Java", "代码", "编程", "算法", "函数", "变量", "对象", "数组", "列表",
    "字典", "集合", "类名", "接口", "数据", "网络", "系统", "软件", "硬件", "手机",
    "电脑", "芯片", "快讯", "新闻", "百科", "电影", "音乐", "游戏", "动漫", "小说",
    "美食", "做菜", "外卖", "火锅", "烧烤", "咖啡", "奶茶", "水果", "蔬菜", "零食",
    "旅游", "订票", "酒店", "地图", "路线", "打车", "公交", "飞机", "火车", "走路",
    "健身", "跑步", "游泳", "瑜伽", "篮球", "足球", "羽球", "减脂", "健康", "医生",
    "感冒", "发烧", "过敏", "头痛", "医生", "挂号", "检查", "开药", "护肤", "化妆",
    "穿搭", "买衣服", "打折", "省钱", "理财", "股票", "基金", "利息", "汇率", "赚钱",
    "工作", "面试", "简历", "入职", "离职", "加班", "周报", "开会", "老板", "同事",
    "学习", "考试", "作业", "大学", "专业", "考研", "留学", "英语", "单词", "语法",
    "情绪", "压力", "焦虑", "开心", "难过", "生气", "失眠", "做梦", "恋爱", "分手",
    "结婚", "生日", "礼物", "聚会", "电影院", "博物馆", "图书馆", "公园", "超市", "医院",
    "银行", "学校", "商场", "餐厅", "洗手间", "红绿灯", "斑马线", "垃圾桶", "充电宝", "电梯",
    "说明书", "遥控器", "投影仪", "打印机", "麦克风", "摄像头", "耳机", "键盘", "鼠标", "屏幕",
    "壁纸", "铃声", "账号", "密码", "验证码", "权限", "登录", "注册", "退出", "删除",
    "撤销", "保存", "分享", "收藏", "搜索框", "进度条", "对话框", "朋友圈", "点赞党", "打工魂",
"你好", "再见", "早安", "晚安", "多谢", "请问", "好的", "没事", "加油", "保重",
    "抱歉", "欢迎", "借光", "借过", "干杯", "幸会", "久仰", "请坐", "走吧", "酷喔",
    "Hello", "Hi there", "Bye bye", "See ya", "Good day", "Morning", "Night", "Cheers", "Thanks", "Sorry",
    "Pardon", "Excuse", "Indeed", "Alright", "Welcome", "Take care", "Not bad", "So what", "Tell me", "Help me",
    "こんにちは", "おはよ", "またね", "おやすみ", "元気？", "どうぞ", "サンキュ", "もしもし", "失礼", "じゃあね",
    "あけおめ", "お疲れ", "最高", "本当？", "大丈夫", "すごい", "やはり", "なるほど", "お願い", "ごめん",
    "안녕", "반가워", "잘가", "굿모닝", "잘자", "수고해", "고마워", "미안해", "축하해", "화이팅",
    "여보세요", "진짜?", "그래요", "몰라요", "좋아요", "싫어요", "대박", "짱이야", "어서와", "힘내",
    "Salut", "Allo", "Merci", "De rien", "Pardon", "Coucou", "Au revoir", "Bonsoir", "Ça va?", "À plus",
    "Bonne nuit", "À bientôt", "S'il vous", "Bravo", "D'accord", "C'est bon", "Super", "Génial", "Enchanté", "Pitié",
    "Hallo", "Guten Tag", "Morgen", "Tschüss", "Danke", "Bitte", "Ja klar", "Genau", "Vielleicht", "Echt?",
    "Viel Glück", "Na und?", "Schade", "Prost", "Bis bald", "Viel Spaß", "Willkommen", "Gesundheit", "Super", "Prima",
    "嘿嘿", "哈喽", "嘿咻", "亲亲", "么么", "乖乖", "对哒", "没错", "是吗", "看看",
    "Whats up", "Look out", "Be kind", "Keep up", "Oh boy", "Oh my", "Wake up", "Stay safe", "Big hug", "Love you",
    "はじめ", "よろしく", "かもね", "いいね", "わかった", "待って", "早く", "行こう", "元気で", "また明日",
    "가지마", "기다려", "나중에", "어떻게", "언제든", "괜찮아", "맞아요", "깜짝아", "세상에", "보고싶어",
    "Tiens", "C'est ça", "Par ici", "Par là", "Bien sûr", "Pourquoi", "Vraiment", "Pas mal", "C'est vrai", "Tranquille",
    "Alles gut", "Gute Nacht", "Bis dann", "Mach's gut", "Kein Ding", "Ich weiß", "Wirklich?", "Komm schon", "Nicht jetzt", "Halt stop",
    "吃了吗", "去哪儿", "回头见", "真棒", "太酷", "想你", "给力", "冲鸭", "开心", "放松",
    "Way to go", "Check it", "No way", "Of course", "Just wait", "I see", "My bad", "Good luck", "All set", "Fair enough"
  ]
import random
def build_probe_request(summary: CredentialSummary, model: str) -> Tuple[str, bytes, Dict[str, str]]:
    url = "https://chatgpt.com/backend-api/codex/responses"
    payload = {
        "model": model,
        "instructions": "",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": x[random.randint(0, len(x) - 1)],
                    }
                ],
            }
        ],
        "stream": True,
        "store": False,
        "parallel_tool_calls": True,
        "reasoning": {"effort": "medium", "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
    }
    access_token = ""
    try:
        raw = json.loads(summary.path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            access_token = str(raw.get("access_token") or "")
            if not access_token:
                metadata = safe_get(raw, "metadata", {})
                access_token = str(safe_get(metadata, "access_token", "") or "")
            base_url = ""
            attributes = safe_get(raw, "attributes", {})
            if isinstance(attributes, dict):
                base_url = str(attributes.get("base_url") or "")
            if base_url.strip():
                url = base_url.rstrip("/") + "/responses"
    except Exception:
        pass

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Originator": "codex_cli_rs",
        "User-Agent": "codex_cli_rs/0.116.0 (Windows; probe)",
        "Connection": "Keep-Alive",
    }
    if summary.account_id:
        headers["Chatgpt-Account-Id"] = summary.account_id
    return url, json.dumps(payload).encode("utf-8"), headers


def parse_remote_reset(error_obj: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[int]]:
    resets_at = error_obj.get("resets_at")
    reset_at = None
    if isinstance(resets_at, (int, float)):
        try:
            reset_at = datetime.fromtimestamp(int(resets_at), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            reset_at = None

    resets_in_seconds = error_obj.get("resets_in_seconds")
    reset_in = int(resets_in_seconds) if isinstance(resets_in_seconds, (int, float)) else None
    return reset_at, reset_in


def extract_error_fields(body_json: Dict[str, Any]) -> Tuple[str, str, Optional[datetime], Optional[int]]:
    error_obj = safe_get(body_json, "error", {}) if isinstance(body_json, dict) else {}
    if not isinstance(error_obj, dict):
        error_obj = {}

    error_type = str(safe_get(error_obj, "type", "") or "")
    error_message = str(
        safe_get(error_obj, "message", "")
        or safe_get(body_json, "detail", "")
        or safe_get(body_json, "message", "")
        or ""
    )
    reset_at, reset_in = parse_remote_reset(error_obj)
    return error_type, error_message, reset_at, reset_in


def _collect_output_text_from_obj(value: Any, parts: List[str]) -> None:
    if isinstance(value, dict):
        value_type = value.get("type")
        text_value = value.get("text")
        if value_type in {"output_text", "text"} and isinstance(text_value, str) and text_value:
            parts.append(text_value)
        output_text = value.get("output_text")
        if isinstance(output_text, str) and output_text:
            parts.append(output_text)
        delta = value.get("delta")
        if isinstance(delta, str) and delta:
            parts.append(delta)
        for nested in value.values():
            _collect_output_text_from_obj(nested, parts)
    elif isinstance(value, list):
        for item in value:
            _collect_output_text_from_obj(item, parts)


def dedupe_preserve_order(parts: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_output_text_from_success_body(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    parts: List[str] = []
    completed_parts: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        event_type = str(event.get("type") or "")
        if event_type == "response.completed":
            _collect_output_text_from_obj(event, completed_parts)
        else:
            _collect_output_text_from_obj(event, parts)

    selected = dedupe_preserve_order(completed_parts or parts)
    return "\n".join(selected)


def should_retry(summary: CredentialSummary) -> bool:
    return summary.remote_status != "USABLE"


def probe_credential(summary: CredentialSummary, model: str, timeout_seconds: float, insecure: bool) -> CredentialSummary:
    if summary.error:
        summary.remote_status = "SKIPPED_LOCAL_ERROR"
        return summary

    url, payload, headers = build_probe_request(summary, model)
    token_value = headers.get("Authorization", "")
    if token_value == "Bearer ":
        summary.remote_status = "NO_ACCESS_TOKEN"
        return summary

    request = urllib.request.Request(url=url, data=payload, headers=headers, method="POST")
    started = time.perf_counter()
    context = None
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
            body = response.read()
            summary.remote_http_status = response.getcode()
            summary.remote_latency_ms = int((time.perf_counter() - started) * 1000)
            if 200 <= response.getcode() < 300:
                summary.remote_status = "USABLE"
                summary.remote_error_type = ""
                summary.remote_error_message = ""
                summary.remote_reset_at = None
                summary.remote_reset_in_seconds = None
                summary.remote_output_text = extract_output_text_from_success_body(body)
                return summary
            body_json = json.loads(body.decode("utf-8", errors="replace")) if body else {}
            (
                summary.remote_error_type,
                summary.remote_error_message,
                summary.remote_reset_at,
                summary.remote_reset_in_seconds,
            ) = extract_error_fields(body_json if isinstance(body_json, dict) else {})
    except urllib.error.HTTPError as exc:
        summary.remote_http_status = exc.code
        summary.remote_latency_ms = int((time.perf_counter() - started) * 1000)
        body = exc.read()
        body_json = {}
        if body:
            try:
                body_json = json.loads(body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                body_json = {}
        (
            summary.remote_error_type,
            summary.remote_error_message,
            summary.remote_reset_at,
            summary.remote_reset_in_seconds,
        ) = extract_error_fields(body_json if isinstance(body_json, dict) else {})

        if exc.code in (401, 403):
            summary.remote_status = "UNAUTHORIZED"
            return summary
        if exc.code == 429:
            if summary.remote_error_type == "usage_limit_reached":
                summary.remote_status = "RATE_LIMITED"
            elif "capacity" in summary.remote_error_message.lower():
                summary.remote_status = "AT_CAPACITY"
            else:
                summary.remote_status = "RATE_LIMITED"
            return summary
        if exc.code >= 500:
            summary.remote_status = "UPSTREAM_5XX"
            return summary
        summary.remote_status = f"HTTP_{exc.code}"
        return summary
    except urllib.error.URLError as exc:
        summary.remote_latency_ms = int((time.perf_counter() - started) * 1000)
        summary.remote_status = "NETWORK_ERROR"
        summary.remote_error_message = str(exc.reason)
        return summary
    except Exception as exc:
        summary.remote_latency_ms = int((time.perf_counter() - started) * 1000)
        summary.remote_status = "PROBE_ERROR"
        summary.remote_error_message = str(exc)
        return summary

    summary.remote_status = "UNKNOWN"
    return summary

import shutil
def probe_credential_with_retries(
    summary: CredentialSummary,
    model: str,
    timeout_seconds: float,
    insecure: bool,
    max_attempts: int,
    retry_delay_seconds: float,
) -> CredentialSummary:
    attempts = max(1, max_attempts)
    current = summary
    for attempt in range(1, attempts + 1):
        current = probe_credential(current, model, timeout_seconds, insecure)
        current.probe_attempts = attempt
        if attempt == 1 and current.remote_status == "USABLE":
            current.initially_usable = True
        if not should_retry(current):
            print(f'alive {current.path}')
            return current
        if attempt < attempts and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)
    if os.path.join(current.path):
        print(f'invalid {current.path} {current.remote_status}')
        if current.remote_status == "UNAUTHORIZED":
            os.remove(current.path)
            print(f'remove')
    return current


def render_summary(summary: CredentialSummary) -> str:
    lines = []
    lines.append(f"=== {summary.path.name} ===")
    if summary.error:
        lines.append(f"error: {summary.error}")
        return "\n".join(lines)

    lines.append(f"path: {summary.path}")
    lines.append(f"provider: {summary.provider}")
    lines.append(f"type: {summary.cred_type}")
    lines.append(f"label: {summary.label or '-'}")
    lines.append(f"email: {summary.email or '-'}")
    lines.append(f"account_id: {summary.account_id or '-'}")
    lines.append(f"plan_type: {summary.plan_type or '-'}")
    lines.append(f"storage_expired_at: {format_datetime(summary.expired_at)}")
    lines.append(f"id_token_exp: {format_unix_timestamp(summary.id_token_exp)}")
    lines.append(f"access_token_exp: {format_unix_timestamp(summary.access_token_exp)}")
    lines.append(f"local_quota_state: {render_quota_state(summary)}")
    lines.append(
        "local_quota_reason: " + (summary.quota_reason if summary.quota_reason else "-")
    )
    lines.append(f"local_next_recover_at: {format_datetime(summary.next_recover_at)}")
    lines.append(
        "local_backoff_level: "
        + (str(summary.backoff_level) if summary.backoff_level is not None else "-")
    )
    lines.append(
        "official_remaining_quota: unavailable (local credential files do not expose a stable OpenAI/Codex remaining quota value)"
    )
    lines.append(f"remote_probe_status: {summary.remote_status}")
    lines.append(
        "remote_http_status: "
        + (str(summary.remote_http_status) if summary.remote_http_status is not None else "-")
    )
    lines.append(
        "remote_error_type: " + (summary.remote_error_type if summary.remote_error_type else "-")
    )
    lines.append(
        "remote_error_message: " + (summary.remote_error_message if summary.remote_error_message else "-")
    )
    lines.append(f"remote_reset_at: {format_datetime(summary.remote_reset_at)}")
    lines.append(
        "remote_reset_in_seconds: "
        + (
            str(summary.remote_reset_in_seconds)
            if summary.remote_reset_in_seconds is not None
            else "-"
        )
    )
    lines.append(
        "remote_latency_ms: "
        + (str(summary.remote_latency_ms) if summary.remote_latency_ms is not None else "-")
    )
    lines.append(f"probe_attempts: {summary.probe_attempts or '-'}")
    lines.append(
        "returned_text: " + (summary.remote_output_text if summary.remote_output_text else "-")
    )

    if summary.model_quotas:
        lines.append("model_quotas:")
        for model_name, exceeded, reason, next_recover, backoff in summary.model_quotas:
            lines.append(
                f"  - {model_name}: {'EXCEEDED' if exceeded else 'OK'}, reason={reason or '-'}, next_recover_at={format_datetime(next_recover)}, backoff_level={backoff if backoff is not None else '-'}"
            )

    return "\n".join(lines)


def iter_json_files(directory: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*.json" if recursive else "*.json"
    for path in sorted(directory.glob(pattern)):
        if path.is_file():
            yield path


def print_scan(
    directory: Path,
    recursive: bool,
    probe: bool,
    model: str,
    timeout_seconds: float,
    max_workers: int,
    insecure: bool,
    retry_attempts: int,
    retry_delay_seconds: float
) -> int:
    files = list(iter_json_files(directory, recursive=recursive))
    if not files:
        print(f"未找到 JSON 凭证文件: {directory}")
        return 1

    summaries = [summarize_credential(path) for path in files]
    if probe:
        workers = max(1, min(max_workers, 16))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    probe_credential_with_retries,
                    summary,
                    model,
                    timeout_seconds,
                    insecure,
                    retry_attempts,
                    retry_delay_seconds,
                )
                for summary in summaries
            ]
            summaries = [future.result() for future in futures]

    safe_print(f"扫描目录: {directory}")
    safe_print(f"文件数量: {len(summaries)}")
    safe_print(f"远程探活: {'开启' if probe else '关闭'}")
    if probe:
        safe_print(f"探活模型: {model}")
        safe_print(f"超时秒数: {timeout_seconds}")
        safe_print(f"失败重试次数: {retry_attempts}")
        safe_print(f"重试间隔秒数: {retry_delay_seconds}")
    safe_print()
    for index, summary in enumerate(summaries, start=1):
        # safe_print(render_summary(summary))
        if index != len(summaries):
            safe_print()

    passed_count = sum(1 for summary in summaries if summary.remote_status == "USABLE")
    failed_count = len(summaries) - passed_count
    success_summaries = [summary for summary in summaries if summary.remote_status == "USABLE"]
    failed_summaries = [summary for summary in summaries if summary.remote_status != "USABLE"]
    first_pass_count = sum(1 for summary in success_summaries if summary.probe_attempts <= 1)
    recovered_count = sum(1 for summary in success_summaries if summary.probe_attempts > 1)

    safe_print()
    safe_print("=== 汇总 ===")
    safe_print(f"总数: {len(summaries)}")
    safe_print(f"首次通过: {first_pass_count}")
    safe_print(f"重试后通过: {recovered_count}")
    safe_print(f"通过总数: {passed_count}")
    safe_print(f"永久失败: {failed_count}")
    if success_summaries:
        safe_print()
        safe_print("=== 成功结果 ===")
        for summary in success_summaries:
            account_name = summary.email or summary.path.name
            output_text = summary.remote_output_text or "(无可提取文本输出)"
            safe_print(
                f"- {account_name} | status={summary.remote_status} | attempts={summary.probe_attempts} | returned_text={output_text}"
            )
    if failed_summaries:
        safe_print()
        safe_print("=== 失败账号 ===")
        for summary in failed_summaries:
            account_name = summary.email or summary.path.name
            safe_print(
                f"- {account_name} | status={summary.remote_status} | attempts={summary.probe_attempts} | http={summary.remote_http_status if summary.remote_http_status is not None else '-'} | error={summary.remote_error_message or '-'}"
            )

    return 0


def clear_terminal() -> None:
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="扫描目录下所有 JSON 凭证，并打印可可靠获得的额度相关信息。"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=str(Path.home() / ".cli-proxy-api"),
        help="凭证目录，默认是 ~/.cli-proxy-api",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="递归扫描子目录中的 JSON 文件",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="持续轮询目录并重复打印结果",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="轮询间隔秒数，默认 30 秒",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="watch 模式下不要清屏",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="对每个凭证发一个最小远程 Codex 请求，判断可用性与限流恢复时间",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.4",
        help="远程探活使用的模型名，默认 gpt-4o",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="远程探活单次请求超时秒数，默认 10 秒",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="远程探活并发数，默认 2，内部最大限制为 16",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="忽略 TLS 证书校验，仅在抓包/代理环境下使用",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="账号探活失败时的最大尝试次数，默认 5 次",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="重试间隔秒数，默认 1 秒",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    directory = Path(args.directory).expanduser()
    if not directory.exists() or not directory.is_dir():
        safe_print(f"目录不存在或不是目录: {directory}")
        return 2

    if args.interval <= 0:
        safe_print("--interval 必须大于 0")
        return 2

    if not args.watch:
        return print_scan(
            directory,
            recursive=args.recursive,
            probe=args.probe,
            model=args.model,
            timeout_seconds=args.timeout,
            max_workers=args.max_workers,
            insecure=args.insecure,
            retry_attempts=args.retries,
            retry_delay_seconds=args.retry_delay,
        )

    try:
        while True:
            if not args.no_clear:
                clear_terminal()
            safe_print(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"))
            safe_print()
            print_scan(
                directory,
                recursive=args.recursive,
                probe=args.probe,
                model=args.model,
                timeout_seconds=args.timeout,
                max_workers=args.max_workers,
                insecure=args.insecure,
                retry_attempts=args.retries,
                retry_delay_seconds=args.retry_delay,
            )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        safe_print("\n已停止轮询。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

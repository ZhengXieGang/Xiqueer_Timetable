#!/usr/bin/env python3
"""
喜鹊儿课表 GUI 导出工具（CSV/ICS）。

使用方式：
1. 直接运行：python3 xiqueer_timetable.py
2. 在图形界面中填写学校、账号、密码等信息
3. 导出 CSV / ICS

特性：
- 图形面板交互（无终端输入）。
- CSV 字段自定义：选择导出字段、调整字段顺序。
- ICS DESCRIPTION 自定义：选择字段与顺序。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import re
import string
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


GATEWAY_URL = "https://api.xiqueer.com/manager//wap/wapController.jsp"
ENC_KEY = "yt6n78"
APP_VERSION = "2.6.450"
APP_INFO = "Android2.6.450"
MODEL = "MI 8"
OS_NAME = "Android"
OS_VERSION = "10"
DEFAULT_ICS_TIMEZONE = "Asia/Shanghai"
DEFAULT_OUTPUT_FILE = "课表.csv"
DEFAULT_TIMEOUT = 20
DEFAULT_TERM_MODE_VALUE = "current"
SCRIPT_DIR = Path(__file__).resolve().parent

LOGIN_AES_KEY = b"loginkeyapp93214"
LOGIN_AES_IV = b"12fg45gpsdfz34ab"


CSV_FIELD_DEFS: List[Tuple[str, str]] = [
    ("school_name", "学校名称"),
    ("school_code", "学校代码"),
    ("account", "账号"),
    ("user_id", "用户ID"),
    ("term_code", "学期代码"),
    ("term_name", "学期名称"),
    ("weekday_num", "星期序号"),
    ("weekday_name", "星期"),
    ("course_name", "课程名称"),
    ("teacher", "教师"),
    ("location", "上课地点"),
    ("campus", "校区"),
    ("teaching_class", "教学班"),
    ("teaching_class_code", "教学班代码"),
    ("course_code", "课程代码"),
    ("course_alias_code", "课程别名代码"),
    ("credits", "学分"),
    ("weeks", "上课周次"),
    ("sections", "节次"),
    ("section_codes", "节次代码"),
    ("time_source", "时间来源"),
    ("period_sections", "解析节次"),
    ("period_start", "开始时间"),
    ("period_end", "结束时间"),
    ("period_duration_min", "时长(分钟)"),
    ("period_note", "时间备注"),
    ("student_count", "人数"),
    ("remark", "备注"),
    ("live_url", "直播链接"),
    ("start_time", "接口开始时间"),
    ("end_time", "接口结束时间"),
    ("date", "接口日期"),
]
CSV_FIELD_LABELS: Dict[str, str] = {k: v for k, v in CSV_FIELD_DEFS}
DEFAULT_CSV_FIELD_KEYS: List[str] = [k for k, _ in CSV_FIELD_DEFS]
DEFAULT_BASIC_CSV_FIELD_KEYS: List[str] = [
    "course_name",
    "weekday_name",
    "sections",
    "teacher",
    "location",
    "weeks",
    "period_start",
    "period_end",
]
DEFAULT_ICS_DESC_FIELD_KEYS: List[str] = [
    "location",
    "teacher",
    "weeks",
    "teaching_class",
]


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _to_base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    sign = ""
    if value < 0:
        sign = "-"
        value = -value
    output = ""
    while value > 0:
        output = chars[value % 36] + output
        value //= 36
    return sign + output


def encode_param(raw: str, key: str = ENC_KEY) -> str:
    if not raw or not key:
        return raw

    key_len = len(key)
    raw_len = len(raw)
    rounds = math.ceil(raw_len / key_len)
    offset = (math.ceil(raw_len * 3.0 * 6.0 / 9.0 / 6.0) * 6) % key_len

    stream = []
    for i in range(rounds):
        for j in range(1, key_len + 1):
            idx = i * key_len + j
            chunk = "000" + str(ord(raw[idx - 1]) + ord(key[j - 1]) + offset)
            stream.append(chunk[-3:])
            if idx == raw_len:
                break
    stream_str = "".join(stream)

    out = []
    pos = 0
    while pos < len(stream_str):
        seg = stream_str[pos : pos + 9]
        pos += 9
        out.append(("000000" + _to_base36(int(seg)))[-6:])
    return "".join(out)


def encode_param2(raw: str) -> str:
    split = [""] + list(md5_hex(raw))
    keep = [ch for i, ch in enumerate(split) if i not in {3, 10, 17, 25}]
    return md5_hex("".join(keep))


def js_escape(text: str) -> str:
    # Equivalent to app's q9.y.a (JavaScript escape style).
    if text is None:
        return ""
    safe = set(string.ascii_letters + string.digits + "-_.!~*'()")
    out = []
    for ch in text:
        code = ord(ch)
        if ch in safe:
            out.append(ch)
        elif code <= 0x7F:
            out.append("%{:02X}".format(code))
        else:
            out.append("%u{:04X}".format(code))
    return "".join(out)


def decrypt_login_response(cipher_text: str) -> str:
    decoded = urllib.parse.unquote(cipher_text)
    encrypted = base64.b64decode(decoded)
    cipher = Cipher(
        algorithms.AES(LOGIN_AES_KEY),
        modes.CBC(LOGIN_AES_IV),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    plain_padded = decryptor.update(encrypted) + decryptor.finalize()
    pad_len = plain_padded[-1]
    if 1 <= pad_len <= 16:
        plain_padded = plain_padded[:-pad_len]
    return plain_padded.decode("utf-8", errors="ignore")


def parse_csv_list(text: str) -> List[str]:
    if not text:
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def parse_index_expr(expr: str, size: int) -> List[int]:
    picked = set()
    for token in re.split(r"[,\s]+", expr.strip()):
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            if len(parts) != 2 or (not parts[0].isdigit()) or (not parts[1].isdigit()):
                raise ValueError(f"非法范围: {token}")
            start = int(parts[0])
            end = int(parts[1])
            if start > end:
                start, end = end, start
            for i in range(start, end + 1):
                if i < 1 or i > size:
                    raise ValueError(f"序号越界: {i}")
                picked.add(i)
        else:
            if not token.isdigit():
                raise ValueError(f"非法序号: {token}")
            i = int(token)
            if i < 1 or i > size:
                raise ValueError(f"序号越界: {i}")
            picked.add(i)
    return sorted(picked)


def safe_file_component(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "unknown"
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name.strip("_") or "unknown"


def resolve_output_path(path_text: str) -> Path:
    p = Path(path_text).expanduser()
    if not p.is_absolute():
        p = SCRIPT_DIR / p
    return p.resolve()


def parse_section_from_jieci(text: str) -> Optional[int]:
    nums = re.findall(r"\d+", text or "")
    if not nums:
        return None
    val = int(nums[0])
    return val if val > 0 else None


def normalize_hhmm(text: str) -> str:
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*$", text or "")
    if not m:
        return ""
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return ""
    return f"{hh:02d}:{mm:02d}"


def hhmm_to_minutes(text: str) -> Optional[int]:
    m = re.match(r"^(\d{2}):(\d{2})$", text or "")
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    return hh * 60 + mm


def minutes_to_hhmm(total: int) -> str:
    total = max(0, min(total, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


def add_minutes_to_hhmm(start: str, delta: int) -> str:
    start_min = hhmm_to_minutes(start)
    if start_min is None:
        return ""
    return minutes_to_hhmm(start_min + max(delta, 0))


def parse_period_numbers(text: str) -> List[int]:
    if not text:
        return []
    cleaned = (
        text.replace("，", ",")
        .replace("；", ",")
        .replace(";", ",")
        .replace("第", "")
        .replace("节", "")
        .replace(" ", "")
    )
    cleaned = re.sub(r"[~～—–－至]", "-", cleaned)

    picked: set[int] = set()
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        nums = re.findall(r"\d+", part)
        if not nums:
            continue
        if "-" in part and len(nums) >= 2:
            start, end = int(nums[0]), int(nums[1])
            if start > end:
                start, end = end, start
            for v in range(start, end + 1):
                if v > 0:
                    picked.add(v)
        else:
            for token in nums:
                val = int(token)
                if val > 0:
                    picked.add(val)
    return sorted(picked)


def parse_weeks_expr(text: str) -> List[int]:
    if not text:
        return []
    cleaned = (
        text.replace("周", "")
        .replace("第", "")
        .replace("，", ",")
        .replace("；", ",")
        .replace(";", ",")
        .replace(" ", "")
    )
    cleaned = re.sub(r"[~～—–－至]", "-", cleaned)

    weeks: set[int] = set()
    for token in cleaned.split(","):
        token = token.strip()
        if not token:
            continue
        odd_only = "单" in token
        even_only = "双" in token
        token = token.replace("单", "").replace("双", "")
        nums = re.findall(r"\d+", token)
        if not nums:
            continue

        values: List[int] = []
        if "-" in token and len(nums) >= 2:
            start, end = int(nums[0]), int(nums[1])
            if start > end:
                start, end = end, start
            values = list(range(start, end + 1))
        else:
            values = [int(n) for n in nums]

        for value in values:
            if value <= 0:
                continue
            if odd_only and value % 2 == 0:
                continue
            if even_only and value % 2 == 1:
                continue
            weeks.add(value)
    return sorted(weeks)


def escape_ics_text(text: str) -> str:
    value = text or ""
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", "\\n")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    return value


def fold_ics_line(line: str, width: int = 75) -> List[str]:
    # RFC5545: each content line should be folded at 75 octets (bytes), not chars.
    if len((line or "").encode("utf-8")) <= width:
        return [line]

    parts: List[str] = []
    rest = line
    first = True
    while rest:
        limit = width if first else width - 1  # continuation line has leading space
        cur_bytes = 0
        cut = 0
        for idx, ch in enumerate(rest):
            ch_bytes = len(ch.encode("utf-8"))
            if cur_bytes + ch_bytes > limit:
                break
            cur_bytes += ch_bytes
            cut = idx + 1

        # Fallback safety; practically unreachable because every UTF-8 char <= 4 bytes.
        if cut == 0:
            cut = 1

        chunk = rest[:cut]
        rest = rest[cut:]
        if first:
            parts.append(chunk)
            first = False
        else:
            parts.append(" " + chunk)
    return parts


def normalize_period_map(raw_sksj: object) -> Dict[int, "PeriodTime"]:
    if raw_sksj is None:
        return {}
    if isinstance(raw_sksj, str):
        text = raw_sksj.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
    elif isinstance(raw_sksj, list):
        payload = raw_sksj
    else:
        return {}

    periods: Dict[int, PeriodTime] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        jieci = str(item.get("jieci", "") or "")
        section = parse_section_from_jieci(jieci)
        start = normalize_hhmm(str(item.get("time", "") or ""))
        try:
            duration = int(str(item.get("shichang", "") or "0"))
        except ValueError:
            duration = 0
        if section is None or not start or duration <= 0:
            continue
        periods[section] = PeriodTime(
            section=section,
            start=start,
            duration_min=duration,
            end=add_minutes_to_hhmm(start, duration),
        )
    return dict(sorted(periods.items()))


def format_period(period: Optional["PeriodTime"]) -> str:
    if period is None:
        return "无"
    return f"{period.start}-{period.end} ({period.duration_min}m)"


@dataclass
class LoginState:
    school_name: str
    school_code: str
    user_id: str
    user_type: str
    uuid: str
    token: str
    xm: str
    cache_md5: str


@dataclass
class PeriodTime:
    section: int
    start: str
    duration_min: int
    end: str


@dataclass
class TimeProfile:
    source: str  # jwsj / sksj
    label: str
    ok: bool
    message: str
    periods: Dict[int, PeriodTime]


@dataclass
class ExportOptions:
    school_name: str
    account: str
    password: str
    timeout: int
    term_mode: str
    term_codes: List[str]
    output_csv: Path
    split_by_term: bool
    export_ics: bool
    output_ics: Optional[Path]
    csv_fields: List[str]
    ics_desc_fields: List[str]


class XiQueErClient:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()

    def _build_signed_form(self, raw: str, token: str) -> Dict[str, str]:
        now = str(int(time.time()))
        return {
            "param": encode_param(raw),
            "param2": encode_param2(raw),
            "timestamp": now,
            "echo": "echo" + str(int(time.time() * 1000))[-8:],
            # Current gateway accepts placeholder values for these two fields.
            "encrptSecretKey": "x" * 64,
            "xqerSign": md5_hex(raw),
            "token": token,
            "appinfo": APP_INFO,
            "appsjxh": MODEL,
        }

    def search_schools(self, keyword: str) -> List[Dict[str, str]]:
        payload = {
            "action": "getAgent",
            "xxmc": keyword,
            "appver": APP_VERSION,
        }
        resp = self.session.post(GATEWAY_URL, data=payload, timeout=self.timeout)
        resp.raise_for_status()
        schools = resp.json()
        if not isinstance(schools, list) or not schools:
            return []

        keyword_text = str(keyword or "").strip().lower()
        all_schools = [s for s in schools if isinstance(s, dict)]
        if not keyword_text:
            return all_schools

        def _name(s: Dict[str, str]) -> str:
            return str(s.get("xxmc", "") or "")

        matched = [
            s for s in all_schools
            if keyword_text in _name(s).lower()
        ]
        if not matched:
            return []

        def _rank(s: Dict[str, str]) -> Tuple[int, int, str]:
            name = _name(s)
            low = name.lower()
            if low == keyword_text:
                level = 0
            elif low.startswith(keyword_text):
                level = 1
            else:
                level = 2
            return (level, len(name), low)

        return sorted(matched, key=_rank)

    def find_school(self, school_name: str) -> Dict[str, str]:
        schools = self.search_schools(school_name)
        if not schools:
            raise RuntimeError("获取学校列表失败，接口返回异常")

        exact = [s for s in schools if s.get("xxmc") == school_name]
        if exact:
            return exact[0]

        fuzzy = [s for s in schools if school_name in s.get("xxmc", "")]
        if fuzzy:
            return fuzzy[0]

        raise RuntimeError(f"未找到学校：{school_name}")

    def login(self, account: str, password: str, school: Dict[str, str]) -> LoginState:
        raw_pairs: List[Tuple[str, str]] = [
            ("loginId", account),
            ("xxdm", school["xxdm"]),
            ("pwd", js_escape(password)),
            ("pwdsfzm", "1"),
            ("action", "getLoginInfoNew"),
            ("zddl", "1"),
            ("isky", "1"),
            ("sjbz", ""),
            ("sswl", ""),
            ("sjxh", MODEL),
            ("os", OS_NAME),
            ("xtbb", OS_VERSION),
            ("loginmode", "0"),
            ("appver", APP_VERSION),
        ]
        raw = "&".join(f"{k}={v}" for k, v in raw_pairs)
        form = self._build_signed_form(raw, token="00000")

        resp = self.session.post(GATEWAY_URL, data=form, timeout=self.timeout)
        resp.raise_for_status()
        encrypted = resp.text.strip()
        if encrypted.startswith("{"):
            err = json.loads(encrypted)
            raise RuntimeError(f"登录失败: {err.get('message') or err}")

        login_text = decrypt_login_response(encrypted)
        login_json = json.loads(login_text)
        if str(login_json.get("flag")) != "0":
            raise RuntimeError(f"登录失败: {login_json.get('msg') or login_json}")

        cache_md5 = ""
        cache_obj = login_json.get("cache")
        if isinstance(cache_obj, dict):
            cache_md5 = str(cache_obj.get("md5", "") or "")

        return LoginState(
            school_name=str(login_json.get("xxmc", school.get("xxmc", ""))),
            school_code=str(login_json.get("xxdm", school["xxdm"])),
            user_id=str(login_json["userid"]),
            user_type=str(login_json["usertype"]),
            uuid=str(login_json.get("uuid", login_json["userid"])),
            token=str(login_json["token"]),
            xm=str(login_json.get("xm", "")),
            cache_md5=cache_md5,
        )

    def _authed_raw(self, base_pairs: Sequence[Tuple[str, str]], state: LoginState) -> str:
        pairs = list(base_pairs)
        keys = {k for k, _ in pairs}

        # App-side extra fields for authenticated calls.
        pairs.append(("xqerxm", js_escape(state.xm)))
        if "uuid" not in keys:
            pairs.append(("uuid", state.uuid))
        pairs.append(("md5", state.cache_md5))
        if "userId" not in keys:
            pairs.append(("userId", state.user_id))
        if "usertype" not in keys:
            pairs.append(("usertype", state.user_type))

        return "&".join(f"{k}={v}" for k, v in pairs)

    def authed_get_json(self, base_pairs: Sequence[Tuple[str, str]], state: LoginState) -> Dict:
        raw = self._authed_raw(base_pairs, state)
        form = self._build_signed_form(raw, token=state.token)
        resp = self.session.get(GATEWAY_URL, params=form, timeout=self.timeout)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            raise RuntimeError("接口返回空内容")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"接口返回非 JSON: {text[:200]}") from exc

        if isinstance(data, dict) and "errcode" in data and str(data.get("errcode")) != "0":
            raise RuntimeError(f"接口错误: {data.get('message') or data}")
        return data

    def get_terms(self, state: LoginState) -> List[Dict[str, str]]:
        data = self.authed_get_json(
            [
                ("userId", state.user_id),
                ("usertype", state.user_type),
                ("action", "getXtgn"),
                ("step", "xnxq"),
            ],
            state,
        )
        terms = data.get("xnxq")
        if not isinstance(terms, list):
            raise RuntimeError(f"获取学期失败: {data}")
        return terms

    def get_term_timetable(self, state: LoginState, term_code: str, week: str = "") -> Dict:
        return self.authed_get_json(
            [
                ("usertype", state.user_type),
                ("action", "getKb"),
                ("step", "kbdetail_bz"),
                ("bjdm", ""),
                ("jsdm", ""),
                ("xnxq", term_code),
                ("week", str(week or "")),
                ("userId", state.user_id),
                ("channel", "jrkb"),
            ],
            state,
        )

    def _fetch_time_profile(
        self,
        state: LoginState,
        action: str,
        step: str,
        source: str,
        label: str,
    ) -> TimeProfile:
        data = self.authed_get_json(
            [
                ("action", action),
                ("step", step),
                ("userId", state.user_id),
                ("usertype", state.user_type),
            ],
            state,
        )
        flag = str(data.get("flag", ""))
        msg = str(data.get("msg", "") or "")
        periods = normalize_period_map(data.get("sksj"))
        ok = flag == "1" and bool(periods)
        return TimeProfile(
            source=source,
            label=label,
            ok=ok,
            message=msg,
            periods=periods,
        )

    def fetch_jwsj_time(self, state: LoginState) -> TimeProfile:
        return self._fetch_time_profile(
            state=state,
            action="jwsj",
            step="gettime",
            source="jwsj",
            label="教务系统作息",
        )

    def fetch_sksj_time(self, state: LoginState) -> TimeProfile:
        return self._fetch_time_profile(
            state=state,
            action="sksj",
            step="obtainSksj",
            source="sksj",
            label="个人设置作息",
        )


def flatten_term_courses(
    timetable: Dict,
    account: str,
    school_name: str,
    school_code: str,
    user_id: str,
    term_code: str,
    term_name: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    week_name = {
        1: "星期一",
        2: "星期二",
        3: "星期三",
        4: "星期四",
        5: "星期五",
        6: "星期六",
        7: "星期日",
    }

    for day in range(1, 8):
        lessons = timetable.get(f"week{day}") or []
        if not isinstance(lessons, list):
            continue
        for item in lessons:
            row = {
                "school_name": school_name,
                "school_code": school_code,
                "account": account,
                "user_id": user_id,
                "term_code": term_code,
                "term_name": term_name,
                "weekday_num": str(day),
                "weekday_name": week_name[day],
                "course_name": str(item.get("kcmc", "")),
                "teacher": str(item.get("rkjs", "")),
                "location": str(item.get("skdd", "")),
                "campus": str(item.get("xq", "")),
                "teaching_class": str(item.get("skbjmc", "")),
                "teaching_class_code": str(item.get("skbj", "")),
                "course_code": str(item.get("kcdm", "")),
                "course_alias_code": str(item.get("kcyhdm", "")),
                "credits": str(item.get("xf", "")),
                "weeks": str(item.get("skzs", "")),
                "sections": str(item.get("jcxx", "")),
                "section_codes": str(item.get("jcdm", "")),
                "student_count": str(item.get("rs", "")),
                "remark": str(item.get("bz", "")),
                "live_url": str(item.get("liveUrl", "")),
                "start_time": str(item.get("beginTime", "")),
                "end_time": str(item.get("endTime", "")),
                "date": str(item.get("rq", "")),
                "time_source": "",
                "period_sections": "",
                "period_start": "",
                "period_end": "",
                "period_duration_min": "",
                "period_note": "",
            }
            rows.append(row)
    return rows


def apply_period_time_to_rows(
    rows: List[Dict[str, str]],
    period_map: Dict[int, PeriodTime],
    time_source: str,
) -> None:
    for row in rows:
        row["time_source"] = time_source if period_map else ""
        row["period_sections"] = ""
        row["period_start"] = ""
        row["period_end"] = ""
        row["period_duration_min"] = ""
        row["period_note"] = ""

        sec_codes = parse_period_numbers(str(row.get("section_codes", "") or ""))
        if not sec_codes:
            sec_codes = parse_period_numbers(str(row.get("sections", "") or ""))
        if not sec_codes:
            row["period_note"] = "课程节次为空"
            continue

        row["period_sections"] = ",".join(f"{x:02d}" for x in sec_codes)
        if not period_map:
            continue

        missing = [sec for sec in sec_codes if sec not in period_map]
        if missing:
            row["period_note"] = "缺少节次时间: " + ",".join(f"{x:02d}" for x in missing)
            continue

        start_sec = min(sec_codes)
        end_sec = max(sec_codes)
        start_period = period_map[start_sec]
        end_period = period_map[end_sec]

        start_min = hhmm_to_minutes(start_period.start)
        end_min = hhmm_to_minutes(end_period.end)
        duration = ""
        if start_min is not None and end_min is not None and end_min >= start_min:
            duration = str(end_min - start_min)
        else:
            duration = str(sum(period_map[sec].duration_min for sec in sec_codes))

        row["period_start"] = start_period.start
        row["period_end"] = end_period.end
        row["period_duration_min"] = duration


def export_csv(
    rows: Iterable[Dict[str, str]],
    output_path: Path,
    field_keys: List[str],
) -> int:
    rows = list(rows)
    if not rows:
        raise RuntimeError("未导出到任何课程数据")
    if not field_keys:
        raise RuntimeError("CSV 字段不能为空")

    headers = [CSV_FIELD_LABELS[k] for k in field_keys if k in CSV_FIELD_LABELS]
    if len(headers) != len(field_keys):
        raise RuntimeError("CSV 字段配置存在未知字段")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            out_row = {CSV_FIELD_LABELS[key]: str(row.get(key, "") or "") for key in field_keys}
            writer.writerow(out_row)
    return len(rows)


def resolve_candidate_terms(
    terms: List[Dict[str, str]],
    term_mode: str,
    term_codes: List[str],
) -> List[str]:
    term_name_map = {str(t.get("dm", "")): str(t.get("mc", "")) for t in terms}
    available_codes = [k for k in term_name_map.keys() if k]

    if term_mode == "current":
        current_terms = [str(t["dm"]) for t in terms if str(t.get("dqxq", "")) == "1"]
        if not current_terms:
            raise RuntimeError("未找到当前学期，请改用“特定”模式后重新选择学期")
        return current_terms

    if term_mode == "specify":
        if not term_codes:
            raise RuntimeError("选择“特定”模式时必须先选择学期")
        missing = [x for x in term_codes if x not in available_codes]
        if missing:
            raise RuntimeError(f"以下学期代码不存在: {missing}")
        return term_codes

    raise RuntimeError(f"未知学期模式: {term_mode}")


def collect_time_conflicts(
    jwsj_map: Dict[int, PeriodTime],
    sksj_map: Dict[int, PeriodTime],
) -> List[Tuple[int, PeriodTime, PeriodTime]]:
    conflicts: List[Tuple[int, PeriodTime, PeriodTime]] = []
    for sec in sorted(set(jwsj_map.keys()) & set(sksj_map.keys())):
        a = jwsj_map[sec]
        b = sksj_map[sec]
        if a.start != b.start or a.end != b.end or a.duration_min != b.duration_min:
            conflicts.append((sec, a, b))
    return conflicts


def merge_time_profiles(
    jwsj_map: Dict[int, PeriodTime],
    sksj_map: Dict[int, PeriodTime],
) -> Dict[int, PeriodTime]:
    merged = dict(jwsj_map)
    # 无冲突时优先个人设置（若个人配置更多节次）
    for sec, period in sksj_map.items():
        merged[sec] = period
    return dict(sorted(merged.items()))


def build_conflicts_text(conflicts: List[Tuple[int, PeriodTime, PeriodTime]]) -> str:
    lines = [
        "检测到“教务作息”与“个人作息”冲突（同一节次时间不同）：",
        "节次 | 教务作息 | 个人作息",
    ]
    for sec, jwsj, sksj in conflicts:
        lines.append(f"{sec:>2} | {format_period(jwsj)} | {format_period(sksj)}")
    return "\n".join(lines)


def derive_first_monday(meta: Dict[str, str]) -> Optional[date]:
    qssj = str(meta.get("qssj", "") or "").strip()
    zc = str(meta.get("zc", "") or "").strip()
    if not qssj:
        return None

    try:
        cur_day = datetime.strptime(qssj, "%Y-%m-%d").date()
    except ValueError:
        return None

    week_no_match = re.search(r"\d+", zc)
    if not week_no_match:
        return None
    week_no = int(week_no_match.group(0))
    if week_no <= 0:
        return None

    current_week_monday = cur_day - timedelta(days=cur_day.weekday())
    first_monday = current_week_monday - timedelta(days=(week_no - 1) * 7)
    return first_monday


def export_ics(
    rows: List[Dict[str, str]],
    period_map: Dict[int, PeriodTime],
    term_first_monday_map: Dict[str, date],
    output_path: Path,
    timezone_name: str,
    calendar_name: str,
    description_fields: List[str],
) -> Tuple[int, Dict[str, int]]:
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stats = {
        "skip_no_term_start": 0,
        "skip_no_week": 0,
        "skip_no_section": 0,
        "skip_no_period_time": 0,
    }

    lines: List[str] = [
        "BEGIN:VCALENDAR",
        "PRODID:-//xiqueer-csv//CN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(calendar_name)}",
        "X-WR-TIMEZONE:UTC",
    ]
    local_tz = ZoneInfo(timezone_name)

    event_count = 0
    for row in rows:
        term_code = str(row.get("term_code", "") or "")
        first_monday = term_first_monday_map.get(term_code)
        if first_monday is None:
            stats["skip_no_term_start"] += 1
            continue

        try:
            weekday = int(str(row.get("weekday_num", "0") or "0"))
        except ValueError:
            weekday = 0
        if weekday < 1 or weekday > 7:
            stats["skip_no_week"] += 1
            continue

        weeks = parse_weeks_expr(str(row.get("weeks", "") or ""))
        if not weeks:
            stats["skip_no_week"] += 1
            continue

        sec_codes = parse_period_numbers(str(row.get("section_codes", "") or ""))
        if not sec_codes:
            sec_codes = parse_period_numbers(str(row.get("sections", "") or ""))
        if not sec_codes:
            stats["skip_no_section"] += 1
            continue

        missing_sec = [sec for sec in sec_codes if sec not in period_map]
        if missing_sec:
            stats["skip_no_period_time"] += 1
            continue

        start_period = period_map[min(sec_codes)]
        end_period = period_map[max(sec_codes)]

        for week_num in weeks:
            class_day = first_monday + timedelta(days=(week_num - 1) * 7 + (weekday - 1))
            start_hour, start_minute = map(int, start_period.start.split(":"))
            end_hour, end_minute = map(int, end_period.end.split(":"))
            start_local = datetime.combine(
                class_day,
                dt_time(start_hour, start_minute),
                tzinfo=local_tz,
            )
            end_local = datetime.combine(
                class_day,
                dt_time(end_hour, end_minute),
                tzinfo=local_tz,
            )
            start_utc = start_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            end_utc = end_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

            uid_seed = (
                f"{term_code}|{row.get('course_name', '')}|{row.get('teacher', '')}|"
                f"{row.get('location', '')}|{week_num}|{weekday}|{min(sec_codes)}-{max(sec_codes)}"
            )
            uid = f"{md5_hex(uid_seed)}@xiqueer.local"

            summary = escape_ics_text(str(row.get("course_name", "") or "课程"))
            location = escape_ics_text(str(row.get("location", "") or ""))
            desc_lines: List[str] = []
            for key in description_fields:
                label = CSV_FIELD_LABELS.get(key)
                if not label:
                    continue
                value = str(row.get(key, "") or "").strip()
                if value:
                    desc_lines.append(f"{label}:{value}")
            description = escape_ics_text("\\n".join(desc_lines))

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{now_utc}",
                    f"DTSTART:{start_utc}",
                    f"DTEND:{end_utc}",
                    f"SUMMARY:{summary}",
                    f"LOCATION:{location}",
                    f"DESCRIPTION:{description}" if description else "DESCRIPTION:",
                    "END:VEVENT",
                ]
            )
            event_count += 1

    lines.append("END:VCALENDAR")
    folded: List[str] = []
    for line in lines:
        folded.extend(fold_ics_line(line))
    content = "\r\n".join(folded) + "\r\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return event_count, stats


class FieldPickerFrame(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        title: str,
        field_defs: List[Tuple[str, str]],
        default_selected: List[str],
    ) -> None:
        super().__init__(master, text=title, padding=8)
        self._field_defs = field_defs
        self._all_keys = [k for k, _ in field_defs]
        self._labels = {k: v for k, v in field_defs}
        self._selected_keys = [k for k in default_selected if k in self._labels]

        left_box = ttk.Frame(self)
        left_box.grid(row=0, column=0, sticky="nsew")
        ttk.Label(left_box, text="可选字段").pack(anchor="w")
        self.left_list = tk.Listbox(left_box, selectmode=tk.EXTENDED, height=12, exportselection=False)
        self.left_list.pack(fill=tk.BOTH, expand=True)

        btn_box = ttk.Frame(self)
        btn_box.grid(row=0, column=1, padx=8, sticky="ns")
        ttk.Button(btn_box, text="添加 >", command=self._add_selected).pack(fill=tk.X, pady=2)
        ttk.Button(btn_box, text="< 移除", command=self._remove_selected).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_box, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        ttk.Button(btn_box, text="上移", command=self._move_up).pack(fill=tk.X, pady=2)
        ttk.Button(btn_box, text="下移", command=self._move_down).pack(fill=tk.X, pady=2)
        ttk.Button(btn_box, text="重置默认", command=self._reset_default).pack(fill=tk.X, pady=8)

        right_box = ttk.Frame(self)
        right_box.grid(row=0, column=2, sticky="nsew")
        ttk.Label(right_box, text="导出字段顺序").pack(anchor="w")
        self.right_list = tk.Listbox(right_box, selectmode=tk.EXTENDED, height=12, exportselection=False)
        self.right_list.pack(fill=tk.BOTH, expand=True)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        self._default_selected = list(self._selected_keys)
        self._left_keys: List[str] = []
        self._refresh()

    def _refresh(self) -> None:
        self._left_keys = [k for k in self._all_keys if k not in self._selected_keys]
        self.left_list.delete(0, tk.END)
        for key in self._left_keys:
            self.left_list.insert(tk.END, self._labels[key])

        self.right_list.delete(0, tk.END)
        for key in self._selected_keys:
            self.right_list.insert(tk.END, self._labels[key])

    def _add_selected(self) -> None:
        indexes = list(self.left_list.curselection())
        for idx in indexes:
            key = self._left_keys[idx]
            if key not in self._selected_keys:
                self._selected_keys.append(key)
        self._refresh()

    def _remove_selected(self) -> None:
        indexes = sorted(self.right_list.curselection(), reverse=True)
        for idx in indexes:
            if 0 <= idx < len(self._selected_keys):
                self._selected_keys.pop(idx)
        self._refresh()

    def _move_up(self) -> None:
        indexes = list(self.right_list.curselection())
        if not indexes:
            return
        for idx in indexes:
            if idx <= 0:
                continue
            self._selected_keys[idx - 1], self._selected_keys[idx] = (
                self._selected_keys[idx],
                self._selected_keys[idx - 1],
            )
        self._refresh()
        for idx in indexes:
            self.right_list.selection_set(max(0, idx - 1))

    def _move_down(self) -> None:
        indexes = list(self.right_list.curselection())
        if not indexes:
            return
        for idx in sorted(indexes, reverse=True):
            if idx >= len(self._selected_keys) - 1:
                continue
            self._selected_keys[idx + 1], self._selected_keys[idx] = (
                self._selected_keys[idx],
                self._selected_keys[idx + 1],
            )
        self._refresh()
        for idx in indexes:
            self.right_list.selection_set(min(len(self._selected_keys) - 1, idx + 1))

    def _reset_default(self) -> None:
        self._selected_keys = list(self._default_selected)
        self._refresh()

    def get_selected_keys(self) -> List[str]:
        return list(self._selected_keys)


class XiQueErGuiApp:
    TERM_MODE_LABEL_TO_VALUE = {
        "当前": "current",
        "特定": "specify",
    }
    TERM_MODE_VALUE_TO_LABEL = {v: k for k, v in TERM_MODE_LABEL_TO_VALUE.items()}

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("喜鹊儿课表导出面板")
        self._configure_window()
        self.selected_term_codes: List[str] = []
        self.selected_term_labels: List[str] = []
        self.available_terms: List[Dict[str, str]] = []
        self.term_list_cache_key: Tuple[str, str, str] = ("", "", "")
        self.selected_term_code_set: set[str] = set()
        self.current_term_index: int = 0
        self.current_term_selected_var = tk.BooleanVar(value=False)
        self.school_search_after_id: Optional[str] = None
        self.school_suggestion_map: Dict[str, Dict[str, str]] = {}
        self.selected_school: Optional[Dict[str, str]] = None

        self.school_var = tk.StringVar(value="")
        self.account_var = tk.StringVar(value="")
        self.password_var = tk.StringVar(value="")
        self.timeout_var = tk.StringVar(value=str(DEFAULT_TIMEOUT))
        self.term_mode_var = tk.StringVar(
            value=self.TERM_MODE_VALUE_TO_LABEL.get(DEFAULT_TERM_MODE_VALUE, "当前")
        )
        self.output_csv_var = tk.StringVar(value=DEFAULT_OUTPUT_FILE)
        self.split_by_term_var = tk.BooleanVar(value=True)
        self.export_ics_var = tk.BooleanVar(value=True)
        self.output_ics_var = tk.StringVar(value="")

        self._build_ui()
        self._update_term_codes_state()

    def _configure_window(self) -> None:
        self.root.update_idletasks()
        screen_w = max(self.root.winfo_screenwidth(), 1280)
        screen_h = max(self.root.winfo_screenheight(), 720)

        preferred_w = min(1240, screen_w - 120)
        preferred_h = min(860, screen_h - 120)
        width = max(980, preferred_w)
        height = max(700, preferred_h)

        if width > screen_w - 40:
            width = max(900, screen_w - 40)
        if height > screen_h - 60:
            height = max(640, screen_h - 60)

        min_w = min(width, max(860, screen_w - 120))
        min_h = min(height, max(620, screen_h - 140))
        self.root.minsize(min_w, min_h)

        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2 - 20, 0)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="学校").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.school_combo = ttk.Combobox(top, textvariable=self.school_var, width=22)
        self.school_combo.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.school_combo.bind("<KeyRelease>", self._on_school_key_release)
        self.school_combo.bind("<<ComboboxSelected>>", self._on_school_combo_selected)
        ttk.Label(top, text="账号").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.account_var, width=16).grid(row=0, column=3, sticky="w", padx=4, pady=4)
        ttk.Label(top, text="密码").grid(row=0, column=4, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.password_var, width=16, show="*").grid(
            row=0, column=5, sticky="w", padx=4, pady=4
        )
        ttk.Label(top, text="超时(秒)").grid(row=0, column=6, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.timeout_var, width=8).grid(row=0, column=7, sticky="w", padx=4, pady=4)

        ttk.Label(top, text="学期模式").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        mode_box = ttk.Combobox(
            top,
            textvariable=self.term_mode_var,
            values=list(self.TERM_MODE_LABEL_TO_VALUE.keys()),
            state="readonly",
            width=10,
        )
        mode_box.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._update_term_codes_state())

        self.term_pick_inline = ttk.Frame(top)
        self.term_pick_inline.grid(row=1, column=2, columnspan=6, sticky="we", padx=4, pady=4)
        self.term_prev_btn = ttk.Button(self.term_pick_inline, text="◀", width=3, command=self._show_prev_term)
        self.term_prev_btn.pack(side=tk.LEFT)
        self.term_current_label = ttk.Label(self.term_pick_inline, text="未加载学期")
        self.term_current_label.pack(side=tk.LEFT, padx=(6, 0))
        self.term_next_btn = ttk.Button(self.term_pick_inline, text="▶", width=3, command=self._show_next_term)
        self.term_next_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.term_current_check = ttk.Checkbutton(
            self.term_pick_inline,
            text="选择当前学期",
            variable=self.current_term_selected_var,
            command=self._toggle_current_term_selection,
        )
        self.term_current_check.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(self.term_pick_inline, text="刷新", command=self._reload_term_list).pack(side=tk.LEFT, padx=(6, 0))
        self.term_pick_summary = ttk.Label(self.term_pick_inline, text="已选 0 个学期")
        self.term_pick_summary.pack(side=tk.LEFT, padx=8)
        self.term_prev_btn.configure(state=tk.DISABLED)
        self.term_next_btn.configure(state=tk.DISABLED)
        self.term_current_check.configure(state=tk.DISABLED)

        ttk.Label(top, text="CSV 输出").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.output_csv_var, width=55).grid(
            row=2, column=1, columnspan=4, sticky="we", padx=4, pady=4
        )
        ttk.Button(top, text="选择文件", command=self._pick_csv_output).grid(row=2, column=5, sticky="w", padx=4, pady=4)
        ttk.Checkbutton(top, text="按学期拆分 CSV", variable=self.split_by_term_var).grid(
            row=2, column=6, columnspan=2, sticky="w", padx=4, pady=4
        )

        ttk.Checkbutton(top, text="导出 ICS", variable=self.export_ics_var).grid(
            row=3, column=0, sticky="w", padx=4, pady=4
        )
        ttk.Label(top, text="ICS 输出").grid(row=3, column=1, sticky="e", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.output_ics_var, width=42).grid(
            row=3, column=2, columnspan=3, sticky="we", padx=4, pady=4
        )
        ttk.Button(top, text="选择文件", command=self._pick_ics_output).grid(row=3, column=5, sticky="w", padx=4, pady=4)

        self.export_btn = ttk.Button(top, text="开始导出", command=self._on_export)
        self.export_btn.grid(row=3, column=6, columnspan=2, sticky="we", padx=4, pady=4)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        csv_tab = ttk.Frame(notebook)
        desc_tab = ttk.Frame(notebook)
        notebook.add(csv_tab, text="CSV 字段选择")
        notebook.add(desc_tab, text="ICS 描述字段选择")

        self.csv_picker = FieldPickerFrame(
            csv_tab,
            title="CSV 列配置",
            field_defs=CSV_FIELD_DEFS,
            default_selected=DEFAULT_BASIC_CSV_FIELD_KEYS,
        )
        self.csv_picker.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.desc_picker = FieldPickerFrame(
            desc_tab,
            title="ICS DESCRIPTION 字段配置",
            field_defs=CSV_FIELD_DEFS,
            default_selected=DEFAULT_ICS_DESC_FIELD_KEYS,
        )
        self.desc_picker.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        log_wrap = ttk.LabelFrame(self.root, text="运行日志", padding=8)
        log_wrap.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))
        self.log_text = scrolledtext.ScrolledText(log_wrap, height=12, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _update_term_codes_state(self) -> None:
        mode = self.TERM_MODE_LABEL_TO_VALUE.get(self.term_mode_var.get(), "current")
        if mode == "specify":
            self.term_pick_inline.grid()
            self._ensure_term_list_loaded()
        else:
            self.term_pick_inline.grid_remove()

    def _update_term_pick_summary(self) -> None:
        self.term_pick_summary.configure(text=f"已选 {len(self.selected_term_codes)} 个学期")

    def _get_current_term(self) -> Optional[Dict[str, str]]:
        if not self.available_terms:
            return None
        if self.current_term_index < 0 or self.current_term_index >= len(self.available_terms):
            return None
        return self.available_terms[self.current_term_index]

    def _render_current_term(self) -> None:
        term = self._get_current_term()
        if term is None:
            self.term_current_label.configure(text="未加载学期")
            self.term_prev_btn.configure(state=tk.DISABLED)
            self.term_next_btn.configure(state=tk.DISABLED)
            self.term_current_check.configure(state=tk.DISABLED)
            self.current_term_selected_var.set(False)
            self._update_term_pick_summary()
            return

        name = str(term.get("mc", "") or "未知学期")
        is_current = str(term.get("dqxq", "") or "") == "1"
        index_text = f"{self.current_term_index + 1}/{len(self.available_terms)}"
        display = f"{name}（当前）" if is_current else name
        self.term_current_label.configure(text=f"{index_text} {display}")

        code = str(term.get("dm", "") or "")
        self.current_term_selected_var.set(code in self.selected_term_code_set if code else False)
        self.term_current_check.configure(state=tk.NORMAL)
        self.term_prev_btn.configure(state=tk.NORMAL if self.current_term_index > 0 else tk.DISABLED)
        self.term_next_btn.configure(
            state=tk.NORMAL if self.current_term_index < len(self.available_terms) - 1 else tk.DISABLED
        )
        self._update_term_pick_summary()

    def _show_prev_term(self) -> None:
        if self.current_term_index <= 0:
            return
        self.current_term_index -= 1
        self._render_current_term()

    def _show_next_term(self) -> None:
        if self.current_term_index >= len(self.available_terms) - 1:
            return
        self.current_term_index += 1
        self._render_current_term()

    def _toggle_current_term_selection(self) -> None:
        term = self._get_current_term()
        if term is None:
            return
        code = str(term.get("dm", "") or "")
        if not code:
            return
        if bool(self.current_term_selected_var.get()):
            self.selected_term_code_set.add(code)
        else:
            self.selected_term_code_set.discard(code)
        self._sync_selected_terms_from_set()
        self._render_current_term()

    def _on_school_key_release(self, _event: tk.Event) -> None:
        self.selected_school = None
        if self.school_search_after_id:
            try:
                self.root.after_cancel(self.school_search_after_id)
            except Exception:
                pass
        self.school_search_after_id = self.root.after(280, self._refresh_school_suggestions)

    def _on_school_combo_selected(self, _event: tk.Event) -> None:
        text = self.school_var.get().strip()
        school = self.school_suggestion_map.get(text)
        if school:
            self.selected_school = school
            self.school_var.set(str(school.get("xxmc", "") or text))
        else:
            self.selected_school = None

    def _refresh_school_suggestions(self) -> None:
        self.school_search_after_id = None
        keyword = self.school_var.get().strip()
        if len(keyword) < 2:
            self.school_combo.configure(values=[])
            self.school_suggestion_map = {}
            return

        try:
            client = XiQueErClient(timeout=min(DEFAULT_TIMEOUT, 10))
            schools = client.search_schools(keyword)
        except Exception:
            return

        values: List[str] = []
        mapping: Dict[str, Dict[str, str]] = {}
        for school in schools[:40]:
            name = str(school.get("xxmc", "") or "").strip()
            code = str(school.get("xxdm", "") or "").strip()
            if not name:
                continue
            label = f"{name}（{code}）" if code else name
            if label in mapping:
                continue
            mapping[label] = school
            values.append(label)

        self.school_suggestion_map = mapping
        self.school_combo.configure(values=values)
        if values and self.school_combo.focus_get() == self.school_combo:
            try:
                self.school_combo.event_generate("<Down>")
            except Exception:
                pass

    def _build_login_context(self) -> Tuple[XiQueErClient, Dict[str, str], LoginState]:
        school_text = self.school_var.get().strip()
        school_name = school_text
        account = self.account_var.get().strip()
        password = self.password_var.get()
        if not school_name:
            raise RuntimeError("学校不能为空")
        if not account:
            raise RuntimeError("账号不能为空")
        if not password:
            raise RuntimeError("密码不能为空")
        try:
            timeout = int(self.timeout_var.get().strip() or str(DEFAULT_TIMEOUT))
        except ValueError:
            raise RuntimeError("超时必须是整数")
        if timeout <= 0:
            raise RuntimeError("超时必须大于 0")

        client = XiQueErClient(timeout=timeout)
        picked = self.school_suggestion_map.get(school_text)
        if picked:
            school = picked
            school_name = str(school.get("xxmc", "") or school_text)
            self.selected_school = school
            self.school_var.set(school_name)
        elif self.selected_school and str(self.selected_school.get("xxmc", "") or "") == school_name:
            school = self.selected_school
        else:
            school_name = re.sub(r"（[^）]*）$", "", school_name).strip()
            school = client.find_school(school_name)
            self.selected_school = school
            self.school_var.set(str(school.get("xxmc", "") or school_name))
        state = client.login(account, password, school)
        return client, school, state

    def _populate_term_list(self, terms: List[Dict[str, str]]) -> None:
        old_selected = set(self.selected_term_code_set)
        self.available_terms = list(terms)
        available_codes = {str(t.get("dm", "") or "") for t in self.available_terms if str(t.get("dm", "") or "")}
        self.selected_term_code_set = {c for c in old_selected if c in available_codes}
        self._sync_selected_terms_from_set()

        if not self.available_terms:
            self.current_term_index = 0
            self._render_current_term()
            return

        if self.current_term_index >= len(self.available_terms):
            self.current_term_index = len(self.available_terms) - 1
        if self.current_term_index < 0:
            self.current_term_index = 0
        if self.selected_term_code_set:
            for i, term in enumerate(self.available_terms):
                code = str(term.get("dm", "") or "")
                if code in self.selected_term_code_set:
                    self.current_term_index = i
                    break
        else:
            for i, term in enumerate(self.available_terms):
                if str(term.get("dqxq", "") or "") == "1":
                    self.current_term_index = i
                    break
        self._render_current_term()

    def _sync_selected_terms_from_set(self) -> None:
        self.selected_term_codes = []
        self.selected_term_labels = []
        for term in self.available_terms:
            code = str(term.get("dm", "") or "")
            if not code:
                continue
            if code in self.selected_term_code_set:
                name = str(term.get("mc", "") or "")
                self.selected_term_codes.append(code)
                self.selected_term_labels.append(name or code)
        self._update_term_pick_summary()

    def _ensure_term_list_loaded(self) -> None:
        cache_key = (
            self.school_var.get().strip(),
            self.account_var.get().strip(),
            self.password_var.get(),
        )
        if not all(cache_key):
            self.available_terms = []
            self.selected_term_code_set.clear()
            self.selected_term_codes = []
            self.selected_term_labels = []
            self.current_term_index = 0
            self.term_list_cache_key = ("", "", "")
            self._render_current_term()
            return
        if self.available_terms and cache_key == self.term_list_cache_key:
            self._render_current_term()
            return
        self._reload_term_list(show_error=False)

    def _reload_term_list(self, show_error: bool = True) -> None:
        try:
            client, _school, state = self._build_login_context()
            terms = client.get_terms(state)
            self.term_list_cache_key = (
                self.school_var.get().strip(),
                self.account_var.get().strip(),
                self.password_var.get(),
            )
            self._populate_term_list(terms)
            self._log(f"已加载学期数：{len(terms)}")
        except Exception as exc:
            self.available_terms = []
            self.selected_term_code_set.clear()
            self.selected_term_codes = []
            self.selected_term_labels = []
            self.current_term_index = 0
            self.term_list_cache_key = ("", "", "")
            self._render_current_term()
            self.term_pick_summary.configure(text="学期列表加载失败")
            if show_error:
                messagebox.showerror("获取学期失败", str(exc))

    def _pick_csv_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择 CSV 输出文件",
            defaultextension=".csv",
            initialdir=str(SCRIPT_DIR),
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if path:
            self.output_csv_var.set(path)

    def _pick_ics_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择 ICS 输出文件",
            defaultextension=".ics",
            initialdir=str(SCRIPT_DIR),
            filetypes=[("ICS 日历", "*.ics"), ("所有文件", "*.*")],
        )
        if path:
            self.output_ics_var.set(path)

    def _log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.root.update_idletasks()

    def _build_options(self) -> ExportOptions:
        school = self.school_var.get().strip()
        account = self.account_var.get().strip()
        password = self.password_var.get()
        if not school:
            raise RuntimeError("学校不能为空")
        if not account:
            raise RuntimeError("账号不能为空")
        if not password:
            raise RuntimeError("密码不能为空")

        try:
            timeout = int(self.timeout_var.get().strip() or "20")
        except ValueError:
            raise RuntimeError("超时必须是整数")
        if timeout <= 0:
            raise RuntimeError("超时必须大于 0")

        term_mode = self.TERM_MODE_LABEL_TO_VALUE.get(self.term_mode_var.get(), "current")
        if term_mode == "specify":
            self._ensure_term_list_loaded()
            self._sync_selected_terms_from_set()
            term_codes = list(self.selected_term_codes)
            if not term_codes:
                raise RuntimeError("学期模式为“特定”时，请在界面中选择至少一个学期")
        else:
            term_codes = []

        csv_text = self.output_csv_var.get().strip() or DEFAULT_OUTPUT_FILE
        output_csv = resolve_output_path(csv_text)

        output_ics: Optional[Path] = None
        if self.export_ics_var.get():
            ics_text = self.output_ics_var.get().strip()
            if ics_text:
                output_ics = resolve_output_path(ics_text)

        csv_fields = self.csv_picker.get_selected_keys()
        if not csv_fields:
            raise RuntimeError("CSV 至少要选择一个字段")

        desc_fields = self.desc_picker.get_selected_keys()
        if self.export_ics_var.get() and not desc_fields:
            raise RuntimeError("导出 ICS 时，DESCRIPTION 至少要选择一个字段")

        return ExportOptions(
            school_name=school,
            account=account,
            password=password,
            timeout=timeout,
            term_mode=term_mode,
            term_codes=term_codes,
            output_csv=output_csv,
            split_by_term=bool(self.split_by_term_var.get()),
            export_ics=bool(self.export_ics_var.get()),
            output_ics=output_ics,
            csv_fields=csv_fields,
            ics_desc_fields=desc_fields,
        )

    def _ask_time_conflict_choice(self, conflicts: List[Tuple[int, PeriodTime, PeriodTime]]) -> str:
        dlg = tk.Toplevel(self.root)
        dlg.title("作息时间冲突")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("780x420")

        ttk.Label(dlg, text="教务作息与个人作息存在冲突，请选择使用版本：").pack(anchor="w", padx=10, pady=(10, 4))
        text = scrolledtext.ScrolledText(dlg, height=14)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        text.insert("1.0", build_conflicts_text(conflicts))
        text.configure(state=tk.DISABLED)

        choice_var = tk.StringVar(value="sksj")
        pick = ttk.Frame(dlg)
        pick.pack(fill=tk.X, padx=10, pady=4)
        ttk.Radiobutton(pick, text="使用教务作息", value="jwsj", variable=choice_var).pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(pick, text="使用个人作息", value="sksj", variable=choice_var).pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(pick, text="不使用时间", value="none", variable=choice_var).pack(side=tk.LEFT, padx=6)

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=10, pady=(4, 10))
        done = {"ok": False}

        def confirm() -> None:
            done["ok"] = True
            dlg.destroy()

        ttk.Button(btns, text="确定", command=confirm).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btns, text="取消(默认个人作息)", command=dlg.destroy).pack(side=tk.RIGHT, padx=6)
        self.root.wait_window(dlg)
        if not done["ok"]:
            return "sksj"
        return choice_var.get()

    def _choose_time_profile_gui(
        self,
        jwsj_profile: TimeProfile,
        sksj_profile: TimeProfile,
    ) -> Tuple[Dict[int, PeriodTime], str]:
        jwsj_map = jwsj_profile.periods
        sksj_map = sksj_profile.periods

        if jwsj_map:
            self._log(f"教务系统作息：{len(jwsj_map)} 节")
        else:
            self._log(f"教务系统作息：未读取到（{jwsj_profile.message or '无数据'}）")

        if sksj_map:
            self._log(f"个人设置作息：{len(sksj_map)} 节")
        else:
            self._log(f"个人设置作息：未读取到（{sksj_profile.message or '无数据'}）")

        if not jwsj_map and not sksj_map:
            return {}, ""
        if jwsj_map and not sksj_map:
            return jwsj_map, "jwsj"
        if sksj_map and not jwsj_map:
            return sksj_map, "sksj"

        conflicts = collect_time_conflicts(jwsj_map, sksj_map)
        if not conflicts:
            return merge_time_profiles(jwsj_map, sksj_map), "merged"

        choice = self._ask_time_conflict_choice(conflicts)
        if choice == "jwsj":
            return jwsj_map, "jwsj"
        if choice == "none":
            return {}, ""
        return sksj_map, "sksj"

    def _on_export(self) -> None:
        self.export_btn.configure(state=tk.DISABLED)
        try:
            self._run_export()
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            self._log(f"导出失败：{exc}")
        finally:
            self.export_btn.configure(state=tk.NORMAL)

    @staticmethod
    def _course_row_key(row: Dict[str, str]) -> Tuple[str, ...]:
        return (
            str(row.get("term_code", "") or ""),
            str(row.get("course_name", "") or ""),
            str(row.get("teacher", "") or ""),
            str(row.get("location", "") or ""),
            str(row.get("weekday_num", "") or ""),
            str(row.get("sections", "") or ""),
            str(row.get("section_codes", "") or ""),
            str(row.get("weeks", "") or ""),
            str(row.get("teaching_class_code", "") or ""),
            str(row.get("course_code", "") or ""),
            str(row.get("course_alias_code", "") or ""),
        )

    def _fetch_term_payload(
        self,
        client: XiQueErClient,
        school: Dict[str, str],
        state: LoginState,
        account: str,
        password: str,
        term_code: str,
        week: str = "",
    ) -> Tuple[Dict, LoginState]:
        try:
            return client.get_term_timetable(state, term_code, week=week), state
        except RuntimeError as exc:
            if "其它设备上登录" not in str(exc):
                raise
            state = client.login(account, password, school)
            return client.get_term_timetable(state, term_code, week=week), state

    def _collect_term_rows_for_export(
        self,
        client: XiQueErClient,
        school: Dict[str, str],
        state: LoginState,
        opts: ExportOptions,
        term_code: str,
        term_name: str,
        selected_period_map: Dict[int, PeriodTime],
        selected_time_source: str,
    ) -> Tuple[List[Dict[str, str]], Dict[str, str], LoginState]:
        first_payload, state = self._fetch_term_payload(
            client=client,
            school=school,
            state=state,
            account=opts.account,
            password=opts.password,
            term_code=term_code,
            week="",
        )

        max_week = 20
        try:
            parsed_max_week = int(str(first_payload.get("maxzc", "") or "").strip())
            if parsed_max_week > 0:
                max_week = min(parsed_max_week, 30)
        except ValueError:
            pass

        merged_rows: List[Dict[str, str]] = []
        seen_row_keys: set[Tuple[str, ...]] = set()
        qssj = str(first_payload.get("qssj", "") or "")
        zc = str(first_payload.get("zc", "") or "")

        for week in range(1, max_week + 1):
            payload, state = self._fetch_term_payload(
                client=client,
                school=school,
                state=state,
                account=opts.account,
                password=opts.password,
                term_code=term_code,
                week=str(week),
            )
            if not qssj:
                qssj = str(payload.get("qssj", "") or "")
            if not zc:
                zc = str(payload.get("zc", "") or "")

            week_rows = flatten_term_courses(
                timetable=payload,
                account=opts.account,
                school_name=state.school_name or school.get("xxmc", opts.school_name),
                school_code=state.school_code or school.get("xxdm", ""),
                user_id=state.user_id,
                term_code=term_code,
                term_name=term_name,
            )
            apply_period_time_to_rows(
                rows=week_rows,
                period_map=selected_period_map,
                time_source=selected_time_source,
            )
            for row in week_rows:
                row_key = self._course_row_key(row)
                if row_key in seen_row_keys:
                    continue
                seen_row_keys.add(row_key)
                merged_rows.append(row)

        if not merged_rows:
            fallback_rows = flatten_term_courses(
                timetable=first_payload,
                account=opts.account,
                school_name=state.school_name or school.get("xxmc", opts.school_name),
                school_code=state.school_code or school.get("xxdm", ""),
                user_id=state.user_id,
                term_code=term_code,
                term_name=term_name,
            )
            apply_period_time_to_rows(
                rows=fallback_rows,
                period_map=selected_period_map,
                time_source=selected_time_source,
            )
            for row in fallback_rows:
                row_key = self._course_row_key(row)
                if row_key in seen_row_keys:
                    continue
                seen_row_keys.add(row_key)
                merged_rows.append(row)

        return merged_rows, {"qssj": qssj, "zc": zc}, state

    def _run_export(self) -> None:
        opts = self._build_options()
        self._log("开始导出...")
        self._log(f"学校={opts.school_name} 账号={opts.account} 学期模式={opts.term_mode}")

        client = XiQueErClient(timeout=opts.timeout)
        school = client.find_school(opts.school_name)
        state = client.login(opts.account, opts.password, school)
        self._log(f"登录成功：{state.school_name}（{state.school_code}）")

        try:
            jwsj_profile = client.fetch_jwsj_time(state)
        except RuntimeError as exc:
            if "其它设备上登录" in str(exc):
                state = client.login(opts.account, opts.password, school)
                jwsj_profile = client.fetch_jwsj_time(state)
            else:
                jwsj_profile = TimeProfile("jwsj", "教务系统作息", False, str(exc), {})

        try:
            sksj_profile = client.fetch_sksj_time(state)
        except RuntimeError as exc:
            if "其它设备上登录" in str(exc):
                state = client.login(opts.account, opts.password, school)
                sksj_profile = client.fetch_sksj_time(state)
            else:
                sksj_profile = TimeProfile("sksj", "个人设置作息", False, str(exc), {})

        selected_period_map, selected_time_source = self._choose_time_profile_gui(jwsj_profile, sksj_profile)
        if not selected_period_map:
            keep = messagebox.askyesno(
                "未读取到时间",
                "未读取到上课时间配置，是否继续导出（仅基础课表 CSV）？",
            )
            if not keep:
                self._log("用户取消导出。")
                return

        terms = client.get_terms(state)
        term_name_map = {str(t.get("dm", "")): str(t.get("mc", "")) for t in terms}
        candidate_terms = resolve_candidate_terms(terms, opts.term_mode, opts.term_codes)

        term_rows_map: Dict[str, List[Dict[str, str]]] = {}
        term_meta_map: Dict[str, Dict[str, str]] = {}
        for term_code in candidate_terms:
            term_name = term_name_map.get(term_code, "")
            self._log(f"拉取学期 {term_code} {term_name} ...")
            rows, term_meta, state = self._collect_term_rows_for_export(
                client=client,
                school=school,
                state=state,
                opts=opts,
                term_code=term_code,
                term_name=term_name,
                selected_period_map=selected_period_map,
                selected_time_source=selected_time_source,
            )
            term_rows_map[term_code] = rows
            term_meta_map[term_code] = term_meta
            self._log(f"  -> {len(rows)} 条课程")

        selected_terms = candidate_terms

        selected_rows: List[Dict[str, str]] = []
        for code in selected_terms:
            selected_rows.extend(term_rows_map.get(code, []))
        if not selected_rows:
            raise RuntimeError("所选学期没有课表数据")

        total_count = export_csv(selected_rows, opts.output_csv, opts.csv_fields)
        self._log(f"CSV 导出完成：{total_count} 条 -> {opts.output_csv}")
        self._log(f"时间来源：{selected_time_source or '未使用'}")

        split_files: List[Tuple[str, Path, int]] = []
        if opts.split_by_term and len(selected_terms) > 1:
            suffix = opts.output_csv.suffix or ".csv"
            for code in selected_terms:
                rows = term_rows_map.get(code, [])
                if not rows:
                    continue
                term_name = term_name_map.get(code, "")
                out_path = opts.output_csv.parent / f"{opts.output_csv.stem}_{code}_{safe_file_component(term_name)}{suffix}"
                count = export_csv(rows, out_path, opts.csv_fields)
                split_files.append((code, out_path, count))
            self._log(f"已按学期拆分导出 {len(split_files)} 个文件")

        ics_result = ""
        if opts.export_ics:
            if not selected_period_map:
                self._log("ICS 跳过：无可用上课时间")
            else:
                term_first_monday_map: Dict[str, date] = {}
                unresolved_terms: List[str] = []
                for code in selected_terms:
                    if not term_rows_map.get(code):
                        continue
                    first_monday = derive_first_monday(meta=term_meta_map.get(code, {}))
                    if first_monday is None:
                        unresolved_terms.append(code)
                    else:
                        term_first_monday_map[code] = first_monday

                for code in unresolved_terms:
                    name = term_name_map.get(code, "")
                    while True:
                        text = simpledialog.askstring(
                            "填写学期起始日",
                            f"{code} {name}\n请输入第一周周一（YYYY-MM-DD），留空则跳过该学期：",
                            parent=self.root,
                        )
                        if text is None or not text.strip():
                            break
                        try:
                            term_first_monday_map[code] = datetime.strptime(text.strip(), "%Y-%m-%d").date()
                            break
                        except ValueError:
                            messagebox.showwarning("日期格式错误", "请按 YYYY-MM-DD 输入。")

                if not term_first_monday_map:
                    self._log("ICS 跳过：没有可用的学期起始日期")
                else:
                    ics_output = opts.output_ics or opts.output_csv.with_suffix(".ics")
                    event_count, stats = export_ics(
                        rows=selected_rows,
                        period_map=selected_period_map,
                        term_first_monday_map=term_first_monday_map,
                        output_path=ics_output,
                        timezone_name=DEFAULT_ICS_TIMEZONE,
                        calendar_name=f"{state.school_name}_{opts.account}_课表",
                        description_fields=opts.ics_desc_fields,
                    )
                    ics_result = f"\nICS：{event_count} 个事件 -> {ics_output}"
                    self._log(f"ICS 导出完成：{event_count} 个事件 -> {ics_output}")
                    if any(stats.values()):
                        self._log(
                            "ICS 跳过统计："
                            f" 无学期起始日={stats['skip_no_term_start']},"
                            f" 无周次={stats['skip_no_week']},"
                            f" 无节次={stats['skip_no_section']},"
                            f" 缺少节次时间={stats['skip_no_period_time']}"
                        )

        summary = (
            f"导出完成\n"
            f"学校：{state.school_name}（{state.school_code}）\n"
            f"账号：{opts.account}\n"
            f"学期数：{len(selected_terms)}\n"
            f"CSV：{total_count} 条 -> {opts.output_csv}"
            f"{ics_result}"
        )
        messagebox.showinfo("完成", summary)


def launch_gui() -> None:
    root = tk.Tk()
    XiQueErGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()

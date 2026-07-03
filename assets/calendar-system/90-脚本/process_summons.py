from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET


SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt"}
ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "01-待识别传票"
TEXT_DIR = ROOT / "02-识别文本"
PENDING_DIR = ROOT / "03-待确认日程"
ICS_DIR = ROOT / "04-日历导出"
DONE_DIR = ROOT / "05-已处理传票"
FAILED_DIR = ROOT / "06-识别失败"
SYNC_LOG_DIR = ROOT / "07-同步日志"
SYNC_FAILED_DIR = ROOT / "08-同步失败"
TZID = "Asia/Shanghai"
LOCAL_TZ = timezone(timedelta(hours=8))
ICLOUD_CONFIG_ENV = "INTELFLOW_ICLOUD_CONFIG"
LOCAL_TOOL_ROOTS = [
    Path(r"E:\Codex-Local-Tools-NoSync"),
    Path(r"C:\Codex-Local-Tools-NoSync"),
]
LOCAL_TEMP_ROOTS = [
    Path(r"E:\Codex-Local-Temp-NoSync"),
    Path(r"C:\Codex-Local-Temp-NoSync"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class ExtractedEvent:
    source_file: str
    source_sha256: str
    title: str
    start: str | None
    end: str | None
    court: str | None
    case_number: str | None
    location: str | None
    hearing_room: str | None
    confidence: str
    warnings: list[str]
    description: str
    calendar_sync: dict | None = None


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


class CalDavError(RuntimeError):
    pass


class CalDavClient:
    def __init__(self, apple_id: str, app_specific_password: str, base_url: str = "https://caldav.icloud.com") -> None:
        self.apple_id = apple_id
        self.app_specific_password = app_specific_password
        self.base_url = base_url.rstrip("/") + "/"
        self.opener = build_opener()

    def _auth_header(self) -> str:
        token = f"{self.apple_id}:{self.app_specific_password}".encode("utf-8")
        return "Basic " + base64.b64encode(token).decode("ascii")

    def request(self, method: str, url: str, body: str | bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, str]:
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth_header())
        req.add_header("User-Agent", "IntelFlow-Court-Calendar/1.0")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with self.opener.open(req, timeout=45) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return exc.code, detail
        except URLError as exc:
            raise CalDavError(f"CalDAV 网络错误：{exc.reason}") from exc

    def propfind(self, url: str, body: str, depth: int = 0) -> ET.Element:
        status, response = self.request(
            "PROPFIND",
            url,
            body,
            {
                "Depth": str(depth),
                "Content-Type": "application/xml; charset=utf-8",
            },
        )
        if status not in {207, 200}:
            raise CalDavError(f"PROPFIND 返回异常状态：{status} {response[:300]}")
        return ET.fromstring(response)

    @staticmethod
    def first_text(root: ET.Element, local_name: str) -> str | None:
        for elem in root.iter():
            if elem.tag.endswith("}" + local_name) and elem.text:
                return elem.text.strip()
        return None

    @staticmethod
    def href_inside(root: ET.Element, local_name: str) -> str | None:
        for elem in root.iter():
            if elem.tag.endswith("}" + local_name):
                for child in elem.iter():
                    if child.tag.endswith("}href") and child.text:
                        return child.text.strip()
        return None

    @staticmethod
    def response_nodes(root: ET.Element) -> list[ET.Element]:
        return [elem for elem in root.iter() if elem.tag.endswith("}response")]

    @staticmethod
    def href_from_response(response: ET.Element) -> str | None:
        for elem in response.iter():
            if elem.tag.endswith("}href") and elem.text:
                return elem.text.strip()
        return None

    @staticmethod
    def has_calendar_resource(response: ET.Element) -> bool:
        for elem in response.iter():
            if elem.tag.endswith("}calendar"):
                return True
        return False

    @staticmethod
    def display_name(response: ET.Element) -> str | None:
        for elem in response.iter():
            if elem.tag.endswith("}displayname") and elem.text:
                return elem.text.strip()
        return None

    def absolute_url(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return urljoin(self.base_url, href.lstrip("/"))

    def current_user_principal(self) -> str:
        body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:current-user-principal />
  </d:prop>
</d:propfind>"""
        root = self.propfind(self.base_url, body, depth=0)
        href = self.href_inside(root, "current-user-principal")
        if not href:
            raise CalDavError("未能发现 iCloud current-user-principal。")
        return self.absolute_url(href)

    def calendar_home_set(self) -> str:
        principal = self.current_user_principal()
        body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <c:calendar-home-set />
  </d:prop>
</d:propfind>"""
        root = self.propfind(principal, body, depth=0)
        href = self.href_inside(root, "calendar-home-set")
        if not href:
            raise CalDavError("未能发现 iCloud calendar-home-set。")
        return self.absolute_url(href)

    def list_calendars(self) -> list[dict[str, str]]:
        home = self.calendar_home_set()
        body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:resourcetype />
    <d:displayname />
  </d:prop>
</d:propfind>"""
        root = self.propfind(home, body, depth=1)
        calendars: list[dict[str, str]] = []
        for response in self.response_nodes(root):
            if not self.has_calendar_resource(response):
                continue
            href = self.href_from_response(response)
            if not href:
                continue
            calendars.append(
                {
                    "name": self.display_name(response) or "",
                    "url": self.absolute_url(href).rstrip("/") + "/",
                }
            )
        return calendars

    def select_calendar_url(self, calendar_name: str | None = None, calendar_url: str | None = None) -> str:
        if calendar_url:
            return calendar_url.rstrip("/") + "/"
        calendars = self.list_calendars()
        if not calendars:
            raise CalDavError("未发现可用 iCloud 日历。")
        if calendar_name:
            for calendar in calendars:
                if calendar["name"] == calendar_name:
                    return calendar["url"]
            names = "、".join(calendar["name"] or "(未命名)" for calendar in calendars)
            raise CalDavError(f"未找到名为“{calendar_name}”的日历。可用日历：{names}")
        for preferred in ["开庭日程", "Calendar", "日历", "Home", "工作"]:
            for calendar in calendars:
                if calendar["name"] == preferred:
                    return calendar["url"]
        return calendars[0]["url"]

    def put_event(self, event: ExtractedEvent, calendar_name: str | None = None, calendar_url: str | None = None) -> str:
        calendar = self.select_calendar_url(calendar_name=calendar_name, calendar_url=calendar_url)
        uid = calendar_uid(event)
        event_url = urljoin(calendar, quote(uid + ".ics"))
        payload = build_icalendar(event)
        status, _ = self.request(
            "PUT",
            event_url,
            payload,
            {
                "Content-Type": "text/calendar; charset=utf-8",
                "If-None-Match": "*",
            },
        )
        if status in {200, 201, 204}:
            return event_url

        # If the event already exists, update it idempotently.
        if status == 412:
            status, _ = self.request(
                "PUT",
                event_url,
                payload,
                {"Content-Type": "text/calendar; charset=utf-8"},
            )
            if status in {200, 201, 204}:
                return event_url
        raise CalDavError(f"写入 iCloud 日历返回异常状态：{status}")


def load_icloud_config() -> dict:
    config_path = Path(os.environ.get(ICLOUD_CONFIG_ENV, str(default_icloud_config_path())))
    if not config_path.exists():
        return {
            "enabled": False,
            "config_path": str(config_path),
            "reason": "未找到本机 iCloud 配置文件。",
        }
    with config_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    data["config_path"] = str(config_path)
    data["enabled"] = bool(data.get("enabled"))
    return data


def sync_event_to_icloud(event: ExtractedEvent) -> dict:
    config = load_icloud_config()
    if not config.get("enabled"):
        return {
            "enabled": False,
            "status": "skipped",
            "config_path": config.get("config_path"),
            "message": config.get("reason") or "iCloud 同步未启用。",
        }
    if not event.start or not event.end:
        return {"enabled": True, "status": "skipped", "message": "缺少开始或结束时间，未同步。"}
    apple_id = config.get("apple_id") or os.environ.get("ICLOUD_APPLE_ID")
    password = config.get("app_specific_password") or os.environ.get("ICLOUD_APP_SPECIFIC_PASSWORD")
    if not apple_id or not password:
        return {
            "enabled": True,
            "status": "failed",
            "config_path": config.get("config_path"),
            "message": "缺少 apple_id 或 app_specific_password。",
        }
    client = CalDavClient(
        apple_id=apple_id,
        app_specific_password=password,
        base_url=config.get("base_url", "https://caldav.icloud.com"),
    )
    try:
        event_url = client.put_event(
            event,
            calendar_name=config.get("calendar_name"),
            calendar_url=config.get("calendar_url"),
        )
        return {
            "enabled": True,
            "status": "synced",
            "event_url": event_url,
            "calendar_name": config.get("calendar_name"),
        }
    except CalDavError as exc:
        return {
            "enabled": True,
            "status": "failed",
            "config_path": config.get("config_path"),
            "message": str(exc),
        }


def write_sync_log(event: ExtractedEvent, result: dict) -> Path:
    SYNC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SYNC_LOG_DIR / f"{stamp}-{event.source_sha256[:12]}-icloud-sync.json"
    payload = {
        "title": event.title,
        "start": event.start,
        "end": event.end,
        "case_number": event.case_number,
        "court": event.court,
        "sync": result,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def command_exists(name: str) -> bool:
    if shutil.which(name) is not None or shutil.which(f"{name}.exe") is not None:
        return True
    result = subprocess.run(
        ["where", name],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stem(path: Path) -> str:
    stem = re.sub(r'[<>:"/\\|?*\r\n\t]+', "-", path.stem).strip(". ")
    return stem or "untitled"


def default_icloud_config_path() -> Path:
    for root in LOCAL_TOOL_ROOTS:
        if root.exists():
            return root / "calendar-sync" / "icloud-calendar.json"
    return LOCAL_TOOL_ROOTS[0] / "calendar-sync" / "icloud-calendar.json"


def get_temp_root() -> Path:
    for preferred in LOCAL_TEMP_ROOTS:
        if preferred.exists():
            root = preferred / "calendar-summons-ocr"
            root.mkdir(parents=True, exist_ok=True)
            return root
    root = Path(tempfile.gettempdir()) / "calendar-summons-ocr"
    root.mkdir(parents=True, exist_ok=True)
    return root


def extract_text_from_pdf(path: Path) -> str:
    text = ""
    if command_exists("pdftotext"):
        result = run_command(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"])
        if result.returncode == 0:
            text = result.stdout.strip()

    if len(text) >= 40:
        return text

    # Fall back to OCR for scanned PDFs. Limit to first 3 pages in v1.
    if not command_exists("pdftoppm") or not command_exists("tesseract"):
        return text

    temp_root = get_temp_root()
    work = temp_root / f"{safe_stem(path)}-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    prefix = work / "page"
    render = run_command(["pdftoppm", "-r", "220", "-png", "-f", "1", "-l", "3", str(path), str(prefix)], timeout=180)
    if render.returncode != 0:
        return text

    chunks: list[str] = []
    for image in sorted(work.glob("page-*.png")):
        ocr = ocr_image(image)
        if ocr.strip():
            chunks.append(ocr)
    return "\n\n".join(chunks).strip() or text


def ocr_image(path: Path) -> str:
    if not command_exists("tesseract"):
        return ""
    result = run_command(["tesseract", str(path), "stdout", "-l", "chi_sim+eng", "--psm", "6"], timeout=180)
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        return ocr_image(path)
    return ""


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(
        r"(上午|下午|晚上|中午|晚)\s*[%％]\s*(\d{2})",
        r"\g<1>9时\2分",
        text,
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" ：:，,。;；")


def extract_court(text: str) -> str | None:
    for line in text.splitlines():
        if "人民法院" in line:
            match = re.search(r"([\u4e00-\u9fa5]{2,40}人民法院)", line)
            if match:
                return match.group(1)
        if "仲裁委员会" in line:
            match = re.search(r"([\u4e00-\u9fa5]{2,50}仲裁委员会)", line)
            if match:
                return match.group(1)
    match = re.search(r"([\u4e00-\u9fa5]{2,40}人民法院)", text)
    if match:
        return match.group(1)
    match = re.search(r"([\u4e00-\u9fa5]{2,50}仲裁委员会)", text)
    return match.group(1) if match else None


def extract_case_number(text: str) -> str | None:
    patterns = [
        r"[（(]\s*20\d{2}\s*[）)]\s*[\u4e00-\u9fa5A-Za-z0-9第初终执再民行刑申破保号之一二三四五六七八九十\-]+号",
        r"案号[:：]?\s*([^\n，。；;]{8,50}?号)",
        r"([深粤京沪穗杭广佛莞珠中][A-Za-z\u4e00-\u9fa5]{1,15}\s*(?:[（(][^）)(]{1,15}[）)])?\s*案\s*[【\[]\s*20\d{2}\s*[】\]]\s*\d+\s*号)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_line(match.group(1) if match.lastindex else match.group(0))
    return None


def extract_location(text: str) -> tuple[str | None, str | None]:
    hearing_room = None
    location = None
    lines = text.splitlines()
    for line in lines:
        line_clean = clean_line(line)
        if not line_clean:
            continue
        if "法庭" in line_clean or "审判庭" in line_clean or re.search(r"仲裁[一二三四五六七八九十\d]+庭", line_clean):
            room_match = re.search(
                r"(?:在|地点[:：]?|地址[:：]?)\s*((?:本院|我院)?第[一二三四五六七八九十\d]+(?:审判庭|法庭)(?:[（(][^）)]{1,20}[）)])?)",
                line_clean,
            )
            if not room_match:
                room_match = re.search(r"((?:本院|我院)?第[一二三四五六七八九十\d]+(?:审判庭|法庭)(?:[（(][^）)]{1,20}[）)])?)", line_clean)
            if not room_match:
                room_match = re.search(r"([A-Za-z0-9（）()\-]{1,20}(?:审判庭|法庭)(?:[（(][^）)]{1,20}[）)])?)", line_clean)
            if not room_match:
                room_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()\-]{1,30}仲裁[一二三四五六七八九十\d]+庭)", line_clean)
            hearing_room = room_match.group(1) if room_match else line_clean
            break
    for index, line in enumerate(lines):
        line_clean = clean_line(line)
        if not line_clean:
            continue
        if any(key in line_clean for key in ["地点", "地址", "法庭", "审判庭"]) or re.search(r"仲裁[一二三四五六七八九十\d]+庭", line_clean):
            if hearing_room:
                location = hearing_room
                location_match = re.search(r"(?:地点|地址)[:：]?\s*([^\n。；;]{2,80})", line_clean)
                if location_match:
                    location = clean_line(location_match.group(1))
                if ("(" in line_clean or "（" in line_clean) and not (")" in line_clean or "）" in line_clean):
                    for follow in lines[index + 1 : index + 3]:
                        follow_clean = clean_line(follow)
                        if follow_clean:
                            location = clean_line(f"{location} {follow_clean}")
                            break
                break
            location_match = re.search(r"(?:地点|地址)[:：]?\s*([^\n。；;]{2,80})", line_clean)
            location = clean_line(location_match.group(1)) if location_match else line_clean[:80]
            if ("(" in location or "（" in location) and not (")" in location or "）" in location):
                for follow in lines[index + 1 : index + 3]:
                    follow_clean = clean_line(follow)
                    if follow_clean:
                        location = clean_line(f"{location} {follow_clean}")
                        break
            break
    return location, hearing_room


def chinese_period_to_hour(period: str | None, hour: int) -> int:
    if not period:
        return hour
    if period in {"下午", "晚", "晚上"} and hour < 12:
        return hour + 12
    if period in {"中午"} and hour < 11:
        return hour + 12
    return hour


def datetime_candidates(text: str) -> list[tuple[datetime, int, str]]:
    candidates: list[tuple[datetime, int, str]] = []
    patterns = [
        re.compile(
            r"(?P<year>20\d{2})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
            r"(?:[^\d上午下午晚上中午]{0,8}(?P<period>上午|下午|晚上|中午|晚)?)?"
            r"\s*(?P<hour>\d{1,2})\s*(?:时|:|：)\s*(?P<minute>\d{1,2})?\s*(?:分)?"
        ),
        re.compile(
            r"(?P<year>20\d{2})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})"
            r"\s*(?P<period>上午|下午|晚上|中午|晚)?\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{1,2})"
        ),
    ]
    keyword_weights = {
        "开庭": 8,
        "到庭": 7,
        "审理": 4,
        "法庭": 4,
        "传唤": 4,
        "举证": -4,
        "答辩": -4,
        "落款": -5,
        "签发": -5,
        "送达": -3,
    }
    for pattern in patterns:
        for match in pattern.finditer(text):
            try:
                year = int(match.group("year"))
                month = int(match.group("month"))
                day = int(match.group("day"))
                hour = int(match.group("hour"))
                minute = int(match.group("minute") or "0")
                hour = chinese_period_to_hour(match.groupdict().get("period"), hour)
                dt = datetime(year, month, day, hour, minute)
            except ValueError:
                continue
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            context = text[start:end]
            score = 0
            for key, weight in keyword_weights.items():
                if key in context:
                    score += weight
            candidates.append((dt, score, clean_line(context)))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def build_event(path: Path, text: str, digest: str) -> ExtractedEvent:
    text = normalize_text(text)
    court = extract_court(text)
    case_number = extract_case_number(text)
    location, hearing_room = extract_location(text)
    candidates = datetime_candidates(text)
    warnings: list[str] = []

    start_dt: datetime | None = None
    if candidates:
        start_dt = candidates[0][0]
        if candidates[0][1] < 4:
            warnings.append("识别到日期时间，但上下文中开庭关键词较弱，请人工核对。")
    else:
        warnings.append("未能自动识别开庭日期时间，需要人工补充。")

    if not court:
        warnings.append("未能自动识别法院。")
    if not case_number:
        warnings.append("未能自动识别案号。")
    if not location:
        warnings.append("未能自动识别地点或法庭。")

    start = start_dt.strftime("%Y-%m-%d %H:%M") if start_dt else None
    end = None
    if start_dt:
        default_end_hour = 12 if start_dt.hour < 12 else 18
        end_dt = start_dt.replace(hour=default_end_hour, minute=0, second=0, microsecond=0)
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
        end = end_dt.strftime("%Y-%m-%d %H:%M")
    case_label = case_number or safe_stem(path)
    court_label = court or "法院待确认"
    title = f"开庭｜{case_label}｜{court_label}"

    confidence_points = sum(1 for value in [start, court, case_number, location or hearing_room] if value)
    confidence = "high" if confidence_points >= 4 and not warnings else "medium" if start else "low"

    description_parts = [
        "案号：" + (case_number or "待确认"),
        "法院：" + (court or "待确认"),
        "地点：" + (location or hearing_room or "待确认"),
        "识别置信度：" + confidence,
        "",
        "请在开庭前核对传票原件、证据原件、授权手续、代理词/质证意见、出行或线上登录安排。",
    ]
    if candidates:
        description_parts.extend(["", "日期时间候选："])
        for dt, score, context in candidates[:5]:
            description_parts.append(f"- {dt.strftime('%Y-%m-%d %H:%M')} | score={score} | {context[:120]}")

    return ExtractedEvent(
        source_file=str(path),
        source_sha256=digest,
        title=title,
        start=start,
        end=end,
        court=court,
        case_number=case_number,
        location=location,
        hearing_room=hearing_room,
        confidence=confidence,
        warnings=warnings,
        description="\n".join(description_parts),
    )


def ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def format_ics_dt(value: str) -> str:
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
    return dt.strftime("%Y%m%dT%H%M%S")


def calendar_uid(event: ExtractedEvent) -> str:
    return f"{event.source_sha256[:16]}@intel-flow-calendar"


def build_icalendar(event: ExtractedEvent) -> str:
    if not event.start or not event.end:
        raise ValueError("event.start and event.end are required")
    uid = calendar_uid(event)
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    alarms = [
        ("P7D", "开庭前7天：检查材料、证据、代理词准备进度"),
        ("P1D", "开庭前1天：核对传票、证据原件、授权手续"),
    ]
    alarm_blocks = []
    for trigger, description in alarms:
        alarm_blocks.append(
            "\n".join(
                [
                    "BEGIN:VALARM",
                    f"TRIGGER:-{trigger}",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{ics_escape(description)}",
                    "END:VALARM",
                ]
            )
        )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IntelFlow//Court Calendar v1//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VTIMEZONE",
        f"TZID:{TZID}",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "DTSTART:19700101T000000",
        "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now_utc}",
        f"DTSTART;TZID={TZID}:{format_ics_dt(event.start)}",
        f"DTEND;TZID={TZID}:{format_ics_dt(event.end)}",
        f"SUMMARY:{ics_escape(event.title)}",
        f"LOCATION:{ics_escape(event.location or event.hearing_room or '')}",
        f"DESCRIPTION:{ics_escape(event.description)}",
        "STATUS:CONFIRMED",
        *alarm_blocks,
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)


def write_outputs(path: Path, text: str, event: ExtractedEvent) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{safe_stem(path)}"
    text_path = TEXT_DIR / f"{base}.txt"
    json_path = PENDING_DIR / f"{base}-待确认日程.json"

    text_path.write_text(text, encoding="utf-8")
    json_path.write_text(
        json.dumps(event.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path, text_path


def move_processed(path: Path, success: bool, keep_original: bool, sync_failed: bool = False) -> Path:
    if keep_original:
        return path
    if sync_failed:
        target_dir = SYNC_FAILED_DIR
    else:
        target_dir = DONE_DIR if success else FAILED_DIR
    target = target_dir / path.name
    if target.exists():
        target = target_dir / f"{path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}"
    shutil.move(str(path), str(target))
    return target


def process_file(path: Path, keep_original: bool = False) -> bool:
    digest = sha256_file(path)
    log(f"处理：{path.name}")
    text = extract_text(path)
    text = normalize_text(text)
    if not text:
        failure = {
            "source_file": str(path),
            "source_sha256": digest,
            "error": "未能抽取或 OCR 出文字。请确认文件清晰，或检查 tesseract/pdftotext 是否可用。",
        }
        failure_path = FAILED_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe_stem(path)}-识别失败.json"
        failure_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        move_processed(path, success=False, keep_original=keep_original)
        log(f"失败：{path.name}")
        return False

    event = build_event(path, text, digest)
    sync_result = sync_event_to_icloud(event)
    event.calendar_sync = sync_result
    if sync_result.get("enabled") or sync_result.get("status") in {"synced", "failed"}:
        sync_log = write_sync_log(event, sync_result)
        log(f"已写入同步日志：{sync_log.name}")
    sync_failed = sync_result.get("enabled") is True and sync_result.get("status") == "failed"

    final_source = move_processed(path, success=bool(event.start), keep_original=keep_original, sync_failed=sync_failed)
    if final_source != path:
        event.source_file = str(final_source)
    json_path, text_path = write_outputs(path, text, event)
    log(f"已生成待确认记录：{json_path.name}")
    log(f"已保存识别文本：{text_path.name}")
    if sync_result.get("status") == "synced":
        log("已同步到 iCloud 日历。")
    elif sync_result.get("status") == "failed":
        log(f"iCloud 同步失败：{sync_result.get('message')}")
    else:
        log(sync_result.get("message", "iCloud 同步未启用。"))
    return not sync_failed


def pending_files() -> list[Path]:
    files = [p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def run_once(keep_original: bool = False) -> int:
    for directory in [INBOX, TEXT_DIR, PENDING_DIR, DONE_DIR, FAILED_DIR, SYNC_LOG_DIR, SYNC_FAILED_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    files = pending_files()
    if not files:
        log("没有待处理文件。")
        return 0
    ok = 0
    for path in files:
        try:
            if process_file(path, keep_original=keep_original):
                ok += 1
        except Exception as exc:
            error_path = FAILED_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe_stem(path)}-异常.json"
            error_path.write_text(
                json.dumps({"source_file": str(path), "error": repr(exc)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log(f"异常：{path.name} | {exc}")
    return ok


def write_listener_pid() -> None:
    SYNC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    (SYNC_LOG_DIR / "listener.pid").write_text(str(os.getpid()), encoding="utf-8")


def watch(interval: int, keep_original: bool) -> None:
    write_listener_pid()
    log(f"开始监听：{INBOX}")
    log("按 Ctrl+C 停止。")
    seen: dict[str, float] = {}
    while True:
        for path in pending_files():
            # Wait until the file's mtime is stable enough to avoid processing half-copied files.
            mtime = path.stat().st_mtime
            key = str(path)
            if key not in seen:
                seen[key] = mtime
                continue
            if seen[key] == mtime:
                process_file(path, keep_original=keep_original)
                seen.pop(key, None)
            else:
                seen[key] = mtime
        time.sleep(interval)


def check_icloud_connection() -> int:
    config = load_icloud_config()
    if not config.get("enabled"):
        log(f"iCloud 同步未启用。配置文件位置：{config.get('config_path')}")
        return 1
    apple_id = config.get("apple_id") or os.environ.get("ICLOUD_APPLE_ID")
    password = config.get("app_specific_password") or os.environ.get("ICLOUD_APP_SPECIFIC_PASSWORD")
    if not apple_id or not password:
        log("配置中缺少 apple_id 或 app_specific_password。")
        return 1
    client = CalDavClient(
        apple_id=apple_id,
        app_specific_password=password,
        base_url=config.get("base_url", "https://caldav.icloud.com"),
    )
    try:
        calendars = client.list_calendars()
    except CalDavError as exc:
        log(f"iCloud 连接失败：{exc}")
        return 1
    if not calendars:
        log("已连接 iCloud，但未发现可用日历。")
        return 1
    log("已连接 iCloud。可用日历：")
    for calendar in calendars:
        marker = " *" if config.get("calendar_name") and calendar["name"] == config.get("calendar_name") else ""
        print(f"- {calendar['name'] or '(未命名)'}{marker}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="识别传票/PDF/截图并自动写入 iCloud 日历。")
    parser.add_argument("--watch", action="store_true", help="持续监听 01-待识别传票。")
    parser.add_argument("--interval", type=int, default=5, help="监听间隔秒数，默认 5。")
    parser.add_argument("--keep-original", action="store_true", help="处理后保留原文件在待识别目录。")
    parser.add_argument("--check-icloud", action="store_true", help="检查 iCloud CalDAV 连接并列出日历。")
    args = parser.parse_args()

    if args.check_icloud:
        return check_icloud_connection()
    if args.watch:
        watch(args.interval, args.keep_original)
        return 0
    run_once(keep_original=args.keep_original)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ============================================================
# HOLLYWOODBETS SEO SERP RANK TRACKER
# ============================================================
# Purpose:
#   Search Google for a keyword, collect the Top 10 organic
#   results, and store one row per tracked result per day.
#
# Visible Excel structure:
#   Keyword | Name | Date | 00:00 ... 23:00 | Current Rank
#
# Design notes:
#   - Exactly 10 visible data rows per keyword/date.
#   - Each hourly capture updates the matching result row.
#   - Matching is done by a hidden stable result key (URL + title),
#     NOT by Name. This prevents duplicate names such as Betway from
#     overwriting each other's previous rank.
#   - A hidden _State sheet stores row/result identity only; it is not
#     part of the visible reporting sheet.
#   - Current Rank is an Excel formula returning the latest non-empty
#     hourly rank.
# ============================================================

import os
import sys
import time
import signal
import logging
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, quote_plus
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import FormulaRule
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

KEYWORD = "Aviator"
TARGET_DOMAIN = "hollywoodbets.net"
TIMEZONE = "Africa/Johannesburg"
NUMBER_OF_ORGANIC_RESULTS = 10
MINIMUM_ORGANIC_RESULTS = 5
GOOGLE_GL = "za"
GOOGLE_HL = "en"
GOOGLE_NUM = 20
HEADLESS = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "serp_chrome_profile_aviator")
EXCEL_FILE = os.path.join(BASE_DIR, "aviator_rankings.xlsx")
LOG_FILE = os.path.join(BASE_DIR, "aviator_seo.log")

HOURS = [f"{hour:02d}:00" for hour in range(24)]
EXCEL_HEADERS = ["Keyword", "Name", "Date"] + HOURS + ["Current Rank"]

TZ = ZoneInfo(TIMEZONE)


# ------------------------------------------------------------
# TIME
# ------------------------------------------------------------

def now_local() -> datetime:
    return datetime.now(TZ)


def hour_column_name(run_ts: datetime) -> str:
    return run_ts.strftime("%H:00")


# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------

logger = logging.getLogger("aviator_seo")
logger.setLevel(logging.INFO)

if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)


# ------------------------------------------------------------
# BROWSER
# ------------------------------------------------------------

class GoogleBlocked(RuntimeError):
    """Raised when Google serves a CAPTCHA or bot-detection page."""


class Browser:
    def __init__(self):
        self._pw = None
        self._context = None

    def start(self):
        if self._context is not None:
            return self._context

        os.makedirs(PROFILE_DIR, exist_ok=True)
        logger.info(
            "Starting Playwright with dedicated SERP Chrome profile: %s",
            PROFILE_DIR,
        )
        logger.info("Headless mode: %s", HEADLESS)

        self._pw = sync_playwright().start()

        try:
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                channel="chrome",
                headless=HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                locale="en-ZA",
                timezone_id=TIMEZONE,
                viewport={"width": 1366, "height": 900},
            )
        except Exception:
            if self._pw:
                self._pw.stop()
            self._pw = None
            raise

        logger.info("Persistent Chrome context ready.")
        return self._context

    def close(self):
        try:
            if self._context:
                self._context.close()
            if self._pw:
                self._pw.stop()
        except Exception as e:
            logger.warning("Browser close error: %s", e)
        finally:
            self._context = None
            self._pw = None

        logger.info("Browser closed.")


BROWSER = Browser()


# ------------------------------------------------------------
# SEARCH
# ------------------------------------------------------------

def search_google(keyword: str):
    context = BROWSER.start()
    page = context.new_page()
    page.set_default_timeout(30_000)

    url = (
        "https://www.google.com/search"
        f"?q={quote_plus(keyword)}"
        f"&hl={GOOGLE_HL}&gl={GOOGLE_GL}&num={GOOGLE_NUM}&pws=0"
    )

    logger.info("GET %s", url)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except PWTimeoutError as e:
        page.close()
        raise RuntimeError(f"Page load timeout: {e}")

    try:
        consent = page.locator(
            "button:has-text('Accept all'), "
            "button:has-text('I agree'), "
            "button:has-text('Accept')"
        ).first
        if consent.count() > 0 and consent.is_visible():
            consent.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except PWTimeoutError:
                pass
            logger.info("Consent accepted.")
    except Exception as e:
        logger.debug("Consent step skipped: %s", e)

    try:
        page.wait_for_selector(
            "h3",
            timeout=15_000,
        )
        # Google can populate result modules progressively after DOMContentLoaded.
        page.wait_for_timeout(2500)
    except PWTimeoutError:
        logger.warning("SERP H3 elements did not appear within the expected time.")

    try:
        body = page.inner_text("body").lower()
    except Exception:
        body = ""

    if "unusual traffic" in body or "our systems have detected" in body:
        page.close()
        raise GoogleBlocked("bot-detection page")

    if "recaptcha" in body or "i'm not a robot" in body or "not a robot" in body:
        page.close()
        raise GoogleBlocked(
            "CAPTCHA page - solve it manually in the opened Chrome window"
        )

    logger.info("SERP loaded.")
    return page


# ------------------------------------------------------------
# URL / DOMAIN HELPERS
# ------------------------------------------------------------

def resolve_google_redirect(page, href: str) -> str:
    if not href:
        return ""

    if href.startswith("/url?"):
        try:
            q_values = parse_qs(urlparse(href).query).get("q", [])
            if q_values:
                return q_values[0]
        except Exception:
            pass

    if href.startswith("/goto?"):
        full = "https://www.google.com" + href
        try:
            new_page = page.context.new_page()
            try:
                new_page.goto(full, wait_until="domcontentloaded", timeout=15_000)
                final = new_page.url
            finally:
                new_page.close()

            if final.startswith("http") and "google.com" not in urlparse(final).netloc:
                return final
        except Exception as e:
            logger.debug("Redirect resolve failed: %s", e)
        return ""

    if href.startswith(("http://", "https://")):
        return href

    return ""


def extract_domain(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""

    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        host = urlparse(url).netloc.lower().split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


# ------------------------------------------------------------
# WEBSITE NAME HELPERS
# ------------------------------------------------------------

KNOWN_WEBSITE_NAMES = {
    "betway.co.za": "Betway",
    "betway.com": "Betway",
    "hollywoodbets.net": "Hollywoodbets",
    "play.google.com": "Google Play",
    "google.com": "Google",
    "spribe.co": "SPRIBE",
    "spribe.com": "SPRIBE",
    "livescore.com": "LiveScore",
    "10bet.co.za": "10bet",
    "10bet.com": "10bet",
    "truworths.co.za": "Truworths",
}


def website_name_from_domain(domain: str) -> str:
    d = (domain or "").lower().strip()

    if d in KNOWN_WEBSITE_NAMES:
        return KNOWN_WEBSITE_NAMES[d]

    for known_domain, known_name in KNOWN_WEBSITE_NAMES.items():
        if d.endswith("." + known_domain):
            return known_name

    parts = d.split(".")
    if not parts or not parts[0]:
        return d

    name = parts[0].replace("-", " ").replace("_", " ").strip()
    return name[:1].upper() + name[1:]


def canonicalize_result_url(url: str) -> str:
    """Canonical URL identity for a SERP result, excluding query tracking noise."""
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ""

        host = parsed.netloc.lower().split(":")[0]
        if host.startswith("www."):
            host = host[4:]

        path = parsed.path.rstrip("/") or "/"
        return f"{host}{path}"
    except Exception:
        return ""


def stable_result_key(result: dict) -> str:
    """Stable identity based primarily on canonical destination URL, not Name/title."""
    url_key = canonicalize_result_url(result.get("url") or "")
    if url_key:
        return url_key

    title = " ".join((result.get("title") or "").split()).lower()
    return f"title:{title}"


# ------------------------------------------------------------
# ORGANIC EXTRACTION
# ------------------------------------------------------------

SPONSORED_HINTS = (
    "sponsored",
    "ad ·",
    "ads ·",
    "advertisement",
)

HARD_EXCLUSION_SELECTORS = (
    "#tads",
    "#tadsb",
    "#bottomads",
    "div[data-text-ad]",
    "[data-pla]",
    ".commercial-unit-desktop-top",
    ".commercial-unit-desktop-rhs",
    ".commercial-unit-mobile-top",
)


def find_result_block(h3):
    """
    Find the smallest useful ancestor that contains both this H3 and a link.

    The parser deliberately does not depend on Google's MjjYud class so that
    normal Google markup changes do not immediately break extraction.
    """
    selectors = (
        "xpath=ancestor::div[.//a[@href]][1]",
        "xpath=ancestor::div[.//h3 and .//a[@href]][1]",
        "xpath=ancestor::li[.//h3 and .//a[@href]][1]",
        "xpath=ancestor::*[.//h3 and .//a[@href]][1]",
    )

    for selector in selectors:
        try:
            block = h3.locator(selector)
            if block.count() > 0:
                return block.first
        except Exception:
            continue

    return h3


def block_is_non_organic(block) -> bool:
    """Reject obvious ads and Google-owned modules without brittle CSS rules."""
    try:
        text = block.inner_text().lower()
    except Exception:
        text = ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_lines = "\n".join(lines[:8])[:1600]

    if "ai overview" in first_lines:
        return True

    if any(hint in first_lines for hint in SPONSORED_HINTS):
        return True

    for selector in HARD_EXCLUSION_SELECTORS:
        try:
            if block.locator(selector).count() > 0:
                return True
        except Exception:
            continue

    return False


def get_result_href(page, h3, block) -> str:
    """Return the most likely external destination URL for a SERP candidate."""

    try:
        link = h3.locator("xpath=ancestor::a[1]")
        if link.count() > 0:
            href = link.first.get_attribute("href") or ""
            resolved = resolve_google_redirect(page, href)
            if resolved and extract_domain(resolved) and not extract_domain(resolved).startswith("google."):
                return resolved
    except Exception:
        pass

    try:
        links = block.locator("a[href]")
        candidates = []

        for i in range(links.count()):
            href = links.nth(i).get_attribute("href") or ""
            if href.startswith(("http://", "https://", "/url?", "/goto?")):
                candidates.append(href)

        # Prefer the first resolvable external link.
        for href in candidates:
            resolved = resolve_google_redirect(page, href)
            if not resolved:
                continue

            domain = extract_domain(resolved)
            if not domain:
                continue
            if domain.startswith("google.") or domain.startswith("accounts."):
                continue
            if domain == "webcache.googleusercontent.com":
                continue

            return resolved

    except Exception:
        pass

    return ""


def extract_organic_results(page) -> list:
    """Extract the first 10 distinct organic results in Google display order."""
    # Do not depend on #search, #rso or #center_col.
    # Google can change container IDs while leaving result headings as H3s.
    h3s = page.locator("h3")

    logger.info("SERP candidates found (H3): %d", h3s.count())

    results = []
    seen_keys = set()

    for i in range(h3s.count()):
        h3 = h3s.nth(i)

        try:
            title = " ".join(h3.inner_text().split()).strip()
            if not title:
                continue

            block = find_result_block(h3)

            if block_is_non_organic(block):
                logger.debug("Candidate %d rejected as non-organic: %s", i + 1, title)
                continue

            href = get_result_href(page, h3, block)
            domain = extract_domain(href)

            if not domain:
                logger.debug("Candidate %d rejected: no external URL: %s", i + 1, title)
                continue

            if domain.startswith("google.") or domain.startswith("accounts."):
                continue

            if domain == "webcache.googleusercontent.com":
                continue

            key = stable_result_key({"url": href, "title": title})

            if key in seen_keys:
                logger.debug("Candidate %d rejected as duplicate: %s", i + 1, href)
                continue

            seen_keys.add(key)

            result = {
                "keyword": KEYWORD,
                "name": website_name_from_domain(domain),
                "title": title,
                "url": href,
                "domain": domain,
                "rank": len(results) + 1,
                "key": key,
            }

            results.append(result)

            logger.info(
                "Rank %d | %s | %s",
                result["rank"],
                result["domain"],
                result["title"],
            )

            if len(results) == NUMBER_OF_ORGANIC_RESULTS:
                break

        except Exception as e:
            logger.debug("Candidate %d skipped: %s", i + 1, e)

    logger.info(
        "SERP extraction complete: %d/%d organic results",
        len(results),
        NUMBER_OF_ORGANIC_RESULTS,
    )

    return results


# ------------------------------------------------------------
# EXCEL HELPERS
# ------------------------------------------------------------

HEADER_FILL = PatternFill("solid", fgColor="5C2D91")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN_PURPLE = Side(style="thin", color="5C2D91")

GREEN_FILL = PatternFill("solid", fgColor="C6EFCE")
GREEN_FONT = Font(color="006100")
RED_FILL = PatternFill("solid", fgColor="FFC7CE")
RED_FONT = Font(color="9C0006")
YELLOW_FILL = PatternFill("solid", fgColor="FFEB9C")
YELLOW_FONT = Font(color="9C6500")


def style_header(ws):
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.row_dimensions[1].height = 22


def prepare_report_sheet(ws):
    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False

    widths = {"A": 14, "B": 24, "C": 14, "AB": 14}
    for col in range(4, 28):  # D:AA
        widths[get_column_letter(col)] = 9
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    for row in ws.iter_rows(min_row=2):
        row[0].alignment = Alignment(vertical="center")
        row[1].alignment = Alignment(vertical="center")
        row[2].alignment = Alignment(vertical="center")
        for cell in row[3:]:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    # Date format.
    for row in range(2, ws.max_row + 1):
        ws.cell(row=row, column=3).number_format = "yyyy-mm-dd"



def apply_current_rank_formulas(ws):
    # D:AA are the 24 hourly columns; AB is Current Rank.
    # Nested IF avoids dynamic-array functions and is widely compatible.
    for row in range(2, ws.max_row + 1):
        checks = []
        for col in range(27, 3, -1):  # AA down to D
            cell = ws.cell(row=row, column=col).coordinate
            checks.append(f'IF({cell}<>"",{cell},')
        formula = "=" + "".join(checks) + '""' + ")" * 24
        ws.cell(row=row, column=28).value = formula
        ws.cell(row=row, column=28).alignment = Alignment(horizontal="center")


def ensure_excel_table(ws):
    # Remove existing tables on the report sheet so malformed old ranges do not survive.
    ws.tables.clear()

    if ws.max_row < 2:
        return

    ref = f"A1:AB{ws.max_row}"
    table = Table(displayName="SERP_Rankings_Table", ref=ref)
    style = TableStyleInfo(
        name="TableStyleMedium4",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    table.tableStyleInfo = style
    ws.add_table(table)


def apply_conditional_formatting(ws):
    # Remove any previous conditional formatting and rebuild cleanly.
    ws.conditional_formatting._cf_rules.clear()

    # Hourly cells D:AA:
    # Improved = current hourly rank is lower than immediately previous hour.
    # Dropped = current hourly rank is higher than immediately previous hour.
    # New Entry = previous hour blank, current hour populated.
    for col in range(4, 28):
        current = ws.cell(row=2, column=col).column_letter
        if col == 4:
            continue
        previous = ws.cell(row=2, column=col - 1).column_letter

        ws.conditional_formatting.add(
            f"{current}2:{current}{max(ws.max_row, 2)}",
            FormulaRule(
                formula=[f'AND({current}2<>"",{previous}2<>"",{current}2<{previous}2)'],
                fill=GREEN_FILL,
                font=GREEN_FONT,
            ),
        )
        ws.conditional_formatting.add(
            f"{current}2:{current}{max(ws.max_row, 2)}",
            FormulaRule(
                formula=[f'AND({current}2<>"",{previous}2<>"",{current}2>{previous}2)'],
                fill=RED_FILL,
                font=RED_FONT,
            ),
        )
        ws.conditional_formatting.add(
            f"{current}2:{current}{max(ws.max_row, 2)}",
            FormulaRule(
                formula=[f'AND({current}2<>"",{previous}2="")'],
                fill=YELLOW_FILL,
                font=YELLOW_FONT,
            ),
        )

    # First hour: any populated rank is a baseline/new entry indicator.
    ws.conditional_formatting.add(
        f"D2:D{max(ws.max_row, 2)}",
        FormulaRule(
            formula=['D2<>""'],
            fill=YELLOW_FILL,
            font=YELLOW_FONT,
        ),
    )


def style_report_and_rebuild_table(ws):
    style_header(ws)
    prepare_report_sheet(ws)
    apply_current_rank_formulas(ws)
    ensure_excel_table(ws)
    apply_conditional_formatting(ws)
    ws.auto_filter.ref = f"A1:AB{max(ws.max_row, 2)}"


# ------------------------------------------------------------
# HIDDEN STATE SHEET
# ------------------------------------------------------------
# Visible report sheet stays exactly 28 columns.
# _State keeps the stable identity (URL + title), assigned row and
# latest rank, so duplicate names never interfere with each other.

STATE_HEADERS = ["Date", "Keyword", "Row", "Result Key", "Name", "Last Rank"]


def get_state_sheet(wb):
    if "_State" in wb.sheetnames:
        ws = wb["_State"]
    else:
        ws = wb.create_sheet("_State")
        ws.append(STATE_HEADERS)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.sheet_state = "hidden"

    ws.sheet_state = "hidden"
    return ws


def state_map_for_day(ws, date_str, keyword):
    """Return result_key -> state row data for the current day."""
    state = {}

    for r in range(2, ws.max_row + 1):
        saved_date = ws.cell(r, 1).value
        saved_keyword = ws.cell(r, 2).value
        result_key = ws.cell(r, 4).value
        row_num = ws.cell(r, 3).value
        last_rank = ws.cell(r, 6).value
        name = ws.cell(r, 5).value

        if str(saved_date)[:10] != date_str:
            continue
        if saved_keyword != keyword:
            continue
        if not result_key:
            continue

        state[result_key] = {
            "state_row": r,
            "row": int(row_num),
            "name": name,
            "last_rank": normalize_rank(last_rank),
        }

    return state


def normalize_rank(value):
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def update_state_entry(ws, date_str, keyword, row_num, result, state=None):
    """Create or update the hidden identity record for a visible report row."""
    key = result["key"]
    name = result["name"]
    rank = result["rank"]

    if state and key in state:
        r = state[key]["state_row"]
        ws.cell(r, 1).value = date_str
        ws.cell(r, 2).value = keyword
        ws.cell(r, 3).value = row_num
        ws.cell(r, 4).value = key
        ws.cell(r, 5).value = name
        ws.cell(r, 6).value = rank
        return r

    # If this visible row already has an identity for this day, replace it
    # rather than appending a duplicate state entry.
    for r in range(2, ws.max_row + 1):
        if (str(ws.cell(r, 1).value)[:10] == date_str
                and ws.cell(r, 2).value == keyword
                and normalize_rank(ws.cell(r, 3).value) == row_num):
            ws.cell(r, 4).value = key
            ws.cell(r, 5).value = name
            ws.cell(r, 6).value = rank
            return r

    ws.append([date_str, keyword, row_num, key, name, rank])
    return ws.max_row


def cleanup_day_state(ws, date_str, keyword, active_keys):
    """Keep only state entries that are still active or historically useful.

    We do not delete old state rows aggressively. This preserves identity for
    the day's historical workbook. Rows not in active_keys can still be used to
    recover identity if the same result re-enters later in the day.
    """
    return


# ------------------------------------------------------------
# DAILY ROW MANAGEMENT
# ------------------------------------------------------------

def get_or_create_day_rows(ws, state_ws, date_str, keyword):
    """Return exactly 10 visible row numbers for keyword/date.

    Rows are created explicitly instead of using ws.append(), which avoids
    accidental blank rows caused by worksheet/table metadata.
    """
    day_rows = []

    for row in range(2, ws.max_row + 1):
        if ws.cell(row=row, column=1).value != keyword:
            continue

        cell_date = ws.cell(row=row, column=3).value
        if hasattr(cell_date, "strftime"):
            cell_date = cell_date.strftime("%Y-%m-%d")
        else:
            cell_date = str(cell_date)[:10]

        if cell_date == date_str:
            day_rows.append(row)

    # The daily report is always exactly 10 rows. Create missing rows directly.
    # If a malformed/blank row exists immediately after the header, reuse it.
    while len(day_rows) < NUMBER_OF_ORGANIC_RESULTS:
        candidate = 2
        while candidate in day_rows:
            candidate += 1

        # Reuse the first truly blank row before extending the sheet.
        found_blank = None
        for row in range(2, ws.max_row + 1):
            if row in day_rows:
                continue
            if all(ws.cell(row=row, column=col).value is None for col in range(1, 29)):
                found_blank = row
                break

        new_row = found_blank if found_blank is not None else max(ws.max_row + 1, candidate)

        ws.cell(row=new_row, column=1).value = keyword
        ws.cell(row=new_row, column=2).value = ""
        ws.cell(row=new_row, column=3).value = datetime.strptime(date_str, "%Y-%m-%d").date()
        for col in range(4, 28):
            ws.cell(row=new_row, column=col).value = None
        ws.cell(row=new_row, column=28).value = None

        day_rows.append(new_row)

    return sorted(day_rows[:NUMBER_OF_ORGANIC_RESULTS])


def clear_row_result(ws, row_num, keep_identity=False):
    if not keep_identity:
        ws.cell(row=row_num, column=2).value = ""
    # Keep keyword and date. Clear all hourly ranks and formula will be rebuilt.
    for col in range(4, 28):
        ws.cell(row=row_num, column=col).value = None
    ws.cell(row=row_num, column=28).value = None


def assign_results_to_rows(ws, state_ws, results, run_ts):
    """Update the 10 day rows while matching results by stable key.

    Existing result keys keep the same row for the whole day. New entries use
    an unused row, with earlier hourly cells left blank.
    """
    date_str = run_ts.strftime("%Y-%m-%d")
    keyword = KEYWORD
    hour = hour_column_name(run_ts)
    hour_col = EXCEL_HEADERS.index(hour) + 1

    day_rows = get_or_create_day_rows(ws, state_ws, date_str, keyword)
    state = state_map_for_day(state_ws, date_str, keyword)

    # Active assignments for the current day.
    row_to_key = {}
    key_to_row = {}
    for key, item in state.items():
        row = item["row"]
        if row in day_rows and ws.cell(row=row, column=2).value:
            row_to_key[row] = key
            key_to_row[key] = row

    used_rows = set()
    newly_seen = []

    # First pass: retain rows for results already seen today.
    for result in results:
        key = result["key"]
        if key in key_to_row:
            row = key_to_row[key]
            used_rows.add(row)
            ws.cell(row=row, column=2).value = result["name"]
            ws.cell(row=row, column=hour_col).value = result["rank"]
            update_state_entry(state_ws, date_str, keyword, row, result, state)

    # Rows that are still unused can take new entrants. We prefer truly blank rows.
    available_rows = [
        r for r in day_rows
        if r not in used_rows and not ws.cell(r, column=2).value
    ]

    # If no blank rows are available, re-use rows whose tracked result is not in
    # this capture. The prior hourly history is cleared because the identity has
    # changed; the new result then starts from this hour.
    replaceable_rows = [r for r in day_rows if r not in used_rows]
    replacement_index = 0

    for result in results:
        key = result["key"]
        if key in key_to_row:
            continue

        if available_rows:
            row = available_rows.pop(0)
        elif replacement_index < len(replaceable_rows):
            row = replaceable_rows[replacement_index]
            replacement_index += 1
            # Remove stale state entries assigned to this row.
            for state_key, item in list(state.items()):
                if item["row"] == row:
                    state_key_row = item["state_row"]
                    # Leave historical state row intact if desired, but remove
                    # mapping from current in-memory state so new key owns the row.
                    del state[state_key]
            clear_row_result(ws, row, keep_identity=False)
        else:
            logger.warning("Could not allocate a row for result: %s", key)
            continue

        used_rows.add(row)
        key_to_row[key] = row
        ws.cell(row=row, column=1).value = keyword
        ws.cell(row=row, column=2).value = result["name"]
        ws.cell(row=row, column=3).value = run_ts.date()
        ws.cell(row=row, column=hour_col).value = result["rank"]
        update_state_entry(state_ws, date_str, keyword, row, result, state)
        newly_seen.append(result)

    # Ensure all 10 rows remain labelled with keyword/date, while unused rows stay blank.
    for row in day_rows:
        ws.cell(row=row, column=1).value = keyword
        ws.cell(row=row, column=3).value = run_ts.date()

    # Recalculate formulas for this worksheet.
    apply_current_rank_formulas(ws)

    logger.info("Updated %d SERP rows for %s at %s", len(results), date_str, hour)
    return day_rows


# ------------------------------------------------------------
# EXCEL LOAD / SAVE
# ------------------------------------------------------------

def open_or_create_workbook():
    if os.path.isfile(EXCEL_FILE) and os.path.getsize(EXCEL_FILE) > 0:
        try:
            wb = load_workbook(EXCEL_FILE)
            if "SERP Rankings" not in wb.sheetnames:
                ws = wb.create_sheet("SERP Rankings", 0)
                ws.append(EXCEL_HEADERS)
            else:
                ws = wb["SERP Rankings"]

            # Detect legacy layouts and rebuild the visible sheet cleanly.
            headers = [ws.cell(row=1, column=i).value for i in range(1, min(ws.max_column, 28) + 1)]
            if headers[:3] != EXCEL_HEADERS[:3] or len(headers) != len(EXCEL_HEADERS):
                logger.info("Legacy/invalid workbook structure detected; rebuilding visible report sheet.")
                old_values = []
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if row and row[0] is not None:
                        old_values.append(row)

                wb.remove(ws)
                ws = wb.create_sheet("SERP Rankings", 0)
                ws.append(EXCEL_HEADERS)

                # Do not blindly migrate old rows because their structure was
                # incompatible. Historical workbook stays safe; new structure
                # starts cleanly if the previous format cannot be migrated.

            state_ws = get_state_sheet(wb)
            style_report_and_rebuild_table(ws)
            return wb, ws, state_ws

        except Exception as e:
            logger.error("Existing Excel could not be safely opened: %s", e)
            raise RuntimeError(
                f"Could not open {EXCEL_FILE}. If it is open in Excel, close it and try again."
            ) from e

    wb = Workbook()
    ws = wb.active
    ws.title = "SERP Rankings"
    ws.append(EXCEL_HEADERS)
    state_ws = get_state_sheet(wb)
    style_report_and_rebuild_table(ws)
    return wb, ws, state_ws


def atomic_save_workbook(wb):
    directory = os.path.dirname(os.path.abspath(EXCEL_FILE)) or "."
    temp_path = None

    try:
        for attempt in range(5):
            try:
                temp_path = os.path.join(
                    directory,
                    f".aviator_rankings_{os.getpid()}_{attempt}.xlsx",
                )
                wb.save(temp_path)
                os.replace(temp_path, EXCEL_FILE)
                logger.info("Excel workbook saved: %s", EXCEL_FILE)
                return
            except PermissionError as e:
                logger.warning(
                    "Excel file is locked; retrying save (%d/5)...",
                    attempt + 1,
                )
                time.sleep(1.5 * (attempt + 1))
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                temp_path = None

        raise PermissionError(
            f"Cannot replace {EXCEL_FILE}. Close the workbook in Microsoft Excel "
            "and run the monitor again."
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


# ------------------------------------------------------------
# REPORT
# ------------------------------------------------------------

def print_report(run_ts, results):
    print("=" * 60)
    print("HOLLYWOODBETS SEO SERP CHECK")
    print("=" * 60)
    print(f"Keyword: {KEYWORD}")
    print(f"Date: {run_ts.strftime('%Y-%m-%d')}")
    print(f"Capture hour: {hour_column_name(run_ts)}")
    print(f"Organic results collected: {len(results)}")
    print("-" * 60)

    for result in results:
        print(f"{result['rank']}. {result['name']} | {result['domain']}")

    target_rank = next(
        (result["rank"] for result in results if is_target_website(result["domain"])),
        None,
    )

    print("-" * 60)
    print(f"Hollywoodbets rank: {target_rank}")
    print(f"Results saved: {EXCEL_FILE}")
    print("=" * 60)


def is_target_website(domain: str) -> bool:
    d = extract_domain(domain)
    return d == TARGET_DOMAIN or d.endswith("." + TARGET_DOMAIN)


# ------------------------------------------------------------
# RUN ONCE
# ------------------------------------------------------------

def run_once():
    run_ts = now_local()
    logger.info("=" * 60)
    logger.info("Run start: %s | keyword=%s", run_ts.isoformat(), KEYWORD)

    page = None
    wb = None

    try:
        page = search_google(KEYWORD)
        results = extract_organic_results(page)

        if len(results) < MINIMUM_ORGANIC_RESULTS:
            logger.error(
                "INCOMPLETE SERP: extracted %d/%d results. Nothing will be written to Excel.",
                len(results),
                NUMBER_OF_ORGANIC_RESULTS,
            )

            # Keep the exact returned HTML for diagnosis when Google markup
            # changes or the page is partially rendered.
            try:
                debug_path = os.path.join(
                    BASE_DIR,
                    f"failed_serp_{run_ts.strftime('%Y%m%d_%H%M%S')}.html",
                )
                with open(debug_path, "w", encoding="utf-8") as debug_file:
                    debug_file.write(page.content())
                logger.error("Failed SERP HTML saved: %s", debug_path)
            except Exception as debug_error:
                logger.warning("Could not save failed SERP HTML: %s", debug_error)

            raise RuntimeError(
                f"Insufficient SERP extraction: {len(results)} results; minimum={MINIMUM_ORGANIC_RESULTS}"
            )

        wb, ws, state_ws = open_or_create_workbook()
        assign_results_to_rows(ws, state_ws, results, run_ts)
        style_report_and_rebuild_table(ws)
        atomic_save_workbook(wb)

        print_report(run_ts, results)

        return {
            "keyword": KEYWORD,
            "date": run_ts.strftime("%Y-%m-%d"),
            "hour": hour_column_name(run_ts),
            "results_collected": len(results),
            "hollywoodbets_ranks": [
                r["rank"] for r in results if is_target_website(r["domain"])
            ],
            "error": None,
        }

    except GoogleBlocked as e:
        logger.warning("Google blocked this run: %s", e)
        print(f"Google blocked this run: {e}")
        return {"keyword": KEYWORD, "error": f"BLOCKED: {e}"}

    except Exception as e:
        logger.error("Run failed: %s", e)
        logger.error(traceback.format_exc())
        print(f"Run failed: {e}")
        return {"keyword": KEYWORD, "error": str(e)}

    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass

        if page is not None:
            try:
                page.close()
            except Exception:
                pass

        BROWSER.close()


# ------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------

_shutdown = False


def handle_sigint(signum, frame):
    global _shutdown
    print("\nCtrl+C detected - finishing current run then shutting down.")
    _shutdown = True


def run_hourly():
    signal.signal(signal.SIGINT, handle_sigint)
    logger.info("Hourly runner started. Press Ctrl+C to stop.")

    try:
        while not _shutdown:
            try:
                run_once()
            except Exception as e:
                logger.error("Unhandled error in hourly loop: %s", e)

            now = now_local()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            seconds = max(0.0, (next_hour - now).total_seconds())

            logger.info(
                "Sleeping until %s (%.0f seconds).",
                next_hour.strftime("%Y-%m-%d %H:%M:%S"),
                seconds,
            )

            while seconds > 0 and not _shutdown:
                time.sleep(min(30, seconds))
                seconds = (next_hour - now_local()).total_seconds()

    finally:
        BROWSER.close()
        logger.info("Hourly runner stopped.")


# ------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------

if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "once"

    if mode == "hourly":
        run_hourly()
    else:
        result = run_once()
        if isinstance(result, dict) and result.get("error"):
            raise SystemExit(1)



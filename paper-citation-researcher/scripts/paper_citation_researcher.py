#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_stdio()


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CITED_BY_RE = re.compile(
    r"(?:Cited by|\u88ab\u5f15\u7528\u6b21\u6570|\u5f15\u7528\u6b21\u6570)\s*[\uff1a:]?\s*(\d+)",
    re.IGNORECASE,
)

POSITIVE_RE = re.compile(
    r"\b(excellent|outstanding|groundbreaking|pioneering|seminal|important|"
    r"significant|key|critical|essential|impressive|remarkable|innovative|"
    r"influential|demonstrated|showed|proved|validated|successfully|"
    r"effectively|efficiently|benefit|advantage|improve|enhance|advance|"
    r"build on|based on|inspired by|as shown by|as demonstrated by|supports|"
    r"confirms)\b",
    re.IGNORECASE,
)

CITING_COLUMNS = [
    "dedupe_key",
    "source_platforms",
    "source_record_ids",
    "citing_title",
    "citing_authors",
    "publication_year",
    "venue",
    "doi",
    "url",
    "pdf_url",
    "open_access_pdf_url",
    "citation_count",
    "semantic_scholar_paper_id",
    "google_scholar_cited_by_url",
    "arxiv_id",
    "acl_id",
    "abstract",
]

S2_FIELDS = "title,externalIds,year,venue,authors,paperId,url,citationCount,openAccessPdf"
S2_MAX_RETRY_DELAY = 60
EXCEL_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")
REF_LABEL_RE = re.compile(r"^\s*(?:\[\s*(\d{1,4})\s*\]|(\d{1,4})[\.\)]\s+)")
BRACKET_CITE_RE = re.compile(r"\[\s*([0-9,\-;\s\u2010-\u2015]+)\s*\]")

GOOGLE_PREFERRED_COLUMNS = {
    "citing_title",
    "citing_authors",
    "publication_year",
    "venue",
    "url",
    "pdf_url",
    "citation_count",
    "google_scholar_cited_by_url",
}

SEMANTIC_SUPPLEMENT_COLUMNS = {
    "doi",
    "open_access_pdf_url",
    "semantic_scholar_paper_id",
    "arxiv_id",
    "acl_id",
    "abstract",
}

CONTEXT_COLUMNS = [
    "citing_title",
    "source_platforms",
    "doi",
    "pdf_path",
    "page",
    "line_start",
    "line_end",
    "citation_marker",
    "match_type",
    "confidence",
    "context",
    "is_positive",
    "reference_marker",
    "reference_score",
    "reference_evidence",
    "reference_entry",
]

COVERAGE_COLUMNS = [
    "citing_title",
    "source_platforms",
    "doi",
    "download_status",
    "analysis_status",
    "pdf_path",
    "location_count",
    "pages",
    "reference_marker",
    "reference_score",
    "reference_evidence",
    "failure_reason",
    "reference_entry",
]


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
    return session


def ensure_dir(path: str | Path) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def safe_filename(text: str, limit: int = 80) -> str:
    text = re.sub(r"[\\/*?:\"<>|]", "_", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(". ")
    if not text:
        text = "paper"
    return text[:limit].rstrip(". ")


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_overlap(wanted: str, candidate: str) -> float:
    wanted_tokens = set(normalize_text(wanted).split())
    candidate_tokens = set(normalize_text(candidate).split())
    if not wanted_tokens:
        return 0.0
    return len(wanted_tokens & candidate_tokens) / len(wanted_tokens)


def is_doi(identifier: str) -> bool:
    raw = identifier.strip()
    if raw.upper().startswith("DOI:"):
        raw = raw[4:]
    return raw.startswith("10.") and "/" in raw


def clean_doi(identifier: str) -> str:
    raw = identifier.strip()
    if raw.upper().startswith("DOI:"):
        raw = raw[4:]
    return raw


def s2_headers(api_key: str = "") -> Dict[str, str]:
    return {"x-api-key": api_key} if api_key else {}


def s2_retry_after_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "").strip()
    if retry_after:
        try:
            return min(float(retry_after), S2_MAX_RETRY_DELAY)
        except ValueError:
            pass
    return min((2 ** attempt) * 3 + random.uniform(0.0, 1.5), S2_MAX_RETRY_DELAY)


def s2_error_message(response: requests.Response, context: str) -> str:
    body = re.sub(r"\s+", " ", response.text or "").strip()
    if len(body) > 500:
        body = body[:500] + "..."
    detail = f"{response.status_code} {response.reason}".strip()
    message = f"Semantic Scholar {context} failed: {detail} for {response.url}"
    if body:
        message += f"; body: {body}"
    return message


def s2_raise_for_status(response: requests.Response, context: str) -> None:
    if not response.ok:
        raise RuntimeError(s2_error_message(response, context))


def s2_get(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    api_key: str = "",
    timeout: int = 30,
    max_retries: int = 4,
) -> requests.Response:
    headers = s2_headers(api_key)
    response: Optional[requests.Response] = None
    for attempt in range(max_retries):
        response = session.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code == 429:
            if attempt >= max_retries - 1:
                return response
            delay = s2_retry_after_seconds(response, attempt)
            print(f"Semantic Scholar rate limited; retrying in {delay:.1f}s")
            time.sleep(delay)
            continue
        if response.status_code >= 500:
            if attempt >= max_retries - 1:
                return response
            time.sleep(s2_retry_after_seconds(response, attempt))
            continue
        return response
    assert response is not None
    return response


def s2_search_query(identifier: str) -> str:
    normalized = normalize_text(identifier)
    return normalized or identifier.strip()


def s2_candidate_score(identifier: str, paper: Dict[str, Any]) -> float:
    title = paper.get("title") or ""
    if not title:
        return 0.0
    wanted = normalize_text(identifier)
    candidate = normalize_text(title)
    if wanted and wanted == candidate:
        return 1.0
    return max(
        token_overlap(identifier, title),
        SequenceMatcher(None, wanted, candidate).ratio(),
    )


def s2_dedupe_candidates(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for paper in candidates:
        key = paper.get("paperId") or f"{normalize_text(paper.get('title', ''))}:{paper.get('year') or ''}"
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(paper)
    return unique


def s2_match_candidates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [paper for paper in data if isinstance(paper, dict)]
    if isinstance(data, dict):
        return [data]
    if payload.get("paperId"):
        return [payload]
    return []


def s2_resolve_paper(session: requests.Session, identifier: str, api_key: str = "") -> Dict[str, Any]:
    if is_doi(identifier):
        doi_key = urllib.parse.quote(f"DOI:{clean_doi(identifier)}", safe="")
        url = f"https://api.semanticscholar.org/graph/v1/paper/{doi_key}"
        response = s2_get(session, url, {"fields": S2_FIELDS}, api_key)
        if response.ok:
            return response.json()
        s2_raise_for_status(response, "DOI resolve")

    candidates: List[Dict[str, Any]] = []
    response = s2_get(
        session,
        "https://api.semanticscholar.org/graph/v1/paper/search/match",
        {"query": identifier, "fields": S2_FIELDS},
        api_key,
    )
    if response.ok:
        matches = s2_match_candidates(response.json())
        for matched in matches:
            if s2_candidate_score(identifier, matched) >= 0.98:
                return matched
        candidates.extend(matches)
    elif response.status_code != 404:
        s2_raise_for_status(response, "title match")

    for query in dict.fromkeys([s2_search_query(identifier), identifier.strip()]):
        if not query:
            continue
        response = s2_get(
            session,
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"query": query, "limit": 10, "fields": S2_FIELDS},
            api_key,
        )
        s2_raise_for_status(response, "title search")
        search_candidates = response.json().get("data", [])
        candidates.extend(search_candidates)
        if search_candidates:
            break

    candidates = s2_dedupe_candidates(candidates)
    if not candidates:
        raise RuntimeError(f"Semantic Scholar could not resolve target paper: {identifier}")
    best = max(candidates, key=lambda paper: s2_candidate_score(identifier, paper))
    best_score = s2_candidate_score(identifier, best)
    if best_score < 0.45:
        titles = "; ".join(paper.get("title", "") for paper in candidates[:5] if paper.get("title"))
        raise RuntimeError(f"Semantic Scholar could not confidently resolve target paper: {identifier}; candidates: {titles}")
    return best


def s2_fetch_citations(
    session: requests.Session,
    target: Dict[str, Any],
    limit: int,
    api_key: str = "",
) -> List[Dict[str, Any]]:
    paper_id = target.get("paperId")
    if not paper_id:
        return []
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    fields = (
        "citingPaper.paperId,citingPaper.title,citingPaper.authors,citingPaper.year,"
        "citingPaper.venue,citingPaper.externalIds,citingPaper.url,citingPaper.openAccessPdf,"
        "citingPaper.citationCount,citingPaper.abstract"
    )
    while len(rows) < limit:
        page_size = min(1000, limit - len(rows))
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
        response = s2_get(
            session,
            url,
            {"limit": page_size, "offset": offset, "fields": fields},
            api_key,
            timeout=45,
        )
        s2_raise_for_status(response, "citation fetch")
        payload = response.json()
        data = payload.get("data", [])
        if not data:
            break
        added = 0
        for item in data:
            paper = item.get("citingPaper") or {}
            paper_id_value = paper.get("paperId") or ""
            if paper_id_value and paper_id_value in seen:
                continue
            if paper_id_value:
                seen.add(paper_id_value)
            external = paper.get("externalIds") or {}
            authors = ", ".join(a.get("name", "") for a in paper.get("authors", []) if a.get("name"))
            rows.append(
                {
                    "source_platforms": "semantic-scholar",
                    "source_record_ids": f"s2:{paper_id_value}" if paper_id_value else "",
                    "citing_title": paper.get("title") or "",
                    "citing_authors": authors,
                    "publication_year": paper.get("year") or "",
                    "venue": paper.get("venue") or "",
                    "doi": external.get("DOI") or "",
                    "url": paper.get("url") or "",
                    "pdf_url": "",
                    "open_access_pdf_url": (paper.get("openAccessPdf") or {}).get("url") or "",
                    "citation_count": citation_count_or_zero(paper.get("citationCount")),
                    "semantic_scholar_paper_id": paper_id_value,
                    "google_scholar_cited_by_url": "",
                    "arxiv_id": external.get("ArXiv") or "",
                    "acl_id": external.get("ACL") or "",
                    "abstract": paper.get("abstract") or "",
                }
            )
            added += 1
            if len(rows) >= limit:
                break
        next_offset = payload.get("next")
        offset = next_offset if isinstance(next_offset, int) else offset + len(data)
        if added == 0 or len(data) < page_size:
            break
        time.sleep(0.2)
    return rows


def create_webdriver(browser: str):
    from selenium import webdriver

    if browser == "edge":
        options = webdriver.EdgeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        return webdriver.Edge(options=options)
    if browser == "firefox":
        options = webdriver.FirefoxOptions()
        return webdriver.Firefox(options=options)
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    return webdriver.Chrome(options=options)


def scholar_url(query: str, locale: str = "zh-CN") -> str:
    return "https://scholar.google.com/scholar?" + urllib.parse.urlencode(
        {"q": query, "hl": locale, "as_vis": "1"}
    )


def google_target_queries(identifier: str) -> List[str]:
    raw = identifier.strip()
    queries = [f'"{raw}"', raw]
    if is_doi(raw):
        queries.insert(0, clean_doi(raw))
    if ":" in raw:
        head, tail = [part.strip() for part in raw.split(":", 1)]
        if head:
            queries.append(f'"{head}"')
        if head and tail:
            queries.append(f'"{head}" "{" ".join(tail.split()[:8])}"')
    out = []
    seen = set()
    for query in queries:
        key = query.lower()
        if query and key not in seen:
            out.append(query)
            seen.add(key)
    return out


def is_scholar_captcha_page(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        marker in lowered
        for marker in (
            "captcha",
            "not a robot",
            "unusual traffic",
            "sorry/index",
        )
    )


def wait_for_scholar_captcha(driver, url: str) -> None:
    while True:
        if not is_scholar_captcha_page(driver.page_source):
            return
        print("Google Scholar captcha detected. Complete it in the browser, then press Enter.")
        try:
            input()
        except EOFError:
            print("No interactive input available; waiting 30 seconds before checking captcha again.")
            time.sleep(30)
        driver.get(url)
        time.sleep(3)


def normalize_scholar_results_url(
    href: str,
    base_url: str = "https://scholar.google.com",
    required_cites: Optional[str] = None,
    require_cites: bool = False,
    require_start: bool = False,
) -> Optional[str]:
    if not href:
        return None
    url = urllib.parse.urljoin(base_url, href)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc != "scholar.google.com":
        return None
    if parsed.path != "/scholar":
        return None

    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    cites_values = params.get("cites") or []
    if require_cites and not cites_values:
        return None
    if required_cites is not None and (not cites_values or cites_values[0] != required_cites):
        return None
    if require_start:
        start_values = params.get("start") or []
        if not start_values:
            return None
        try:
            int(start_values[0])
        except (TypeError, ValueError):
            return None

    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def scholar_query_value(url: str, key: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    values = params.get(key) or []
    return values[0] if values else None


def scholar_start(url: str) -> int:
    value = scholar_query_value(url, "start")
    try:
        return int(value) if value is not None and value != "" else 0
    except ValueError:
        return 0


def scholar_results_url_with_start(url: str, start: int) -> str:
    normalized = normalize_scholar_results_url(url) or url
    parsed = urllib.parse.urlparse(normalized)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    params["start"] = [str(max(0, start))]
    query = urllib.parse.urlencode(params, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=query, fragment=""))


def parse_count(value: str) -> Optional[int]:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def citation_count_or_zero(value: Any) -> str:
    if value is None:
        return "0"
    count = parse_count(str(value))
    return str(count) if count is not None else "0"


def link_looks_like_next_page(link: Any) -> bool:
    text = link.get_text(" ", strip=True).lower()
    aria = (link.get("aria-label") or "").lower()
    title = (link.get("title") or "").lower()
    return (
        link.select_one(".gs_ico_nav_next") is not None
        or "next" in text
        or "next" in aria
        or "next" in title
        or "\u4e0b\u4e00\u9875" in text
        or "\u4e0b\u4e00\u9801" in text
        or "\u4e0b\u4e00\u9875" in aria
        or "\u4e0b\u4e00\u9801" in aria
    )


def find_next_scholar_page(soup: BeautifulSoup, current_url: str) -> Optional[str]:
    current_results_url = normalize_scholar_results_url(current_url)
    required_cites = scholar_query_value(current_results_url or current_url, "cites")
    current_start = scholar_start(current_results_url or current_url)

    candidates: List[Tuple[int, str]] = []
    nav_links = soup.select("#gs_n a")
    link_groups = [nav_links, soup.find_all("a")] if nav_links else [soup.find_all("a")]
    seen_hrefs = set()
    for links in link_groups:
        for link in links:
            href = link.get("href") or ""
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            in_pagination_nav = bool(nav_links) and link in nav_links
            if not in_pagination_nav and not link_looks_like_next_page(link):
                continue
            url = normalize_scholar_results_url(
                href,
                base_url=current_results_url or current_url,
                required_cites=required_cites,
                require_start=True,
            )
            if not url:
                continue
            start = scholar_start(url)
            if start > current_start:
                candidates.append((start, url))
        if candidates:
            break

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def find_cited_by_link(block: Any) -> Tuple[str, str]:
    for a in block.find_all("a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href", "")
        match = CITED_BY_RE.search(text)
        cited_by_url = normalize_scholar_results_url(href, require_cites=True)
        if cited_by_url and (match or scholar_query_value(cited_by_url, "cites")):
            return cited_by_url, match.group(1) if match else ""
    return "", "0"


def parse_google_result(block) -> Dict[str, Any]:
    title_tag = block.find("h3")
    link = title_tag.find("a") if title_tag else block.find("a")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    url = link.get("href", "") if link else ""
    meta = block.find("div", class_="gs_a")
    meta_text = meta.get_text(" ", strip=True) if meta else ""
    year_match = re.search(r"\b(19|20)\d{2}\b", meta_text)
    cited_by_url, citation_count = find_cited_by_link(block)
    pdf_url = ""
    for a in block.find_all("a"):
        if "[PDF" in a.get_text(" ", strip=True).upper():
            pdf_url = urllib.parse.urljoin("https://scholar.google.com", a.get("href", ""))
            break
    return {
        "source_platforms": "google-scholar",
        "source_record_ids": cited_by_url or url,
        "citing_title": title,
        "citing_authors": meta_text,
        "publication_year": year_match.group(0) if year_match else "",
        "venue": meta_text,
        "doi": "",
        "url": url,
        "pdf_url": pdf_url,
        "open_access_pdf_url": "",
        "citation_count": citation_count_or_zero(citation_count),
        "semantic_scholar_paper_id": "",
        "google_scholar_cited_by_url": cited_by_url,
        "arxiv_id": "",
        "acl_id": "",
        "abstract": "",
    }


def google_result_blocks(soup: BeautifulSoup) -> List[Any]:
    blocks = soup.find_all("div", class_="gs_ri")
    if blocks:
        return blocks
    return [
        block
        for block in soup.find_all("div", class_="gs_r")
        if block.find("h3") and not block.get_text(" ", strip=True).lower().startswith("search within citing articles")
    ]


def score_google_target(block, identifier: str, rank: int) -> float:
    parsed = parse_google_result(block)
    title = parsed.get("citing_title", "")
    if is_doi(identifier):
        text = block.get_text(" ", strip=True).lower()
        return 1.0 if clean_doi(identifier).lower() in text else max(0.0, 0.7 - rank * 0.02)
    return max(
        token_overlap(identifier, title),
        SequenceMatcher(None, normalize_text(identifier), normalize_text(title)).ratio(),
    )


def google_cited_by_url(
    driver,
    identifier: str,
    min_delay: float,
    max_delay: float,
    locale: str = "zh-CN",
) -> Tuple[Optional[str], bool, Optional[int]]:
    for query in google_target_queries(identifier):
        url = scholar_url(query, locale)
        driver.get(url)
        time.sleep(random.uniform(min_delay, max_delay))
        wait_for_scholar_captcha(driver, url)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        blocks = google_result_blocks(soup)
        scored = sorted(
            ((score_google_target(block, identifier, idx), idx, block) for idx, block in enumerate(blocks)),
            key=lambda item: (-item[0], item[1]),
        )
        for score, _, block in scored:
            if score < 0.55 and not is_doi(identifier):
                continue
            parsed = parse_google_result(block)
            title = parsed.get("citing_title")
            if parsed.get("google_scholar_cited_by_url"):
                print(f"Google Scholar target candidate score={score:.2f}: {title}")
                return parsed["google_scholar_cited_by_url"], True, parse_count(parsed.get("citation_count", ""))
            if score >= 0.75 or is_doi(identifier):
                print(f"Google Scholar target candidate has no Cited by link (score={score:.2f}): {title}")
                return None, True, None
    return None, False, None


def google_scrape_citing(
    identifier: str,
    limit: int,
    browser: str,
    min_delay: float,
    max_delay: float,
    locale: str = "zh-CN",
) -> List[Dict[str, Any]]:
    driver = create_webdriver(browser)
    try:
        current_url, target_found, reported_total = google_cited_by_url(
            driver,
            identifier,
            min_delay,
            max_delay,
            locale,
        )
        if not target_found:
            raise RuntimeError("Could not find a matching target paper on Google Scholar.")
        if not current_url:
            print("Google Scholar target found with no citing papers.")
            return []
        rows: List[Dict[str, Any]] = []
        seen_urls = set()
        empty_pages = 0
        target_total = min(limit, reported_total) if reported_total else limit
        while current_url and len(rows) < target_total:
            normalized_url = normalize_scholar_results_url(current_url) or current_url
            if normalized_url in seen_urls:
                print(f"Stopping Google Scholar pagination loop: {normalized_url}")
                break
            seen_urls.add(normalized_url)
            driver.get(current_url)
            time.sleep(random.uniform(min_delay, max_delay))
            wait_for_scholar_captcha(driver, current_url)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            blocks = google_result_blocks(soup)
            if not blocks:
                empty_pages += 1
                current_start = scholar_start(driver.current_url or current_url)
                print(f"No Google Scholar result blocks found at start={current_start}: {driver.current_url}")
                if reported_total and len(rows) < target_total and empty_pages < 3:
                    current_url = scholar_results_url_with_start(driver.current_url or current_url, current_start + 10)
                    continue
                break
            empty_pages = 0
            for block in blocks:
                rows.append(parse_google_result(block))
                if len(rows) >= target_total:
                    break
            current_start = scholar_start(driver.current_url or current_url)
            next_url = find_next_scholar_page(soup, driver.current_url or current_url)
            if next_url:
                current_url = next_url
            elif reported_total and len(rows) < target_total:
                next_start = current_start + 10
                print(
                    "Google Scholar did not expose a next link at "
                    f"start={current_start}; trying start={next_start} "
                    f"based on reported citation count {reported_total}."
                )
                current_url = scholar_results_url_with_start(driver.current_url or current_url, next_start)
            else:
                current_url = None
        if reported_total and len(rows) < target_total:
            print(
                f"Google Scholar reported {reported_total} citations but exposed "
                f"{len(rows)} result rows through pagination."
            )
        return rows
    finally:
        driver.quit()


def dedupe_key(row: Dict[str, Any]) -> str:
    return title_dedupe_key(row)


def title_dedupe_key(row: Dict[str, Any]) -> str:
    title = normalize_text(str(row.get("citing_title") or ""))
    year = str(row.get("publication_year") or "").strip()
    return f"title:{title[:120] if title else 'untitled'}:{year}"


def normalized_identity_url(url: Any) -> str:
    text = str(url or "").strip()
    if not text or text.lower() == "nan":
        return ""
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return ""
    query = urllib.parse.urlencode(
        sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)),
        doseq=True,
    )
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, "")
    )


def normalized_doi_value(value: Any) -> str:
    doi = str(value or "").strip().lower()
    if not doi or doi == "nan":
        return ""
    if doi.startswith("doi:"):
        doi = doi[4:].strip()
    return doi


def add_identity_key(keys: List[str], seen: set[str], key: str) -> None:
    if key and key not in seen:
        keys.append(key)
        seen.add(key)


def dedupe_keys(row: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    seen: set[str] = set()
    add_identity_key(keys, seen, title_dedupe_key(row))

    doi = normalized_doi_value(row.get("doi"))
    if doi:
        add_identity_key(keys, seen, f"doi:{doi}")

    semantic_id = str(row.get("semantic_scholar_paper_id") or "").strip()
    if semantic_id and semantic_id.lower() != "nan":
        add_identity_key(keys, seen, f"semantic:{semantic_id}")

    for col in ("url", "pdf_url", "open_access_pdf_url", "google_scholar_cited_by_url"):
        normalized_url = normalized_identity_url(row.get(col))
        if normalized_url:
            add_identity_key(keys, seen, f"url:{normalized_url}")

    for source_id in str(row.get("source_record_ids") or "").split(";"):
        source_id = source_id.strip()
        if not source_id:
            continue
        if source_id.startswith("s2:"):
            add_identity_key(keys, seen, f"semantic:{source_id[3:]}")
            continue
        normalized_url = normalized_identity_url(source_id)
        if normalized_url:
            add_identity_key(keys, seen, f"url:{normalized_url}")

    for candidate_url in candidate_pdf_urls(row):
        normalized_url = normalized_identity_url(candidate_url)
        if normalized_url:
            add_identity_key(keys, seen, f"url:{normalized_url}")

    return keys


def value_present(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() != "nan"


def source_platform_set(row: Dict[str, Any]) -> set[str]:
    return set(filter(None, str(row.get("source_platforms", "")).split(";")))


def row_has_platform(row: Dict[str, Any], platform: str) -> bool:
    return platform in source_platform_set(row)


def normalized_doi(row: Dict[str, Any]) -> str:
    return normalized_doi_value(row.get("doi"))


def records_compatible(existing: Dict[str, Any], row: Dict[str, Any]) -> bool:
    existing_doi = normalized_doi(existing)
    row_doi = normalized_doi(row)
    return not (existing_doi and row_doi and existing_doi != row_doi)


def merge_record_into(existing: Dict[str, Any], row: Dict[str, Any]) -> None:
    platforms = source_platform_set(existing)
    platforms.update(source_platform_set(row))
    existing["source_platforms"] = ";".join(sorted(platforms))

    ids = set(filter(None, str(existing.get("source_record_ids", "")).split(";")))
    ids.update(filter(None, str(row.get("source_record_ids", "")).split(";")))
    existing["source_record_ids"] = ";".join(sorted(ids))

    row_is_google = row_has_platform(row, "google-scholar")
    for col in CITING_COLUMNS:
        if col in {"dedupe_key", "source_platforms", "source_record_ids"}:
            continue
        row_value = row.get(col, "")
        existing_value = existing.get(col, "")
        if col in GOOGLE_PREFERRED_COLUMNS and row_is_google and value_present(row_value):
            existing[col] = row_value
        elif not value_present(existing_value) and value_present(row_value):
            existing[col] = row_value


def merge_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    key_aliases: Dict[str, str] = {}
    next_internal_id = 1
    for raw in records:
        row = {col: raw.get(col, "") for col in CITING_COLUMNS if col != "dedupe_key"}
        keys = dedupe_keys(row)
        matching_keys: List[str] = []
        for candidate in keys:
            mapped_key = key_aliases.get(candidate)
            if (
                mapped_key
                and mapped_key in merged
                and mapped_key not in matching_keys
                and records_compatible(merged[mapped_key], row)
            ):
                matching_keys.append(mapped_key)
        if not matching_keys:
            key = f"record:{next_internal_id}"
            next_internal_id += 1
            row["dedupe_key"] = title_dedupe_key(row)
            merged[key] = row
            for alias in keys:
                key_aliases.setdefault(alias, key)
            continue

        key = matching_keys[0]
        existing = merged[key]
        for other_key in matching_keys[1:]:
            merge_record_into(existing, merged[other_key])
            del merged[other_key]
            for alias, mapped_key in list(key_aliases.items()):
                if mapped_key == other_key:
                    key_aliases[alias] = key
        existing = merged[key]
        merge_record_into(existing, row)
        for alias in keys:
            key_aliases[alias] = key
    return finalize_dedupe_keys(list(merged.values()))


def finalize_dedupe_keys(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    finalized = []
    for row in rows:
        base_key = title_dedupe_key(row)
        key = base_key
        suffix = 2
        while key in seen:
            key = f"{base_key}:dup{suffix}"
            suffix += 1
        seen.add(key)
        row["dedupe_key"] = key
        finalized.append(row)
    return finalized


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]], columns: Sequence[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def clean_excel_value(value: Any) -> Any:
    if isinstance(value, str):
        return EXCEL_ILLEGAL_CHARS_RE.sub("", value)
    return value


def clean_excel_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.map(clean_excel_value)


def candidate_pdf_urls(row: Dict[str, Any]) -> List[str]:
    candidates = []
    for col in ("pdf_url", "open_access_pdf_url"):
        value = str(row.get(col) or "").strip()
        if value and value.lower() != "nan":
            candidates.append(value)
    arxiv_id = str(row.get("arxiv_id") or "").strip()
    if arxiv_id and arxiv_id.lower() != "nan":
        candidates.append(f"https://arxiv.org/pdf/{arxiv_id}.pdf")
    acl_id = str(row.get("acl_id") or "").strip()
    if acl_id and acl_id.lower() != "nan":
        candidates.append(f"https://aclanthology.org/{acl_id}.pdf")
    doi = str(row.get("doi") or "").strip()
    if doi and doi.lower() != "nan":
        candidates.append(f"https://doi.org/{doi}")
    seen = set()
    unique = []
    for url in candidates:
        if url not in seen:
            unique.append(url)
            seen.add(url)
    return unique


def is_pdf_response(response: requests.Response) -> bool:
    ctype = response.headers.get("content-type", "").lower()
    return "application/pdf" in ctype or response.content[:5] == b"%PDF-"


def absolute_candidate(base_url: str, href: str) -> str:
    return urllib.parse.urljoin(base_url, href)


def try_download_url(session: requests.Session, url: str, path: Path) -> Tuple[bool, str]:
    try:
        response = session.get(url, timeout=35, allow_redirects=True)
        if response.ok and is_pdf_response(response):
            path.write_bytes(response.content)
            return True, response.url
        if not response.ok or "text/html" not in response.headers.get("content-type", "").lower():
            return False, f"not a downloadable PDF: HTTP {response.status_code}"
        soup = BeautifulSoup(response.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        links = []
        if meta and meta.get("content"):
            links.append(meta["content"])
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            if ".pdf" in href.lower() or "pdf" in text:
                links.append(absolute_candidate(response.url, href))
        for pdf_url in links[:5]:
            pdf_response = session.get(pdf_url, timeout=35, allow_redirects=True)
            if pdf_response.ok and is_pdf_response(pdf_response):
                path.write_bytes(pdf_response.content)
                return True, pdf_response.url
        return False, "no PDF link found on landing page"
    except Exception as exc:
        return False, str(exc)


def arxiv_fallback(session: requests.Session, title: str, path: Path) -> Tuple[bool, str]:
    if not title:
        return False, "empty title"
    try:
        response = session.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": f'ti:"{title}"', "start": 0, "max_results": 1},
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return False, "no arXiv match"
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        if not pdf_url:
            arxiv_id = (entry.findtext("atom:id", default="", namespaces=ns).rstrip("/").split("/")[-1])
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""
        return try_download_url(session, pdf_url, path) if pdf_url else (False, "no arXiv PDF URL")
    except Exception as exc:
        return False, str(exc)


def extract_pdf_pages(pdf_path: Path) -> List[List[str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [(page.extract_text() or "").splitlines() for page in reader.pages]


def detect_references(lines_by_page: List[List[str]]) -> Tuple[int, int]:
    heading_re = re.compile(r"^\s*(references|bibliography)\s*$", re.I)
    for page_idx, lines in enumerate(lines_by_page):
        for line_idx, line in enumerate(lines):
            if heading_re.match(line.strip()):
                return page_idx, line_idx
    return len(lines_by_page), 0


def line_is_before_boundary(page_idx: int, line_idx: int, boundary: Tuple[int, int]) -> bool:
    boundary_page, boundary_line = boundary
    return page_idx < boundary_page or (page_idx == boundary_page and line_idx < boundary_line)


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def author_surnames(target: Dict[str, Any]) -> List[str]:
    out = []
    for author in target.get("authors", []) or []:
        name = author.get("name") if isinstance(author, dict) else str(author)
        parts = re.findall(r"[A-Za-z]+", name or "")
        if parts:
            out.append(parts[-1].lower())
    return out


def target_years(target: Dict[str, Any]) -> List[str]:
    years = set()
    if target.get("year"):
        years.add(str(target["year"]))
    return sorted(years)


def target_ids(target: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    external = target.get("externalIds") or {}
    for key in ("DOI", "ArXiv"):
        value = text_value(external.get(key)).strip()
        if value:
            ids.append(value.lower())
    return ids


def reference_lines(lines_by_page: Sequence[Sequence[str]], boundary: Tuple[int, int]) -> List[Tuple[int, int, str]]:
    boundary_page, boundary_line = boundary
    if boundary_page >= len(lines_by_page):
        return []
    out: List[Tuple[int, int, str]] = []
    for page_idx in range(boundary_page, len(lines_by_page)):
        start = boundary_line + 1 if page_idx == boundary_page else 0
        for line_idx, line in enumerate(lines_by_page[page_idx][start:], start):
            cleaned = line.strip()
            if cleaned:
                out.append((page_idx, line_idx, cleaned))
    return out


def reference_label(line: str) -> str:
    match = REF_LABEL_RE.match(line)
    if not match:
        return ""
    label = match.group(1) or match.group(2) or ""
    return "" if int(label) > 1000 else label


def segment_references(ref_lines: Sequence[Tuple[int, int, str]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    current: List[Tuple[int, int, str]] = []
    current_label = ""
    for item in ref_lines:
        label = reference_label(item[2])
        if label and current:
            entries.append({"label": current_label, "lines": current})
            current = []
        if label:
            current_label = label
        current.append(item)
    if current:
        entries.append({"label": current_label, "lines": current})
    return entries


def score_reference(entry_text: str, target: Dict[str, Any]) -> Tuple[float, List[str]]:
    title = text_value(target.get("title"))
    norm_entry = normalize_text(entry_text)
    norm_title = normalize_text(title)
    score = 0.0
    evidence: List[str] = []
    if "shapegpt" in norm_entry:
        score += 8.0
        evidence.append("contains ShapeGPT")
    if norm_title and norm_title in norm_entry:
        score += 10.0
        evidence.append("contains normalized title")
    for identifier in target_ids(target):
        if identifier and identifier in entry_text.lower():
            score += 8.0
            evidence.append(f"contains {identifier}")
    overlap = token_overlap(title, entry_text)
    if overlap >= 0.80:
        score += 5.0
        evidence.append(f"title token overlap {overlap:.2f}")
    elif overlap >= 0.65:
        score += 3.0
        evidence.append(f"title token overlap {overlap:.2f}")
    surnames = author_surnames(target)
    years = target_years(target)
    if surnames and years and surnames[0] in norm_entry and any(year in norm_entry for year in years):
        score += 3.0
        evidence.append(f"first author/year {surnames[0]} {','.join(years)}")
    return score, evidence


def find_target_reference(
    lines_by_page: Sequence[Sequence[str]], target: Dict[str, Any], boundary: Tuple[int, int]
) -> Optional[Dict[str, Any]]:
    scored: List[Dict[str, Any]] = []
    for entry in segment_references(reference_lines(lines_by_page, boundary)):
        entry_text = " ".join(line for _, _, line in entry["lines"])
        score, evidence = score_reference(entry_text, target)
        if score >= 8.0:
            scored.append(
                {
                    "label": entry.get("label", ""),
                    "text": entry_text,
                    "score": score,
                    "evidence": "; ".join(evidence),
                }
            )
    if scored:
        return max(scored, key=lambda item: item["score"])

    ref_lines = reference_lines(lines_by_page, boundary)
    for idx in range(len(ref_lines)):
        window_items = ref_lines[idx : idx + 4]
        window = " ".join(item[2] for item in window_items)
        score, evidence = score_reference(window, target)
        if score >= 10.0:
            label = ""
            for _, _, line in window_items:
                label = reference_label(line)
                if label:
                    break
            return {"label": label, "text": window, "score": score, "evidence": "; ".join(evidence)}
    return None


def cite_group_contains(group: str, label: str) -> bool:
    normalized = group
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"):
        normalized = normalized.replace(dash, "-")
    for part in re.split(r"[,;]\s*", normalized):
        part = part.strip()
        if not part:
            continue
        range_match = re.fullmatch(r"(\d{1,4})\s*-\s*(\d{1,4})", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start <= int(label) <= end:
                return True
            continue
        if part == label:
            return True
    return False


def numeric_markers_in_line(line: str, label: str) -> List[str]:
    if not label:
        return []
    markers = []
    for match in BRACKET_CITE_RE.finditer(line):
        if cite_group_contains(match.group(1), label):
            markers.append(match.group(0))
    return markers


def context_window(lines: Sequence[str], line_idx: int, context_lines: int) -> Tuple[int, int, str]:
    start = max(0, line_idx - context_lines)
    end = min(len(lines), line_idx + context_lines + 1)
    snippet = " ".join(line.strip() for line in lines[start:end]).strip()
    return start + 1, end, snippet


def coverage_row(row: Dict[str, Any], status: str, pdf_path: str = "") -> Dict[str, Any]:
    return {
        "citing_title": text_value(row.get("citing_title")),
        "source_platforms": text_value(row.get("source_platforms")),
        "doi": text_value(row.get("doi")),
        "download_status": text_value(row.get("download_status")),
        "analysis_status": status,
        "pdf_path": pdf_path or text_value(row.get("pdf_path")),
        "location_count": 0,
        "pages": "",
        "reference_marker": "",
        "reference_score": "",
        "reference_evidence": "",
        "failure_reason": text_value(row.get("failure_reason")),
        "reference_entry": "",
    }


def analyze_one_pdf(
    row: Dict[str, Any],
    target: Dict[str, Any],
    context_lines: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    pdf_path = Path(text_value(row.get("pdf_path")))
    if row.get("download_status") not in {"downloaded", "manual"}:
        return [], coverage_row(row, "pdf_not_downloaded", str(pdf_path))
    if not pdf_path.exists():
        return [], coverage_row(row, "pdf_missing", str(pdf_path))

    lines_by_page = extract_pdf_pages(pdf_path)
    boundary = detect_references(lines_by_page)
    reference = find_target_reference(lines_by_page, target, boundary)
    coverage = coverage_row(row, "target_reference_not_found", str(pdf_path))
    if not reference:
        return [], coverage

    label = text_value(reference.get("label"))
    reference_marker = f"[{label}]" if label else ""
    coverage.update(
        {
            "reference_marker": reference_marker,
            "reference_score": reference.get("score", ""),
            "reference_evidence": reference.get("evidence", ""),
            "reference_entry": text_value(reference.get("text"))[:2000],
        }
    )

    contexts: List[Dict[str, Any]] = []
    seen = set()
    for page_idx, lines in enumerate(lines_by_page):
        for line_idx, line in enumerate(lines):
            if not line_is_before_boundary(page_idx, line_idx, boundary):
                continue
            matches: List[Tuple[str, str, float]] = []
            for marker in numeric_markers_in_line(line, label):
                matches.append((marker, "verified numeric reference", 0.95))
            if re.search(r"\bShapeGPT\b", line, flags=re.I):
                matches.append(("ShapeGPT", "explicit ShapeGPT mention", 0.98))
            if not matches:
                continue

            line_start, line_end, snippet = context_window(lines, line_idx, context_lines)
            for marker, match_type, confidence in matches:
                key = (page_idx, line_idx, marker, normalize_text(snippet))
                if key in seen:
                    continue
                seen.add(key)
                contexts.append(
                    {
                        "citing_title": text_value(row.get("citing_title")),
                        "source_platforms": text_value(row.get("source_platforms")),
                        "doi": text_value(row.get("doi")),
                        "pdf_path": str(pdf_path),
                        "page": page_idx + 1,
                        "line_start": line_start,
                        "line_end": line_end,
                        "citation_marker": marker,
                        "match_type": match_type,
                        "confidence": confidence,
                        "context": snippet,
                        "is_positive": bool(POSITIVE_RE.search(snippet)),
                        "reference_marker": reference_marker,
                        "reference_score": reference.get("score", ""),
                        "reference_evidence": reference.get("evidence", ""),
                        "reference_entry": text_value(reference.get("text"))[:2000],
                    }
                )

    coverage["location_count"] = len(contexts)
    coverage["pages"] = ";".join(str(page) for page in sorted({item["page"] for item in contexts}))
    coverage["analysis_status"] = "cited_in_body" if contexts else "target_reference_found_no_body_hits"
    return contexts, coverage


def cmd_find(args: argparse.Namespace) -> Tuple[Path, Path]:
    output = ensure_dir(args.output)
    session = make_session()
    api_key = args.s2_api_key or os.environ.get(args.s2_api_key_env or "SEMANTIC_SCHOLAR_API_KEY", "")
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    target: Dict[str, Any] = {"title": args.paper}
    records: List[Dict[str, Any]] = []
    platform_errors: List[Dict[str, str]] = []

    if "semantic-scholar" in platforms:
        try:
            target = s2_resolve_paper(session, args.paper, api_key)
            records.extend(s2_fetch_citations(session, target, args.max_papers, api_key))
        except Exception as exc:
            message = str(exc)
            platform_errors.append({"platform": "semantic-scholar", "error": message})
            print(f"Semantic Scholar failed, continuing with other platforms: {message}", file=sys.stderr)
    if "google-scholar" in platforms:
        try:
            records.extend(
                google_scrape_citing(
                    args.paper,
                    args.max_papers,
                    args.browser,
                    args.min_delay,
                    args.max_delay,
                    args.scholar_locale,
                )
            )
        except Exception as exc:
            message = str(exc)
            platform_errors.append({"platform": "google-scholar", "error": message})
            print(f"Google Scholar failed, continuing with other platforms: {message}", file=sys.stderr)

    if platform_errors:
        target["platform_errors"] = platform_errors
    if not records and platform_errors:
        raise RuntimeError("; ".join(f"{item['platform']}: {item['error']}" for item in platform_errors))

    rows = merge_records(records)
    target_path = output / "target.json"
    citing_path = output / "citing_papers.csv"
    write_json(target_path, target)
    write_csv(citing_path, rows, CITING_COLUMNS)
    print(f"Saved target metadata: {target_path}")
    print(f"Saved citing papers: {citing_path} ({len(rows)} rows)")
    return target_path, citing_path


def download_one_paper(
    idx: int,
    total: int,
    row: Dict[str, Any],
    pdf_dir: Path,
    arxiv_fallback_enabled: bool,
) -> Tuple[int, Dict[str, Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    item = row.copy()
    item["pdf_path"] = ""
    item["download_status"] = "failed"
    item["download_url"] = ""
    item["failure_reason"] = ""
    title = item.get("citing_title", "") or f"paper-{idx + 1}"
    filename = safe_filename(f"{idx + 1:04d}-{title}", 110) + ".pdf"
    pdf_path = pdf_dir / filename
    failure: Optional[Dict[str, Any]] = None
    manual_todo: Optional[Dict[str, Any]] = None

    try:
        if pdf_path.exists():
            item["pdf_path"] = str(pdf_path.resolve())
            item["download_status"] = "downloaded"
            return idx, item, None, None, f"{idx + 1}/{total} downloaded: {title[:80]}"

        session = make_session()
        errors = []
        for url in candidate_pdf_urls(item):
            ok, detail = try_download_url(session, url, pdf_path)
            if ok:
                item["pdf_path"] = str(pdf_path.resolve())
                item["download_status"] = "downloaded"
                item["download_url"] = detail
                break
            errors.append(f"{url}: {detail}")

        if item["download_status"] != "downloaded" and arxiv_fallback_enabled:
            ok, detail = arxiv_fallback(session, title, pdf_path)
            if ok:
                item["pdf_path"] = str(pdf_path.resolve())
                item["download_status"] = "downloaded"
                item["download_url"] = detail
            else:
                errors.append(f"arXiv fallback: {detail}")

        if item["download_status"] != "downloaded":
            item["failure_reason"] = " | ".join(errors) if errors else "no candidate PDF URL"
            failure = item.copy()
            manual_todo = item.copy()
            manual_todo["candidate_urls"] = "; ".join(candidate_pdf_urls(item))
            manual_todo["expected_pdf_path"] = str(pdf_path.resolve())
            manual_todo["manual_pdf_path"] = ""
        return idx, item, failure, manual_todo, f"{idx + 1}/{total} {item['download_status']}: {title[:80]}"
    except Exception as exc:
        item["failure_reason"] = str(exc)
        failure = item.copy()
        manual_todo = item.copy()
        manual_todo["candidate_urls"] = "; ".join(candidate_pdf_urls(item))
        manual_todo["expected_pdf_path"] = str(pdf_path.resolve())
        manual_todo["manual_pdf_path"] = ""
        return idx, item, failure, manual_todo, f"{idx + 1}/{total} failed: {title[:80]}"


def cmd_download(args: argparse.Namespace) -> Tuple[Path, Path]:
    output = ensure_dir(args.output)
    pdf_dir = ensure_dir(output / "pdfs")
    df = pd.read_csv(args.input, dtype=str).fillna("")
    manifest: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    manual_todo: List[Dict[str, Any]] = []
    workers = max(1, int(getattr(args, "download_workers", 4) or 1))
    arxiv_enabled = bool(getattr(args, "arxiv_fallback", True))
    total = len(df)
    jobs = [(idx, row.to_dict()) for idx, row in df.iterrows()]
    results: List[Tuple[int, Dict[str, Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]] = []
    print(f"Downloading {total} papers with {workers} worker(s)")

    if workers == 1:
        for idx, row in jobs:
            result = download_one_paper(idx, total, row, pdf_dir, arxiv_enabled)
            results.append(result)
            print(result[4])
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(download_one_paper, idx, total, row, pdf_dir, arxiv_enabled)
                for idx, row in jobs
            ]
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(result[4])

    for _, item, failure, todo, _ in sorted(results, key=lambda result: result[0]):
        manifest.append(item)
        if failure:
            failures.append(failure)
        if todo:
            manual_todo.append(todo)

    manifest_path = output / "download_manifest.csv"
    failures_path = output / "download_failures.csv"
    manual_todo_path = output / "manual_download_todo.csv"
    pd.DataFrame(manifest).to_csv(manifest_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(failures).to_csv(failures_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(manual_todo).to_csv(manual_todo_path, index=False, encoding="utf-8-sig")
    print(f"Saved download manifest: {manifest_path}")
    print(f"Saved download failures: {failures_path}")
    print(f"Saved manual download todo list: {manual_todo_path}")
    return manifest_path, failures_path


def load_target_for_analysis(args: argparse.Namespace) -> Dict[str, Any]:
    if args.target_json and Path(args.target_json).exists():
        return json.loads(Path(args.target_json).read_text(encoding="utf-8"))
    target_path = Path(args.output) / "target.json"
    if target_path.exists():
        return json.loads(target_path.read_text(encoding="utf-8"))
    return {"title": args.target_title or ""}


def rows_for_analysis(args: argparse.Namespace) -> List[Dict[str, Any]]:
    manifest_path = Path(args.output) / "download_manifest.csv"
    manual_todo_path = Path(args.output) / "manual_download_todo.csv"
    rows: List[Dict[str, Any]] = []
    if manifest_path.exists():
        df = pd.read_csv(manifest_path, dtype=str).fillna("")
        rows = df.to_dict("records")
    if manual_todo_path.exists():
        todo_df = pd.read_csv(manual_todo_path, dtype=str).fillna("")
        existing = {
            str(Path(row.get("pdf_path", "")).resolve())
            for row in rows
            if row.get("pdf_path") and Path(row.get("pdf_path", "")).exists()
        }
        for row in todo_df.to_dict("records"):
            manual_path = row.get("manual_pdf_path", "").strip()
            expected_path = row.get("expected_pdf_path", "").strip()
            pdf_path = manual_path or expected_path
            if not pdf_path or not Path(pdf_path).exists():
                continue
            resolved = str(Path(pdf_path).resolve())
            if resolved in existing:
                continue
            row["pdf_path"] = resolved
            row["download_status"] = "manual"
            rows.append(row)
            existing.add(resolved)
    if rows:
        return rows
    metadata = pd.read_csv(args.metadata, dtype=str).fillna("") if args.metadata else pd.DataFrame()
    by_name = {safe_filename(row.get("citing_title", ""), 110): row for row in metadata.to_dict("records")}
    rows = []
    for pdf in Path(args.pdf_dir).glob("*.pdf"):
        key = safe_filename(pdf.stem, 110)
        row = by_name.get(key, {})
        row["pdf_path"] = str(pdf.resolve())
        rows.append(row)
    return rows


def dashboard_records(df: pd.DataFrame, columns: Sequence[str]) -> List[Dict[str, Any]]:
    subset = df.reindex(columns=columns).fillna("")
    return [{key: text_value(value) for key, value in row.items()} for row in subset.to_dict("records")]


def dashboard_counts(series: pd.Series) -> Dict[str, int]:
    return {str(key): int(value) for key, value in series.fillna("Unknown").value_counts().items()}


def build_dashboard_payload(output: Path) -> Dict[str, Any]:
    required = [
        output / "target.json",
        output / "citing_papers.csv",
        output / "download_manifest.csv",
        output / "citation_locations_reliable.csv",
        output / "citation_paper_coverage_reliable.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Cannot build dashboard; missing files: {', '.join(missing)}")

    target = json.loads((output / "target.json").read_text(encoding="utf-8"))
    citing = pd.read_csv(output / "citing_papers.csv")
    manifest = pd.read_csv(output / "download_manifest.csv")
    locations = pd.read_csv(output / "citation_locations_reliable.csv")
    coverage = pd.read_csv(output / "citation_paper_coverage_reliable.csv")

    normalized_titles = (
        citing["citing_title"].fillna("").astype(str).str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    )
    year_counts = (
        citing["publication_year"]
        .fillna("Unknown")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .value_counts()
        .sort_index()
    )
    top_locations = (
        coverage[coverage["location_count"].fillna(0).astype(int) > 0]
        .sort_values(["location_count", "citing_title"], ascending=[False, True])
        .head(12)
    )
    coverage_with_meta = coverage.merge(
        citing[
            [
                "citing_title",
                "publication_year",
                "venue",
                "citation_count",
                "url",
                "semantic_scholar_paper_id",
                "google_scholar_cited_by_url",
            ]
        ],
        on="citing_title",
        how="left",
    )
    external = target.get("externalIds") or {}
    return {
        "target": {
            "title": target.get("title", ""),
            "year": target.get("year", ""),
            "citationCount": target.get("citationCount", ""),
            "url": target.get("url", ""),
            "doi": external.get("DOI", ""),
            "arxiv": external.get("ArXiv", ""),
        },
        "stats": {
            "citingRows": int(len(citing)),
            "titleUniqueRows": int(normalized_titles.nunique()),
            "titleDuplicateGroups": int((normalized_titles.value_counts() > 1).sum()),
            "downloaded": int((manifest["download_status"] == "downloaded").sum()),
            "failed": int((manifest["download_status"] == "failed").sum()),
            "locationRows": int(len(locations)),
            "locatedPapers": int(locations["citing_title"].nunique()) if len(locations) else 0,
            "positiveLocations": int(locations["is_positive"].sum()) if "is_positive" in locations else 0,
        },
        "charts": {
            "sourcePlatforms": dashboard_counts(citing["source_platforms"]),
            "publicationYears": {str(key): int(value) for key, value in year_counts.items()},
            "downloadStatus": dashboard_counts(manifest["download_status"]),
            "analysisStatus": dashboard_counts(coverage["analysis_status"]),
            "matchType": dashboard_counts(locations["match_type"]) if len(locations) else {},
        },
        "topLocations": dashboard_records(
            top_locations,
            ["citing_title", "analysis_status", "location_count", "pages", "reference_marker", "source_platforms"],
        ),
        "papers": dashboard_records(
            coverage_with_meta,
            [
                "citing_title",
                "publication_year",
                "venue",
                "citation_count",
                "source_platforms",
                "download_status",
                "analysis_status",
                "location_count",
                "pages",
                "reference_marker",
                "reference_evidence",
                "failure_reason",
                "url",
            ],
        ),
        "locations": dashboard_records(
            locations,
            [
                "citing_title",
                "page",
                "line_start",
                "line_end",
                "citation_marker",
                "match_type",
                "confidence",
                "is_positive",
                "context",
                "reference_marker",
                "source_platforms",
                "doi",
            ],
        ),
    }


def dashboard_html(payload: Dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>引用调查可视化</title>
  <style>
    :root { --bg:#f6f7f9; --panel:#fff; --ink:#202124; --muted:#64707d; --line:#d9dee5; --teal:#0f766e; --blue:#2563eb; --amber:#b7791f; --rose:#be123c; --violet:#7c3aed; --green:#15803d; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 "Segoe UI", Arial, sans-serif; }
    header { background:#fff; border-bottom:1px solid var(--line); }
    .wrap { max-width:1440px; margin:0 auto; padding:18px 22px; }
    .title-row { display:grid; grid-template-columns:1fr auto; gap:16px; align-items:end; }
    h1 { margin:0; font-size:24px; line-height:1.2; letter-spacing:0; }
    h2 { margin:0; padding:13px 14px 0; font-size:16px; letter-spacing:0; }
    .subline { margin-top:6px; color:var(--muted); display:flex; gap:14px; flex-wrap:wrap; }
    .links { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
    a.button { color:var(--teal); border:1px solid #9ccfca; padding:7px 10px; border-radius:6px; text-decoration:none; background:#f2fbfa; white-space:nowrap; }
    main.wrap { display:grid; gap:16px; }
    .stats { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; }
    .stat,.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:0 1px 2px rgba(16,24,40,.08); }
    .stat { padding:12px; min-height:86px; }
    .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:0; }
    .value { margin-top:8px; font-size:26px; font-weight:700; line-height:1; }
    .note { margin-top:8px; color:var(--muted); font-size:12px; }
    .grid { display:grid; grid-template-columns:repeat(12,1fr); gap:16px; }
    .span-4 { grid-column:span 4; } .span-5 { grid-column:span 5; } .span-7 { grid-column:span 7; } .span-12 { grid-column:span 12; }
    .panel-body { padding:14px; }
    .bars { display:grid; gap:11px; }
    .bar-row { display:grid; grid-template-columns:minmax(130px,1fr) minmax(160px,2fr) 42px; gap:10px; align-items:center; }
    .bar-label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#334155; }
    .bar-track { height:12px; background:#edf0f4; border-radius:999px; overflow:hidden; }
    .bar-fill { height:100%; background:var(--teal); border-radius:999px; }
    .bar-value { color:var(--muted); text-align:right; font-variant-numeric:tabular-nums; }
    .filters { display:grid; grid-template-columns:1.5fr 220px 220px; gap:10px; margin-bottom:12px; }
    input,select { width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--ink); }
    table { width:100%; border-collapse:collapse; table-layout:fixed; }
    th,td { padding:9px 8px; border-bottom:1px solid #edf0f4; vertical-align:top; text-align:left; }
    th { color:#475569; font-size:12px; background:#fafafa; position:sticky; top:0; z-index:1; }
    td { color:#26313d; word-wrap:break-word; }
    .table-wrap { max-height:520px; overflow:auto; border:1px solid var(--line); border-radius:8px; }
    .pill { display:inline-flex; align-items:center; min-height:22px; padding:2px 7px; border-radius:999px; font-size:12px; border:1px solid transparent; white-space:nowrap; }
    .ok { color:#166534; background:#ecfdf3; border-color:#bbf7d0; } .warn { color:#92400e; background:#fffbeb; border-color:#fde68a; } .bad { color:#9f1239; background:#fff1f2; border-color:#fecdd3; } .neutral { color:#475569; background:#f8fafc; border-color:#e2e8f0; }
    .context { color:#334155; max-width:760px; } .muted { color:var(--muted); }
    @media (max-width:980px) { .title-row,.filters { grid-template-columns:1fr; } .links { justify-content:flex-start; } .stats { grid-template-columns:repeat(2,minmax(0,1fr)); } .span-4,.span-5,.span-7,.span-12 { grid-column:span 12; } }
  </style>
</head>
<body>
  <header><div class="wrap title-row"><div><h1>引用调查可视化</h1><div class="subline" id="targetMeta"></div></div><nav class="links"><a class="button" href="citing_papers.csv">被引列表 CSV</a><a class="button" href="citation_locations_reliable.csv">引用位置 CSV</a><a class="button" href="citation_locations_reliable.xlsx">可靠结果 Excel</a></nav></div></header>
  <main class="wrap">
    <section class="stats" id="stats"></section>
    <section class="grid">
      <article class="panel span-4"><h2>来源分布</h2><div class="panel-body" id="sourceChart"></div></article>
      <article class="panel span-4"><h2>下载状态</h2><div class="panel-body" id="downloadChart"></div></article>
      <article class="panel span-4"><h2>第三步覆盖状态</h2><div class="panel-body" id="coverageChart"></div></article>
      <article class="panel span-5"><h2>发表年份</h2><div class="panel-body" id="yearChart"></div></article>
      <article class="panel span-7"><h2>引用位置最多的论文</h2><div class="panel-body" id="topChart"></div></article>
      <article class="panel span-12"><h2>论文覆盖表</h2><div class="panel-body"><div class="filters"><input id="paperSearch" placeholder="搜索论文、venue、URL"><select id="statusFilter"></select><select id="sourceFilter"></select></div><div class="table-wrap"><table><thead><tr><th style="width:34%">论文</th><th style="width:8%">年份</th><th style="width:13%">来源</th><th style="width:14%">状态</th><th style="width:9%">位置数</th><th style="width:10%">页码</th><th style="width:12%">参考标记</th></tr></thead><tbody id="paperRows"></tbody></table></div></div></article>
      <article class="panel span-12"><h2>可靠引用位置</h2><div class="panel-body"><div class="filters"><input id="locationSearch" placeholder="搜索论文、引用标记、上下文"><select id="matchFilter"></select><select id="positiveFilter"><option value="">全部情感/用途</option><option value="true">positive</option><option value="false">not positive</option></select></div><div class="table-wrap"><table><thead><tr><th style="width:25%">论文</th><th style="width:8%">页/行</th><th style="width:14%">标记</th><th style="width:14%">匹配类型</th><th style="width:39%">上下文</th></tr></thead><tbody id="locationRows"></tbody></table></div></div></article>
    </section>
  </main>
  <script id="payload" type="application/json">__DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('payload').textContent);
    const colors = ['#0f766e','#2563eb','#b7791f','#be123c','#7c3aed','#15803d','#6b7280'];
    function esc(v){ return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch])); }
    function pillClass(v){ if(['downloaded','cited_in_body'].includes(v)) return 'ok'; if(['failed','pdf_not_downloaded','target_reference_not_found','pdf_missing','pdf_parse_failed'].includes(v)) return 'bad'; if(v==='target_reference_found_no_body_hits') return 'warn'; return 'neutral'; }
    function barChart(id,obj,limit=12){ const entries=Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,limit); const max=Math.max(1,...entries.map(([,v])=>v)); document.getElementById(id).innerHTML='<div class="bars">'+entries.map(([label,value],idx)=>`<div class="bar-row"><div class="bar-label" title="${esc(label)}">${esc(label)}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(3,value/max*100)}%;background:${colors[idx%colors.length]}"></div></div><div class="bar-value">${value}</div></div>`).join('')+'</div>'; }
    function fillSelect(id,label,values){ const el=document.getElementById(id); el.innerHTML=`<option value="">${esc(label)}</option>`+[...new Set(values.filter(Boolean))].sort().map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join(''); }
    function renderTarget(){ const t=data.target; document.getElementById('targetMeta').innerHTML=[`目标论文：${esc(t.title)}`,`年份：${esc(t.year)}`,`Semantic Scholar citationCount：${esc(t.citationCount)}`,t.doi?`DOI：${esc(t.doi)}`:'',t.arxiv?`arXiv：${esc(t.arxiv)}`:''].filter(Boolean).map(x=>`<span>${x}</span>`).join(''); }
    function renderStats(){ const s=data.stats; const items=[['被引记录',s.citingRows,`${s.titleUniqueRows} 个标题去重后唯一项`],['PDF 下载成功',s.downloaded,`${s.failed} 个失败进入 manual todo`],['可靠引用位置',s.locationRows,`覆盖 ${s.locatedPapers} 篇论文`],['Positive 位置',s.positiveLocations,'关键词启发式标记'],['标题疑似重复组',s.titleDuplicateGroups,'跨平台年份/标题差异'],['第三步输出','Reliable','自动生成前端展示']]; document.getElementById('stats').innerHTML=items.map(([label,value,note])=>`<article class="stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="note">${esc(note)}</div></article>`).join(''); }
    function renderPaperRows(){ const q=document.getElementById('paperSearch').value.toLowerCase(); const status=document.getElementById('statusFilter').value; const source=document.getElementById('sourceFilter').value; const rows=data.papers.filter(row=>{ const hay=[row.citing_title,row.venue,row.url,row.reference_evidence].join(' ').toLowerCase(); return (!q||hay.includes(q))&&(!status||row.analysis_status===status)&&(!source||row.source_platforms===source); }); document.getElementById('paperRows').innerHTML=rows.map(row=>`<tr><td>${esc(row.citing_title)}<div class="muted">${esc(row.venue||'')}</div></td><td>${esc(String(row.publication_year||'').replace(/\.0$/,''))}</td><td>${esc(row.source_platforms)}</td><td><span class="pill ${pillClass(row.analysis_status)}">${esc(row.analysis_status)}</span></td><td>${esc(row.location_count||0)}</td><td>${esc(row.pages||'')}</td><td>${esc(row.reference_marker||'')}</td></tr>`).join(''); }
    function renderLocationRows(){ const q=document.getElementById('locationSearch').value.toLowerCase(); const match=document.getElementById('matchFilter').value; const positive=document.getElementById('positiveFilter').value; const rows=data.locations.filter(row=>{ const hay=[row.citing_title,row.citation_marker,row.match_type,row.context].join(' ').toLowerCase(); const isPositive=String(row.is_positive).toLowerCase(); return (!q||hay.includes(q))&&(!match||row.match_type===match)&&(!positive||isPositive===positive); }); document.getElementById('locationRows').innerHTML=rows.map(row=>`<tr><td>${esc(row.citing_title)}</td><td>p.${esc(row.page)}<div class="muted">L${esc(row.line_start)}-${esc(row.line_end)}</div></td><td>${esc(row.citation_marker)}<div class="muted">ref ${esc(row.reference_marker||'')}</div></td><td><span class="pill neutral">${esc(row.match_type)}</span><div class="muted">conf ${esc(row.confidence)}</div></td><td class="context">${esc(row.context)}</td></tr>`).join(''); }
    function init(){ renderTarget(); renderStats(); barChart('sourceChart',data.charts.sourcePlatforms); barChart('downloadChart',data.charts.downloadStatus); barChart('coverageChart',data.charts.analysisStatus); barChart('yearChart',data.charts.publicationYears); barChart('topChart',Object.fromEntries(data.topLocations.map(row=>[row.citing_title,Number(row.location_count)||0])),12); fillSelect('statusFilter','全部覆盖状态',data.papers.map(row=>row.analysis_status)); fillSelect('sourceFilter','全部来源',data.papers.map(row=>row.source_platforms)); fillSelect('matchFilter','全部匹配类型',data.locations.map(row=>row.match_type)); ['paperSearch','statusFilter','sourceFilter'].forEach(id=>document.getElementById(id).addEventListener('input',renderPaperRows)); ['locationSearch','matchFilter','positiveFilter'].forEach(id=>document.getElementById(id).addEventListener('input',renderLocationRows)); renderPaperRows(); renderLocationRows(); }
    init();
  </script>
</body>
</html>
"""
    return template.replace("__DATA__", data_json)


def write_dashboard(output: Path) -> Path:
    dashboard_path = output / "citation_dashboard.html"
    dashboard_path.write_text(dashboard_html(build_dashboard_payload(output)), encoding="utf-8")
    return dashboard_path


def cmd_analyze(args: argparse.Namespace) -> Path:
    output = ensure_dir(args.output)
    target = load_target_for_analysis(args)
    target_title = args.target_title or target.get("title") or ""
    if not target_title:
        raise RuntimeError("Analyze requires --target-title or target.json with title.")
    target["title"] = target_title
    rows = rows_for_analysis(args)
    contexts: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        try:
            hits, status = analyze_one_pdf(row, target, args.context_lines)
            contexts.extend(hits)
            coverage.append(status)
            print(f"{idx}/{len(rows)} {status['analysis_status']}: {status['citing_title']} ({len(hits)} locations)")
        except Exception as exc:
            status = coverage_row(row, "pdf_parse_failed")
            status["failure_reason"] = str(exc)
            coverage.append(status)
            print(f"{idx}/{len(rows)} failed: {status['citing_title']}: {exc}", file=sys.stderr)
    if args.analysis_scope == "positive-only":
        contexts = [row for row in contexts if row.get("is_positive")]
    contexts_path = output / "citation_locations_reliable.csv"
    write_csv(contexts_path, contexts, CONTEXT_COLUMNS)
    coverage_path = output / "citation_paper_coverage_reliable.csv"
    write_csv(coverage_path, coverage, COVERAGE_COLUMNS)
    workbook_path = output / "citation_locations_reliable.xlsx"
    with pd.ExcelWriter(workbook_path) as writer:
        clean_excel_frame(pd.DataFrame(contexts, columns=CONTEXT_COLUMNS)).to_excel(
            writer, sheet_name="locations", index=False
        )
        if contexts:
            summary = (
                pd.DataFrame(contexts)
                .groupby("citing_title", dropna=False)
                .agg(
                    location_count=("context", "count"),
                    positive_count=("is_positive", "sum"),
                    pages=("page", lambda values: ";".join(str(page) for page in sorted(set(values)))),
                    markers=("citation_marker", lambda values: "; ".join(sorted(set(map(str, values))))),
                    match_types=("match_type", lambda values: "; ".join(sorted(set(map(str, values))))),
                )
                .reset_index()
            )
        else:
            summary = pd.DataFrame(
                columns=["citing_title", "location_count", "positive_count", "pages", "markers", "match_types"]
            )
        summary = clean_excel_frame(summary)
        summary.to_excel(writer, sheet_name="per_paper_summary", index=False)
        clean_excel_frame(pd.DataFrame(coverage, columns=COVERAGE_COLUMNS)).to_excel(
            writer, sheet_name="coverage", index=False
        )
    print(f"Saved reliable citation locations: {contexts_path}")
    print(f"Saved reliable paper coverage: {coverage_path}")
    print(f"Saved reliable citation workbook: {workbook_path}")
    dashboard_path = write_dashboard(output)
    print(f"Saved citation dashboard: {dashboard_path}")
    return contexts_path


def cmd_dashboard(args: argparse.Namespace) -> Path:
    output = ensure_dir(args.output)
    dashboard_path = write_dashboard(output)
    print(f"Saved citation dashboard: {dashboard_path}")
    return dashboard_path


def cmd_run(args: argparse.Namespace) -> None:
    find_args = argparse.Namespace(**vars(args))
    _, citing_path = cmd_find(find_args)
    download_args = argparse.Namespace(
        input=str(citing_path),
        output=args.output,
        arxiv_fallback=args.arxiv_fallback,
        download_workers=args.download_workers,
    )
    cmd_download(download_args)
    analyze_args = argparse.Namespace(
        target_title="",
        target_json=str(Path(args.output) / "target.json"),
        metadata=str(citing_path),
        pdf_dir=str(Path(args.output) / "pdfs"),
        output=args.output,
        context_lines=args.context_lines,
        analysis_scope=args.analysis_scope,
    )
    cmd_analyze(analyze_args)


def add_common_find_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--paper", required=True, help="Target paper title or DOI")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--platforms", default="google-scholar,semantic-scholar")
    parser.add_argument("--max-papers", type=int, default=1000, help="Maximum citing papers per platform (default: 1000)")
    parser.add_argument("--browser", choices=["chrome", "edge", "firefox"], default="edge")
    parser.add_argument("--scholar-locale", default="zh-CN", help="Google Scholar UI locale for search/cited-by pages (default: zh-CN)")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    parser.add_argument("--s2-api-key", default="")
    parser.add_argument("--s2-api-key-env", default="SEMANTIC_SCHOLAR_API_KEY")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find, download, and analyze papers citing a target paper.")
    sub = parser.add_subparsers(dest="command", required=True)

    find_p = sub.add_parser("find", help="Find citing papers")
    add_common_find_args(find_p)
    find_p.set_defaults(func=cmd_find)

    download_p = sub.add_parser("download", help="Download open PDFs from citing_papers.csv")
    download_p.add_argument("--input", required=True)
    download_p.add_argument("--output", required=True)
    download_p.add_argument("--arxiv-fallback", action=argparse.BooleanOptionalAction, default=True)
    download_p.add_argument("--download-workers", type=int, default=4, help="Parallel PDF download workers (default: 4)")
    download_p.set_defaults(func=cmd_download)

    analyze_p = sub.add_parser("analyze", help="Analyze downloaded PDFs for citation contexts")
    analyze_p.add_argument("--target-title", default="")
    analyze_p.add_argument("--target-json", default="")
    analyze_p.add_argument("--metadata", default="")
    analyze_p.add_argument("--pdf-dir", required=True)
    analyze_p.add_argument("--output", required=True)
    analyze_p.add_argument("--context-lines", type=int, default=2)
    analyze_p.add_argument("--analysis-scope", choices=["all-contexts", "positive-only", "summary-only"], default="all-contexts")
    analyze_p.set_defaults(func=cmd_analyze)

    dashboard_p = sub.add_parser("dashboard", help="Build the citation dashboard from existing outputs")
    dashboard_p.add_argument("--output", required=True)
    dashboard_p.set_defaults(func=cmd_dashboard)

    run_p = sub.add_parser("run", help="Run find, download, and analyze")
    add_common_find_args(run_p)
    run_p.add_argument("--arxiv-fallback", action=argparse.BooleanOptionalAction, default=True)
    run_p.add_argument("--download-workers", type=int, default=4, help="Parallel PDF download workers (default: 4)")
    run_p.add_argument("--context-lines", type=int, default=2)
    run_p.add_argument("--analysis-scope", choices=["all-contexts", "positive-only", "summary-only"], default="all-contexts")
    run_p.set_defaults(func=cmd_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

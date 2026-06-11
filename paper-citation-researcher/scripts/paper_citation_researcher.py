#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
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
    r"(?:Cited by|\u88ab\u5f15\u7528\u6b21\u6570|\u5f15\u7528\u6b21\u6570)\s*[\uff1a:]?\s*([\d,，]+)",
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
    "citing_authors_json",
    "citing_author_ids",
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
GOOGLE_AUTHOR_TIMEOUT = 10
PROFILE_ENRICHMENT_VERSION = "2026-06-10-profile-v7-identity-background"
GOOGLE_AUTHOR_ENRICHMENT_VERSION = "2026-06-10-google-author-v6-cited-by-locale"
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
    "citing_authors_json",
    "citing_author_ids",
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

AUTHOR_COLUMNS = [
    "rank",
    "author_key",
    "name",
    "normalized_name",
    "semantic_author_id",
    "is_target_author",
    "target_author_match",
    "citing_paper_count",
    "max_citing_paper_citation_count",
    "sum_citing_paper_citation_count",
    "citing_titles",
    "google_scholar_citations",
    "google_scholar_profile_url",
    "google_scholar_homepage_url",
    "google_scholar_affiliation",
    "google_scholar_interests",
    "google_scholar_match_status",
    "semantic_scholar_citations",
    "semantic_scholar_h_index",
    "semantic_scholar_paper_count",
    "semantic_scholar_affiliations",
    "semantic_scholar_profile_url",
    "semantic_scholar_homepage_url",
    "selected_citation_count",
    "selected_citation_source",
    "profile_query_status",
    "notes",
]

EXPERT_COLUMNS = [
    "rank",
    "author_key",
    "name",
    "selected_citation_count",
    "selected_citation_source",
    "semantic_scholar_h_index",
    "google_scholar_profile_url",
    "semantic_scholar_profile_url",
    "wikipedia_title",
    "wikipedia_url",
    "wikidata_id",
    "wikidata_description",
    "wikipedia_summary",
    "wikipedia_evidence",
    "wikidata_evidence",
    "academic_titles",
    "honors_awards",
    "professional_memberships",
    "leadership_roles",
    "profile_affiliations",
    "research_interests",
    "personal_homepage_url",
    "personal_homepage_evidence",
    "personal_homepage_summary",
    "personal_homepage_identity_status",
    "personal_homepage_identity_confidence",
    "personal_homepage_identity_evidence",
    "personal_homepage_rejection_reason",
    "profile_evidence_sources",
    "notability_confidence",
    "expert_query_status",
    "expert_rejection_reason",
    "is_notable",
    "notable_reason",
]

NOTABLE_COLUMNS = [
    "author_name",
    "selected_citation_count",
    "selected_citation_source",
    "notable_reason",
    "wikipedia_url",
    "citing_title",
    "publication_year",
    "venue",
    "source_platforms",
    "analysis_status",
    "location_count",
    "pages",
    "citation_markers",
    "citation_location_status",
    "citation_context_sample",
]

TOP_AUTHOR_COLUMNS = [
    "top_author_key",
    "top_author_name",
    "top_author_selected_citation_count",
    "top_author_selected_citation_source",
    "top_author_profile_url",
    "top_author_homepage_url",
    "top_author_is_notable",
    "top_author_status",
    "target_author_excluded_count",
]

DOWNLOAD_COLUMNS = [
    "pdf_path",
    "download_status",
    "download_url",
    "failure_reason",
]

MANUAL_COLUMNS = CITING_COLUMNS + DOWNLOAD_COLUMNS + [
    "candidate_urls",
    "expected_pdf_path",
    "manual_pdf_path",
]

DOWNLOAD_DETAIL_COLUMNS = CITING_COLUMNS + DOWNLOAD_COLUMNS + [
    "candidate_urls",
    "expected_pdf_path",
    "manual_pdf_path",
]

PAPER_COLUMNS = CITING_COLUMNS + [
    "pdf_path",
    "download_status",
    "download_url",
    "analysis_status",
    "location_count",
    "pages",
    "reference_marker",
    "reference_score",
    "reference_evidence",
    "reference_entry",
    "failure_reason",
] + TOP_AUTHOR_COLUMNS

PAPER_AUTHOR_COLUMNS = [
    "dedupe_key",
    "citing_title",
    "publication_year",
    "venue",
    "author_order",
    "author_key",
    "name",
    "normalized_name",
    "semantic_author_id",
    "is_target_author",
    "target_author_match",
    "selected_citation_count",
    "selected_citation_source",
    "google_scholar_citations",
    "semantic_scholar_citations",
    "semantic_scholar_h_index",
    "google_scholar_profile_url",
    "google_scholar_homepage_url",
    "semantic_scholar_profile_url",
    "semantic_scholar_homepage_url",
    "personal_homepage_url",
    "profile_query_status",
    "notes",
]

AUTHOR_REPORT_COLUMNS = AUTHOR_COLUMNS + [
    "wikipedia_title",
    "wikipedia_url",
    "wikidata_id",
    "wikidata_description",
    "wikipedia_summary",
    "wikipedia_evidence",
    "wikidata_evidence",
    "academic_titles",
    "honors_awards",
    "professional_memberships",
    "leadership_roles",
    "profile_affiliations",
    "research_interests",
    "personal_homepage_url",
    "personal_homepage_evidence",
    "personal_homepage_summary",
    "profile_evidence_sources",
    "notability_confidence",
    "expert_query_status",
    "expert_rejection_reason",
    "is_notable",
    "notable_reason",
]

TARGET_COLUMNS = [
    "record_type",
    "field",
    "value",
    "author_order",
    "author_name",
    "author_id",
]

RUN_NOTE_COLUMNS = ["key", "value"]

REPORT_FILENAME = "citation_report.xlsx"
REPORT_SHEETS = {
    "target": TARGET_COLUMNS,
    "papers": PAPER_COLUMNS,
    "paper_authors": PAPER_AUTHOR_COLUMNS,
    "authors": AUTHOR_REPORT_COLUMNS,
    "citation_locations": CONTEXT_COLUMNS,
    "downloaded_papers": DOWNLOAD_DETAIL_COLUMNS,
    "download_failures": DOWNLOAD_DETAIL_COLUMNS,
    "manual_download_todo": MANUAL_COLUMNS,
    "notable_citations": NOTABLE_COLUMNS,
    "run_notes": RUN_NOTE_COLUMNS,
}

LEGACY_TABLE_FILES = [
    "target.json",
    "citing_papers.csv",
    "download_manifest.csv",
    "download_failures.csv",
    "manual_download_todo.csv",
    "citation_paper_coverage_reliable.csv",
    "citation_locations_reliable.csv",
    "citation_locations_reliable.xlsx",
    "author_candidates.csv",
    "author_expert_profiles.csv",
    "notable_scholar_citing_papers.csv",
]


def report_path(output: str | Path) -> Path:
    return Path(output) / REPORT_FILENAME


def empty_report_frame(sheet: str) -> pd.DataFrame:
    return pd.DataFrame(columns=REPORT_SHEETS[sheet])


def clean_frame_for_report(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = ""
    out = out.reindex(columns=columns).fillna("")
    return clean_excel_frame(out)


def load_report_sheets(output: str | Path) -> Dict[str, pd.DataFrame]:
    path = report_path(output)
    sheets = {name: empty_report_frame(name) for name in REPORT_SHEETS}
    if not path.exists():
        return sheets
    try:
        loaded = pd.read_excel(path, sheet_name=None, dtype=str).items()
    except Exception:
        return sheets
    for name, frame in loaded:
        if name in REPORT_SHEETS:
            sheets[name] = clean_frame_for_report(frame.fillna(""), REPORT_SHEETS[name])
    return sheets


def target_to_frame(target: Dict[str, Any]) -> pd.DataFrame:
    external = target.get("externalIds") or {}
    metadata = {
        "paperId": target.get("paperId", ""),
        "title": target.get("title", ""),
        "venue": target.get("venue", ""),
        "year": target.get("year", ""),
        "citationCount": target.get("citationCount", ""),
        "url": target.get("url", ""),
        "doi": external.get("DOI", ""),
        "arxiv": external.get("ArXiv", ""),
        "externalIds_json": json.dumps(external, ensure_ascii=False),
        "openAccessPdf_json": json.dumps(target.get("openAccessPdf") or {}, ensure_ascii=False),
        "target_json": json.dumps(target, ensure_ascii=False),
    }
    rows: List[Dict[str, Any]] = [
        {"record_type": "metadata", "field": key, "value": value, "author_order": "", "author_name": "", "author_id": ""}
        for key, value in metadata.items()
    ]
    for idx, author in enumerate(target.get("authors") or [], 1):
        rows.append(
            {
                "record_type": "author",
                "field": "",
                "value": "",
                "author_order": idx,
                "author_name": author.get("name", "") if isinstance(author, dict) else str(author),
                "author_id": author.get("authorId", "") if isinstance(author, dict) else "",
            }
        )
    return pd.DataFrame(rows, columns=TARGET_COLUMNS)


def frame_to_target(frame: pd.DataFrame) -> Dict[str, Any]:
    if frame.empty:
        return {}
    rows = frame.fillna("").to_dict("records")
    for row in rows:
        if row.get("record_type") == "metadata" and row.get("field") == "target_json" and row.get("value"):
            try:
                return json.loads(row["value"])
            except Exception:
                break
    target: Dict[str, Any] = {}
    external: Dict[str, Any] = {}
    for row in rows:
        if row.get("record_type") != "metadata":
            continue
        key = row.get("field", "")
        value = row.get("value", "")
        if key in {"paperId", "title", "venue", "url"}:
            target[key] = value
        elif key in {"year", "citationCount"}:
            target[key] = parse_int(value)
        elif key == "doi" and value:
            external["DOI"] = value
        elif key == "arxiv" and value:
            external["ArXiv"] = value
        elif key == "externalIds_json" and value:
            try:
                external.update(json.loads(value))
            except Exception:
                pass
        elif key == "openAccessPdf_json" and value:
            try:
                target["openAccessPdf"] = json.loads(value)
            except Exception:
                pass
    authors = []
    for row in rows:
        if row.get("record_type") == "author" and row.get("author_name"):
            authors.append({"authorId": row.get("author_id", ""), "name": row.get("author_name", "")})
    if authors:
        target["authors"] = authors
    if external:
        target["externalIds"] = external
    return target


def load_legacy_target_json(output: str | Path) -> Dict[str, Any]:
    target_path = Path(output) / "target.json"
    if not target_path.exists():
        return {}
    try:
        return json.loads(target_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_target(output: str | Path) -> Dict[str, Any]:
    target = frame_to_target(load_report_sheets(output)["target"])
    if target:
        return target
    return load_legacy_target_json(output)


def read_csv_if_exists(path: Path, columns: Sequence[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return clean_frame_for_report(pd.read_csv(path, dtype=str).fillna(""), columns)


def legacy_papers_frame(output: str | Path) -> pd.DataFrame:
    output = Path(output)
    citing = read_csv_if_exists(output / "citing_papers.csv", CITING_COLUMNS)
    if citing.empty:
        return pd.DataFrame(columns=PAPER_COLUMNS)
    papers = citing.copy()
    manifest_path = output / "download_manifest.csv"
    if manifest_path.exists():
        manifest = pd.read_csv(manifest_path, dtype=str).fillna("")
        keep = ["citing_title"] + [col for col in DOWNLOAD_COLUMNS if col in manifest.columns]
        papers = papers.merge(manifest[keep], on="citing_title", how="left")
    coverage_path = output / "citation_paper_coverage_reliable.csv"
    if coverage_path.exists():
        coverage = pd.read_csv(coverage_path, dtype=str).fillna("")
        keep = [
            "citing_title",
            "analysis_status",
            "location_count",
            "pages",
            "reference_marker",
            "reference_score",
            "reference_evidence",
            "reference_entry",
            "failure_reason",
        ]
        papers = papers.merge(coverage[[col for col in keep if col in coverage.columns]], on="citing_title", how="left")
    return clean_frame_for_report(papers, PAPER_COLUMNS)


def read_papers(output: str | Path) -> pd.DataFrame:
    sheets = load_report_sheets(output)
    if not sheets["papers"].empty:
        return sheets["papers"]
    return legacy_papers_frame(output)


def read_manual_todo(output: str | Path) -> pd.DataFrame:
    sheets = load_report_sheets(output)
    if not sheets["manual_download_todo"].empty:
        return sheets["manual_download_todo"]
    return read_csv_if_exists(Path(output) / "manual_download_todo.csv", MANUAL_COLUMNS)


def read_locations(output: str | Path) -> pd.DataFrame:
    sheets = load_report_sheets(output)
    if not sheets["citation_locations"].empty:
        return sheets["citation_locations"]
    return read_csv_if_exists(Path(output) / "citation_locations_reliable.csv", CONTEXT_COLUMNS)


def download_detail_frame(papers: pd.DataFrame, manual: pd.DataFrame, status: str) -> pd.DataFrame:
    papers = clean_frame_for_report(papers, PAPER_COLUMNS)
    manual = clean_frame_for_report(manual, MANUAL_COLUMNS)
    if papers.empty:
        return empty_report_frame("downloaded_papers" if status == "success" else "download_failures")
    has_download_data = (
        papers["download_status"].fillna("").astype(str).str.strip().ne("").any()
        if "download_status" in papers
        else False
    ) or not manual.empty
    if not has_download_data:
        return empty_report_frame("downloaded_papers" if status == "success" else "download_failures")
    manual_by_key = {
        str(row.get("dedupe_key") or row.get("citing_title") or ""): row
        for row in manual.to_dict("records")
    } if not manual.empty else {}
    rows: List[Dict[str, Any]] = []
    for row in papers.to_dict("records"):
        download_status = str(row.get("download_status") or "").strip().lower()
        key = str(row.get("dedupe_key") or row.get("citing_title") or "")
        manual_row = manual_by_key.get(key, {})
        is_success = download_status in {"downloaded", "manual"}
        if status == "success" and not is_success:
            continue
        if status == "failure" and is_success:
            continue
        if status == "failure" and not download_status and not manual_row:
            continue
        detail = {column: row.get(column, "") for column in DOWNLOAD_DETAIL_COLUMNS}
        detail["candidate_urls"] = manual_row.get("candidate_urls") or "; ".join(candidate_pdf_urls(row))
        detail["expected_pdf_path"] = manual_row.get("expected_pdf_path", "")
        detail["manual_pdf_path"] = manual_row.get("manual_pdf_path", "")
        rows.append(detail)
    return clean_frame_for_report(pd.DataFrame(rows), DOWNLOAD_DETAIL_COLUMNS)


def sync_download_detail_sheets(sheets: Dict[str, pd.DataFrame], updated_names: set[str]) -> None:
    if not {"papers", "manual_download_todo"} & updated_names:
        return
    papers = sheets.get("papers", empty_report_frame("papers"))
    manual = sheets.get("manual_download_todo", empty_report_frame("manual_download_todo"))
    if "downloaded_papers" not in updated_names:
        sheets["downloaded_papers"] = download_detail_frame(papers, manual, "success")
    if "download_failures" not in updated_names:
        sheets["download_failures"] = download_detail_frame(papers, manual, "failure")


def write_report(
    output: str | Path,
    updates: Dict[str, pd.DataFrame],
    export_legacy_csv: bool = False,
    migrate_legacy_tables: bool = True,
) -> Path:
    output = ensure_dir(output)
    sheets = load_report_sheets(output)
    updated_names: set[str] = set()
    for name, frame in updates.items():
        if name not in REPORT_SHEETS:
            continue
        updated_names.add(name)
        sheets[name] = clean_frame_for_report(frame, REPORT_SHEETS[name])
    if migrate_legacy_tables:
        if "target" not in updated_names and sheets["target"].empty:
            legacy_target = load_legacy_target_json(output)
            if legacy_target:
                sheets["target"] = target_to_frame(legacy_target)
        if "papers" not in updated_names and sheets["papers"].empty:
            legacy_papers = legacy_papers_frame(output)
            if not legacy_papers.empty:
                sheets["papers"] = legacy_papers
        if "citation_locations" not in updated_names and sheets["citation_locations"].empty:
            legacy_locations = read_csv_if_exists(Path(output) / "citation_locations_reliable.csv", CONTEXT_COLUMNS)
            if not legacy_locations.empty:
                sheets["citation_locations"] = legacy_locations
        if "manual_download_todo" not in updated_names and sheets["manual_download_todo"].empty:
            legacy_manual = read_csv_if_exists(Path(output) / "manual_download_todo.csv", MANUAL_COLUMNS)
            if not legacy_manual.empty:
                sheets["manual_download_todo"] = legacy_manual
    sync_download_detail_sheets(sheets, updated_names)
    path = report_path(output)
    with pd.ExcelWriter(path) as writer:
        for name, columns in REPORT_SHEETS.items():
            clean_frame_for_report(sheets.get(name, pd.DataFrame()), columns).to_excel(
                writer, sheet_name=name, index=False
            )
    if not export_legacy_csv:
        cleanup_legacy_tables(output)
    return path


def cleanup_legacy_tables(output: str | Path) -> None:
    for name in LEGACY_TABLE_FILES:
        path = Path(output) / name
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def export_legacy_enabled(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "export_legacy_csv", False))


def append_run_notes(output: str | Path, notes: Dict[str, Any]) -> pd.DataFrame:
    existing = load_report_sheets(output)["run_notes"]
    rows = existing.to_dict("records") if not existing.empty else []
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for key, value in notes.items():
        rows.append({"key": f"{timestamp} {key}", "value": value})
    return pd.DataFrame(rows, columns=RUN_NOTE_COLUMNS)


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
            author_details = [
                {"name": a.get("name", ""), "authorId": a.get("authorId", "")}
                for a in paper.get("authors", [])
                if a.get("name")
            ]
            authors = ", ".join(a["name"] for a in author_details if a.get("name"))
            rows.append(
                {
                    "source_platforms": "semantic-scholar",
                    "source_record_ids": f"s2:{paper_id_value}" if paper_id_value else "",
                    "citing_title": paper.get("title") or "",
                    "citing_authors": authors,
                    "citing_authors_json": json.dumps(author_details, ensure_ascii=False),
                    "citing_author_ids": ";".join(a["authorId"] for a in author_details if a.get("authorId")),
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


class ScholarCaptchaError(RuntimeError):
    pass


def scholar_driver_state(driver) -> Dict[str, str]:
    state = {"current_url": "", "page_title": "", "browser_pid": ""}
    try:
        state["current_url"] = str(driver.current_url or "")
    except Exception:
        pass
    try:
        state["page_title"] = str(driver.title or "")
    except Exception:
        pass
    try:
        process = getattr(getattr(driver, "service", None), "process", None)
        pid = getattr(process, "pid", "")
        state["browser_pid"] = str(pid or "")
    except Exception:
        pass
    return state


def append_scholar_event(events: List[Dict[str, Any]], event: str, driver=None, **extra: Any) -> None:
    row: Dict[str, Any] = {"event": event, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    if driver is not None:
        row.update(scholar_driver_state(driver))
    for key, value in extra.items():
        row[key] = value
    events.append(row)


def save_scholar_debug(driver, debug_dir: Path, label: str, events: List[Dict[str, Any]]) -> Dict[str, str]:
    ensure_dir(debug_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = safe_filename(label, 42) or "captcha"
    base = debug_dir / f"{stamp}-{safe_label}"
    html_path = base.with_suffix(".html")
    url_path = base.with_suffix(".url.txt")
    screenshot_path = base.with_suffix(".png")
    html_file = ""
    url_file = ""
    screenshot_file = ""
    state = scholar_driver_state(driver)
    try:
        html_path.write_text(str(driver.page_source or ""), encoding="utf-8")
        html_file = str(html_path)
    except Exception:
        html_file = ""
    try:
        url_path.write_text(
            "\n".join([state.get("current_url", ""), state.get("page_title", "")]),
            encoding="utf-8",
        )
        url_file = str(url_path)
    except Exception:
        url_file = ""
    try:
        driver.save_screenshot(str(screenshot_path))
        screenshot_file = str(screenshot_path)
    except Exception:
        screenshot_file = ""
    debug = {
        "debug_html": html_file,
        "debug_url": url_file,
        "debug_screenshot": screenshot_file,
    }
    append_scholar_event(events, "captcha_debug_saved", driver, **debug)
    return debug


def notify_scholar_captcha_user(driver, debug_dir: Path) -> None:
    try:
        driver.maximize_window()
        driver.switch_to.window(driver.current_window_handle)
        driver.execute_script("window.focus();")
    except Exception:
        pass
    if os.name != "nt":
        return
    message = (
        "Google Scholar needs human verification.\n\n"
        "Please switch to the visible Edge/Chrome Scholar window, complete the captcha, "
        "and leave the browser open. The script will continue automatically.\n\n"
        f"Debug files: {debug_dir}"
    )
    command = (
        "$wshell = New-Object -ComObject WScript.Shell; "
        f"$wshell.Popup({json.dumps(message)}, 0, 'Google Scholar verification needed', 64) | Out-Null"
    )
    try:
        kwargs: Dict[str, Any] = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception:
        pass


def wait_for_scholar_captcha(
    driver,
    url: str,
    captcha_action: str,
    debug_dir: Path,
    events: List[Dict[str, Any]],
    captcha_timeout: float = 600.0,
) -> bool:
    saw_captcha = False
    wait_started = 0.0
    debug_saved = False
    last_notice = 0.0
    while True:
        if not is_scholar_captcha_page(driver.page_source):
            if saw_captcha:
                append_scholar_event(events, "captcha_resolved", driver, retry_url=url)
            return saw_captcha
        saw_captcha = True
        debug: Dict[str, str] = {}
        if not debug_saved:
            debug = save_scholar_debug(driver, debug_dir, "captcha", events)
            debug_saved = True
            notify_scholar_captcha_user(driver, debug_dir)
        append_scholar_event(events, "captcha_detected", driver, retry_url=url, captcha_action=captcha_action, **debug)
        if captcha_action == "fail":
            message = (
                "Google Scholar captcha detected. Open the visible browser and complete verification, "
                "or rerun with --scholar-captcha-action wait. Debug files were saved under "
                f"{debug_dir}."
            )
            print(message, file=sys.stderr)
            raise ScholarCaptchaError(message)
        if not wait_started:
            wait_started = time.time()
            append_scholar_event(events, "captcha_wait_started", driver, retry_url=url, captcha_timeout=captcha_timeout)
            print(
                "Google Scholar captcha detected. Complete verification in the visible browser; "
                f"waiting up to {int(captcha_timeout)} seconds. No console input is required."
            )
            last_notice = wait_started
        elif time.time() - last_notice >= 30:
            append_scholar_event(events, "captcha_waiting", driver, retry_url=url)
            print("Still waiting for Google Scholar verification in the visible browser...")
            last_notice = time.time()
        if time.time() - wait_started > captcha_timeout:
            message = f"Timed out waiting for Google Scholar captcha verification. Debug files were saved under {debug_dir}."
            print(message, file=sys.stderr)
            raise ScholarCaptchaError(message)
        time.sleep(5)


def transfer_driver_cookies_to_session(driver, session: requests.Session) -> int:
    count = 0
    try:
        cookies = driver.get_cookies()
    except Exception:
        cookies = []
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        domain = str(cookie.get("domain") or ".google.com").lstrip(".")
        path = str(cookie.get("path") or "/")
        try:
            session.cookies.set(name, value, domain=domain, path=path)
            count += 1
        except Exception:
            continue
    return count


def prime_google_scholar_author_session(
    session: requests.Session,
    browser: str,
    locale: str,
    output: str | Path,
    captcha_action: str = "wait",
    captcha_timeout: float = 600.0,
    seed_query: str = "computer vision",
) -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {
        "captcha_status": "none",
        "events": [],
        "cookie_count": 0,
        "status": "not_started",
    }
    if captcha_action == "fail":
        diagnostics["status"] = "skipped_fail_mode"
        return diagnostics
    debug_dir = ensure_dir(Path(output) / "scholar_debug")
    url = "https://scholar.google.com/citations?" + urllib.parse.urlencode(
        {"view_op": "search_authors", "mauthors": seed_query or "computer vision", "hl": locale}
    )
    driver = create_webdriver(browser)
    try:
        append_scholar_event(diagnostics["events"], "author_browser_started", driver, browser=browser, locale=locale)
        driver.get(url)
        time.sleep(2)
        if wait_for_scholar_captcha(driver, url, captcha_action, debug_dir, diagnostics["events"], captcha_timeout):
            diagnostics["captcha_status"] = "resolved"
        diagnostics["cookie_count"] = transfer_driver_cookies_to_session(driver, session)
        diagnostics["status"] = "ok"
        diagnostics["final_url"] = scholar_driver_state(driver).get("current_url", "")
        diagnostics["final_title"] = scholar_driver_state(driver).get("page_title", "")
        append_scholar_event(diagnostics["events"], "author_browser_cookies_transferred", driver, cookie_count=diagnostics["cookie_count"])
        return diagnostics
    except ScholarCaptchaError as exc:
        diagnostics["captcha_status"] = "blocked"
        diagnostics["status"] = "captcha_error"
        diagnostics["error"] = str(exc)
        setattr(exc, "diagnostics", diagnostics)
        return diagnostics
    except Exception as exc:
        diagnostics["status"] = "error"
        diagnostics["error"] = str(exc)
        return diagnostics
    finally:
        append_scholar_event(diagnostics["events"], "author_browser_quit", driver)
        driver.quit()


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
        "citing_authors_json": "",
        "citing_author_ids": "",
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
    captcha_action: str = "fail",
    debug_dir: Path = Path("scholar_debug"),
    diagnostics: Optional[Dict[str, Any]] = None,
    captcha_timeout: float = 600.0,
) -> Tuple[Optional[str], bool, Optional[int]]:
    diagnostics = diagnostics if diagnostics is not None else {"events": []}
    events = diagnostics.setdefault("events", [])
    for query in google_target_queries(identifier):
        url = scholar_url(query, locale)
        append_scholar_event(events, "target_search_start", driver, query=query, requested_url=url)
        driver.get(url)
        time.sleep(random.uniform(min_delay, max_delay))
        if wait_for_scholar_captcha(driver, url, captcha_action, debug_dir, events, captcha_timeout):
            diagnostics["captcha_status"] = "resolved"
        soup = BeautifulSoup(driver.page_source, "html.parser")
        blocks = google_result_blocks(soup)
        append_scholar_event(events, "target_search_page_loaded", driver, query=query, result_blocks=len(blocks))
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
                reported_total = parse_count(parsed.get("citation_count", ""))
                diagnostics["target_found"] = True
                diagnostics["target_title"] = title
                diagnostics["target_score"] = f"{score:.3f}"
                diagnostics["target_cited_by_url"] = parsed["google_scholar_cited_by_url"]
                diagnostics["reported_cited_by_count"] = reported_total or ""
                append_scholar_event(
                    events,
                    "target_found_with_cited_by",
                    driver,
                    target_title=title,
                    target_score=f"{score:.3f}",
                    cited_by_url=parsed["google_scholar_cited_by_url"],
                    reported_cited_by_count=reported_total or "",
                )
                return parsed["google_scholar_cited_by_url"], True, parse_count(parsed.get("citation_count", ""))
            if score >= 0.75 or is_doi(identifier):
                print(f"Google Scholar target candidate has no Cited by link (score={score:.2f}): {title}")
                diagnostics["target_found"] = True
                diagnostics["target_title"] = title
                diagnostics["target_score"] = f"{score:.3f}"
                diagnostics["target_cited_by_url"] = ""
                diagnostics["reported_cited_by_count"] = ""
                append_scholar_event(
                    events,
                    "target_found_without_cited_by",
                    driver,
                    target_title=title,
                    target_score=f"{score:.3f}",
                )
                return None, True, None
    diagnostics["target_found"] = False
    append_scholar_event(events, "target_not_found", driver)
    return None, False, None


def google_scrape_citing(
    identifier: str,
    limit: int,
    browser: str,
    min_delay: float,
    max_delay: float,
    locale: str = "zh-CN",
    output: str | Path = ".",
    captcha_action: str = "wait",
    captcha_timeout: float = 600.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    diagnostics: Dict[str, Any] = {
        "browser": browser,
        "locale": locale,
        "captcha_action": captcha_action,
        "captcha_status": "none",
        "events": [],
    }
    debug_dir = ensure_dir(Path(output) / "scholar_debug")
    driver = create_webdriver(browser)
    try:
        append_scholar_event(diagnostics["events"], "browser_started", driver, browser=browser, locale=locale)
        diagnostics["browser_pid"] = scholar_driver_state(driver).get("browser_pid", "")
        current_url, target_found, reported_total = google_cited_by_url(
            driver,
            identifier,
            min_delay,
            max_delay,
            locale,
            captcha_action,
            debug_dir,
            diagnostics,
            captcha_timeout,
        )
        if not target_found:
            raise RuntimeError("Could not find a matching target paper on Google Scholar.")
        if not current_url:
            print("Google Scholar target found with no citing papers.")
            diagnostics["rows"] = 0
            diagnostics["final_url"] = scholar_driver_state(driver).get("current_url", "")
            diagnostics["final_title"] = scholar_driver_state(driver).get("page_title", "")
            append_scholar_event(diagnostics["events"], "scrape_finished", driver, rows=0, reported_cited_by_count=reported_total or "")
            return [], diagnostics
        rows: List[Dict[str, Any]] = []
        seen_urls = set()
        empty_pages = 0
        target_total = min(limit, reported_total) if reported_total else limit
        append_scholar_event(
            diagnostics["events"],
            "enter_cited_by",
            driver,
            cited_by_url=current_url,
            reported_cited_by_count=reported_total or "",
            target_total=target_total,
        )
        while current_url and len(rows) < target_total:
            normalized_url = normalize_scholar_results_url(current_url) or current_url
            if normalized_url in seen_urls:
                print(f"Stopping Google Scholar pagination loop: {normalized_url}")
                break
            seen_urls.add(normalized_url)
            append_scholar_event(
                diagnostics["events"],
                "cited_by_page_start",
                driver,
                requested_url=current_url,
                start=scholar_start(current_url),
                rows_so_far=len(rows),
            )
            driver.get(current_url)
            time.sleep(random.uniform(min_delay, max_delay))
            if wait_for_scholar_captcha(driver, current_url, captcha_action, debug_dir, diagnostics["events"], captcha_timeout):
                diagnostics["captcha_status"] = "resolved"
            soup = BeautifulSoup(driver.page_source, "html.parser")
            blocks = google_result_blocks(soup)
            append_scholar_event(
                diagnostics["events"],
                "cited_by_page_loaded",
                driver,
                start=scholar_start(driver.current_url or current_url),
                result_blocks=len(blocks),
                rows_so_far=len(rows),
            )
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
        diagnostics["rows"] = len(rows)
        diagnostics["reported_cited_by_count"] = reported_total or diagnostics.get("reported_cited_by_count", "")
        diagnostics["final_url"] = scholar_driver_state(driver).get("current_url", "")
        diagnostics["final_title"] = scholar_driver_state(driver).get("page_title", "")
        append_scholar_event(
            diagnostics["events"],
            "scrape_finished",
            driver,
            rows=len(rows),
            reported_cited_by_count=reported_total or "",
        )
        return rows, diagnostics
    except ScholarCaptchaError as exc:
        diagnostics["captcha_status"] = "blocked"
        partial_rows = locals().get("rows", []) if "rows" in locals() else []
        diagnostics["rows"] = len(partial_rows)
        diagnostics["final_url"] = scholar_driver_state(driver).get("current_url", "")
        diagnostics["final_title"] = scholar_driver_state(driver).get("page_title", "")
        append_scholar_event(diagnostics["events"], "scrape_blocked_by_captcha", driver, rows=len(partial_rows))
        if partial_rows:
            diagnostics["status"] = "partial_captcha_blocked"
            diagnostics["partial_failure"] = str(exc)
            append_scholar_event(diagnostics["events"], "scrape_finished_partial", driver, rows=len(partial_rows), reason="captcha_blocked")
            return partial_rows, diagnostics
        setattr(exc, "diagnostics", diagnostics)
        raise
    except Exception as exc:
        partial_rows = locals().get("rows", []) if "rows" in locals() else []
        diagnostics["rows"] = len(partial_rows)
        diagnostics["final_url"] = scholar_driver_state(driver).get("current_url", "")
        diagnostics["final_title"] = scholar_driver_state(driver).get("page_title", "")
        append_scholar_event(diagnostics["events"], "scrape_failed", driver, rows=len(partial_rows), error=str(exc))
        if partial_rows:
            diagnostics["status"] = "partial_error"
            diagnostics["partial_failure"] = str(exc)
            append_scholar_event(diagnostics["events"], "scrape_finished_partial", driver, rows=len(partial_rows), reason="connection_or_pagination_error")
            return partial_rows, diagnostics
        setattr(exc, "diagnostics", diagnostics)
        raise
    finally:
        append_scholar_event(diagnostics["events"], "browser_quit", driver)
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


def fetch_find_platform(
    platform: str,
    paper: str,
    max_papers: int,
    browser: str,
    min_delay: float,
    max_delay: float,
    scholar_locale: str,
    api_key: str,
    output: str | Path,
    scholar_captcha_action: str,
    scholar_captcha_timeout: float,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    if platform == "semantic-scholar":
        session = make_session()
        target = s2_resolve_paper(session, paper, api_key)
        rows = s2_fetch_citations(session, target, max_papers, api_key)
        return platform, target, rows, {"rows": len(rows), "status": "ok"}
    if platform == "google-scholar":
        rows, diagnostics = google_scrape_citing(
            paper,
            max_papers,
            browser,
            min_delay,
            max_delay,
            scholar_locale,
            output,
            scholar_captcha_action,
            scholar_captcha_timeout,
        )
        return platform, {}, rows, diagnostics
    raise RuntimeError(f"Unsupported platform: {platform}")


def cmd_find(args: argparse.Namespace) -> Tuple[Path, Path]:
    output = ensure_dir(args.output)
    api_key = args.s2_api_key or os.environ.get(args.s2_api_key_env or "SEMANTIC_SCHOLAR_API_KEY", "")
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    target: Dict[str, Any] = {"title": args.paper}
    records: List[Dict[str, Any]] = []
    platform_errors: List[Dict[str, str]] = []
    platform_stats: Dict[str, Dict[str, Any]] = {}
    platform_record_counts: Dict[str, int] = {}
    find_workers = max(1, numeric_arg(args, "find_workers", 2, int))
    scholar_captcha_action = getattr(args, "scholar_captcha_action", "wait") or "wait"
    scholar_captcha_timeout = numeric_arg(args, "scholar_captcha_timeout", 600.0, float)
    require_google_scholar = bool(getattr(args, "require_google_scholar", False))

    def handle_result(platform: str, platform_target: Dict[str, Any], platform_records: List[Dict[str, Any]], diagnostics: Dict[str, Any]) -> None:
        nonlocal target
        if platform_target:
            target = platform_target
        records.extend(platform_records)
        platform_record_counts[platform] = len(platform_records)
        platform_stats[platform] = diagnostics or {"rows": len(platform_records)}

    if find_workers > 1 and len(platforms) > 1:
        with ThreadPoolExecutor(max_workers=min(find_workers, len(platforms))) as executor:
            futures = {
                executor.submit(
                    fetch_find_platform,
                    platform,
                    args.paper,
                    args.max_papers,
                    args.browser,
                    args.min_delay,
                    args.max_delay,
                    args.scholar_locale,
                    api_key,
                    output,
                    scholar_captcha_action,
                    scholar_captcha_timeout,
                ): platform
                for platform in platforms
            }
            for future in as_completed(futures):
                platform = futures[future]
                try:
                    handle_result(*future.result())
                except Exception as exc:
                    message = str(exc)
                    diagnostics = getattr(exc, "diagnostics", {}) or {}
                    if diagnostics:
                        platform_stats[platform] = diagnostics
                        platform_record_counts[platform] = parse_int(diagnostics.get("rows"))
                    platform_errors.append({"platform": platform, "error": message})
                    print(f"{platform} failed, continuing with other platforms: {message}", file=sys.stderr)
    else:
        for platform in platforms:
            try:
                handle_result(
                    *fetch_find_platform(
                        platform,
                        args.paper,
                        args.max_papers,
                        args.browser,
                        args.min_delay,
                        args.max_delay,
                        args.scholar_locale,
                        api_key,
                        output,
                        scholar_captcha_action,
                        scholar_captcha_timeout,
                    )
                )
            except Exception as exc:
                message = str(exc)
                diagnostics = getattr(exc, "diagnostics", {}) or {}
                if diagnostics:
                    platform_stats[platform] = diagnostics
                    platform_record_counts[platform] = parse_int(diagnostics.get("rows"))
                platform_errors.append({"platform": platform, "error": message})
                print(f"{platform} failed, continuing with other platforms: {message}", file=sys.stderr)

    if platform_errors:
        target["platform_errors"] = platform_errors
    hard_platform_failure = bool(not records and platform_errors)

    rows = merge_records(records)
    google_rows = sum(1 for row in rows if row_has_platform(row, "google-scholar"))
    semantic_rows = sum(1 for row in rows if row_has_platform(row, "semantic-scholar"))
    target_path = output / "target.json"
    citing_path = output / "citing_papers.csv"
    papers = clean_frame_for_report(pd.DataFrame(rows), PAPER_COLUMNS)
    google_stats = platform_stats.get("google-scholar", {})
    note_payload: Dict[str, Any] = {
        "find.paper": args.paper,
        "find.platforms": ",".join(platforms),
        "find.rows": len(rows),
        "find.max_papers": args.max_papers,
        "find.workers": find_workers,
        "find.require_google_scholar": require_google_scholar,
        "find.scholar_captcha_action": scholar_captcha_action,
        "find.scholar_captcha_timeout": scholar_captcha_timeout,
        "find.google_scholar.attempted": "google-scholar" in platforms,
        "find.google_scholar_attempted": "google-scholar" in platforms,
        "find.google_scholar.rows": google_rows,
        "find.semantic_scholar.rows": semantic_rows,
        "find.platform_record_counts_json": json.dumps(platform_record_counts, ensure_ascii=False),
    }
    if platform_errors:
        note_payload["find.platform_errors_json"] = json.dumps(platform_errors, ensure_ascii=False)
    if google_stats:
        note_payload.update(
            {
                "find.google_scholar.raw_rows": google_stats.get("rows", ""),
                "find.google_scholar.status": google_stats.get("status", ""),
                "find.google_scholar.partial_failure": google_stats.get("partial_failure", ""),
                "find.google_scholar.captcha_status": google_stats.get("captcha_status", ""),
                "find.google_scholar.browser_pid": google_stats.get("browser_pid", ""),
                "find.google_scholar.reported_cited_by_count": google_stats.get("reported_cited_by_count", ""),
                "find.google_scholar.target_found": google_stats.get("target_found", ""),
                "find.google_scholar.target_title": google_stats.get("target_title", ""),
                "find.google_scholar.target_cited_by_url": google_stats.get("target_cited_by_url", ""),
                "find.google_scholar.current_url": google_stats.get("final_url", ""),
                "find.google_scholar.page_title": google_stats.get("final_title", ""),
                "find.google_scholar.events_json": json.dumps(google_stats.get("events", []), ensure_ascii=False),
            }
        )
    require_google_failure = "google-scholar" in platforms and require_google_scholar and google_rows == 0
    if hard_platform_failure:
        note_payload["find.status"] = "failed_all_platforms"
    elif require_google_failure:
        note_payload["find.status"] = "failed_require_google_scholar"
        note_payload["find.require_google_scholar_failure"] = "no_google_scholar_rows_collected"
    else:
        note_payload["find.status"] = "ok"
    notes = append_run_notes(
        output,
        note_payload,
    )
    report = write_report(
        output,
        {
            "target": target_to_frame(target),
            "papers": papers,
            "paper_authors": empty_report_frame("paper_authors"),
            "authors": empty_report_frame("authors"),
            "citation_locations": empty_report_frame("citation_locations"),
            "downloaded_papers": empty_report_frame("downloaded_papers"),
            "download_failures": empty_report_frame("download_failures"),
            "manual_download_todo": empty_report_frame("manual_download_todo"),
            "notable_citations": empty_report_frame("notable_citations"),
            "run_notes": notes,
        },
        export_legacy_csv=export_legacy_enabled(args),
        migrate_legacy_tables=False,
    )
    if require_google_failure:
        raise RuntimeError(
            "Google Scholar was required but no Google Scholar citing rows were collected. "
            f"Check {output / 'scholar_debug'} and the run_notes sheet for captcha/status details."
        )
    if hard_platform_failure:
        raise RuntimeError("; ".join(f"{item['platform']}: {item['error']}" for item in platform_errors))
    if export_legacy_enabled(args):
        write_json(target_path, target)
        write_csv(citing_path, rows, CITING_COLUMNS)
    print(f"Saved citation report: {report} ({len(rows)} papers)")
    return target_path, citing_path


def parse_author_json(value: Any) -> List[Dict[str, str]]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out = []
    for item in payload:
        if isinstance(item, dict) and item.get("name"):
            out.append({"name": str(item.get("name") or ""), "authorId": str(item.get("authorId") or "")})
    return out


def parse_google_author_names(value: Any) -> List[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text.lower() == "nan":
        return []
    head = re.split(r"\s[-\u2010-\u2015]\s", text, maxsplit=1)[0]
    head = re.sub(r"\b(?:19|20)\d{2}\b.*$", "", head).strip(" ,;")
    names = []
    for raw in re.split(r",|;", head):
        name = re.sub(r"\s+", " ", raw).strip(" .,\u2026")
        if not name or len(name) > 80:
            continue
        if re.search(r"\b(journal|conference|proceedings|transactions|arxiv|springer|elsevier)\b", name, re.I):
            continue
        names.append(name)
    return names[:12]


def normalized_author_name(name: str) -> str:
    return normalize_text(name)


def author_entries_for_row(row: Dict[str, Any]) -> List[Dict[str, str]]:
    entries = parse_author_json(row.get("citing_authors_json"))
    if entries:
        return entries
    return [{"name": name, "authorId": ""} for name in parse_google_author_names(row.get("citing_authors"))]


def collect_author_candidates_from_papers(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], pd.DataFrame]:
    df = clean_frame_for_report(df, PAPER_COLUMNS)
    parsed_rows: List[Tuple[Dict[str, Any], List[Dict[str, str]]]] = []
    name_to_id_key: Dict[str, str] = {}
    for row in df.to_dict("records"):
        entries = author_entries_for_row(row)
        parsed_rows.append((row, entries))
        for entry in entries:
            name_norm = normalized_author_name(entry.get("name", ""))
            author_id = str(entry.get("authorId") or "").strip()
            if name_norm and author_id:
                name_to_id_key.setdefault(name_norm, f"s2:{author_id}")

    candidates: Dict[str, Dict[str, Any]] = {}
    for row, entries in parsed_rows:
        for order, entry in enumerate(entries, 1):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            name_norm = normalized_author_name(name)
            author_id = str(entry.get("authorId") or "").strip()
            key = f"s2:{author_id}" if author_id else name_to_id_key.get(name_norm, f"name:{name_norm}")
            item = candidates.setdefault(
                key,
                {
                    "author_key": key,
                    "name": name,
                    "normalized_name": name_norm,
                    "semantic_author_id": author_id if author_id else "",
                    "papers": [],
                },
            )
            if author_id and not item.get("semantic_author_id"):
                item["semantic_author_id"] = author_id
            if len(name) > len(str(item.get("name") or "")):
                item["name"] = name
            item["papers"].append(
                {
                    "citing_title": row.get("citing_title", ""),
                    "publication_year": row.get("publication_year", ""),
                    "venue": row.get("venue", ""),
                    "source_platforms": row.get("source_platforms", ""),
                    "citation_count": citation_count_or_zero(row.get("citation_count", "")),
                    "dedupe_key": row.get("dedupe_key", ""),
                    "author_order": order,
                }
            )
    for item in candidates.values():
        paper_counts = [parse_int(paper.get("citation_count")) for paper in item.get("papers", [])]
        item["citing_paper_count"] = len(item.get("papers", []))
        item["max_citing_paper_citation_count"] = max(paper_counts) if paper_counts else 0
        item["sum_citing_paper_citation_count"] = sum(paper_counts)
    return list(candidates.values()), df


def collect_author_candidates(citing_path: Path) -> Tuple[List[Dict[str, Any]], pd.DataFrame]:
    df = pd.read_csv(citing_path, dtype=str).fillna("")
    return collect_author_candidates_from_papers(df)


def load_cache(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(path: Path, payload: Dict[str, Any]) -> None:
    write_json(path, payload)


def parse_int(value: Any) -> int:
    text = re.sub(r"[^\d]", "", str(value or ""))
    return int(text) if text else 0


def prepare_author_profile_cache(cache: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if "google_scholar" in cache or "semantic_scholar" in cache:
        return {
            "google_scholar": cache.setdefault("google_scholar", {}),
            "semantic_scholar": cache.setdefault("semantic_scholar", {}),
        }
    if cache:
        return {"google_scholar": dict(cache), "semantic_scholar": {}}
    return {"google_scholar": {}, "semantic_scholar": {}}


def author_metric_cache_key(candidate: Dict[str, Any], name: str = "") -> str:
    author_id = str(candidate.get("semantic_author_id") or "").strip()
    if author_id:
        return f"s2:{author_id}"
    normalized = str(candidate.get("normalized_name") or normalized_author_name(name or candidate.get("name", "")))
    return f"name:{normalized}"


def author_profile_priority(candidate: Dict[str, Any]) -> Tuple[int, int, int, int]:
    return (
        1 if candidate.get("semantic_author_id") else 0,
        parse_int(candidate.get("max_citing_paper_citation_count")),
        parse_int(candidate.get("sum_citing_paper_citation_count")),
        parse_int(candidate.get("citing_paper_count")),
    )


def numeric_arg(args: argparse.Namespace, name: str, default: int | float, cast):
    value = getattr(args, name, None)
    if value is None or value == "":
        return default
    return cast(value)


def s2_author_metrics(session: requests.Session, author_id: str, name: str, api_key: str = "") -> Dict[str, Any]:
    fields = "name,citationCount,hIndex,paperCount,affiliations,url,homepage"
    try:
        if author_id:
            response = s2_get(
                session,
                f"https://api.semanticscholar.org/graph/v1/author/{author_id}",
                {"fields": fields},
                api_key,
                timeout=30,
            )
            if response.ok:
                return response.json()
            return {"error": s2_error_message(response, "author lookup")}
        if name:
            response = s2_get(
                session,
                "https://api.semanticscholar.org/graph/v1/author/search",
                {"query": name, "limit": 5, "fields": fields},
                api_key,
                timeout=30,
            )
            if response.ok:
                candidates = response.json().get("data", [])
                exact = [
                    item for item in candidates
                    if normalized_author_name(item.get("name", "")) == normalized_author_name(name)
                ]
                pool = exact or candidates
                if pool:
                    return max(pool, key=lambda item: parse_int(item.get("citationCount")))
            return {"error": s2_error_message(response, "author search")}
    except Exception as exc:
        return {"error": str(exc)}
    return {}


def fetch_s2_author_metric(cache_key: str, candidate: Dict[str, Any], api_key: str = "") -> Tuple[str, Dict[str, Any]]:
    session = make_session()
    return cache_key, s2_author_metrics(session, candidate.get("semantic_author_id", ""), candidate.get("name", ""), api_key)


def google_author_candidates_from_soup(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    candidates = []
    for block in soup.select(".gs_ai_chpr"):
        name_tag = block.select_one(".gs_ai_name a") or block.select_one(".gs_ai_name")
        if not name_tag:
            continue
        profile_name = name_tag.get_text(" ", strip=True)
        href = name_tag.get("href", "") if name_tag.name == "a" else ""
        profile_url = urllib.parse.urljoin("https://scholar.google.com", href)
        cited_text = block.get_text(" ", strip=True)
        cited_match = CITED_BY_RE.search(cited_text)
        affiliation_tag = block.select_one(".gs_ai_aff")
        affiliation = affiliation_tag.get_text(" ", strip=True) if affiliation_tag else ""
        interests = [
            item.get_text(" ", strip=True)
            for item in block.select(".gs_ai_one_int")
            if item.get_text(" ", strip=True)
        ]
        user = scholar_query_value(profile_url, "user")
        candidates.append(
            {
                "name": profile_name,
                "profile_url": profile_url,
                "user": user,
                "citations": parse_int(cited_match.group(1) if cited_match else ""),
                "affiliation": affiliation,
                "interests": "; ".join(interests),
                "raw_text": cited_text,
            }
        )
    return candidates


def google_author_search(session: requests.Session, name: str, locale: str) -> List[Dict[str, Any]]:
    response = session.get(
        "https://scholar.google.com/citations",
        params={"view_op": "search_authors", "mauthors": name, "hl": locale},
        timeout=GOOGLE_AUTHOR_TIMEOUT,
    )
    if is_scholar_captcha_page(response.text):
        raise RuntimeError("google_scholar_author_captcha_or_blocked")
    return google_author_candidates_from_soup(BeautifulSoup(response.text, "html.parser"))


def google_profile_header_details(soup: BeautifulSoup) -> Dict[str, str]:
    header = soup.select_one("#gsc_prf_i") or soup
    homepage_url = ""
    for link in header.select("a[href]"):
        href = urllib.parse.urljoin("https://scholar.google.com", link.get("href", ""))
        text = link.get_text(" ", strip=True)
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc and parsed.netloc != "scholar.google.com" and (
            re.search(r"\b(homepage|home page|website|personal|lab)\b", text, re.I)
            or re.search(r"\b(edu|ac\.|university|college|institute|lab)\b", parsed.netloc, re.I)
        ):
            homepage_url = href
            break
    affiliation = ""
    affiliation_tag = header.select_one(".gsc_prf_il")
    if affiliation_tag:
        affiliation = affiliation_tag.get_text(" ", strip=True)
    verified_email = ""
    for block in header.select(".gsc_prf_il"):
        text = block.get_text(" ", strip=True)
        if "verified email" in text.lower():
            verified_email = text
            break
    interests = [
        item.get_text(" ", strip=True)
        for item in header.select(".gsc_prf_ila")
        if item.get_text(" ", strip=True)
    ]
    return {
        "homepage_url": homepage_url,
        "verified_email": verified_email,
        "affiliation": affiliation,
        "interests": "; ".join(interests),
    }


def profile_soup_mentions_paper(soup: BeautifulSoup, candidate: Dict[str, Any], titles: Sequence[str]) -> bool:
    details = google_profile_header_details(soup)
    for key, value in details.items():
        if value and not candidate.get(key):
            candidate[key] = value
    text = normalize_text(soup.get_text(" ", strip=True))
    for title in titles:
        title_norm = normalize_text(title)
        if title_norm and (title_norm in text or token_overlap(title, text) >= 0.75):
            return True
    return False


def google_profile_mentions_paper(session: requests.Session, candidate: Dict[str, Any], titles: Sequence[str], locale: str) -> bool:
    user = candidate.get("user")
    if not user:
        return False
    response = session.get(
        "https://scholar.google.com/citations",
        params={"user": user, "hl": locale, "pagesize": 100, "view_op": "list_works", "sortby": "pubdate"},
        timeout=GOOGLE_AUTHOR_TIMEOUT,
    )
    if is_scholar_captcha_page(response.text):
        raise RuntimeError("google_scholar_author_captcha_or_blocked")
    return profile_soup_mentions_paper(BeautifulSoup(response.text, "html.parser"), candidate, titles)


def author_name_match_status(query_name: str, profile_name: str) -> str:
    query_norm = normalized_author_name(query_name)
    profile_norm = normalized_author_name(profile_name)
    if query_norm and query_norm == profile_norm:
        return "exact_name"
    query_parts = query_norm.split()
    profile_parts = profile_norm.split()
    if len(query_parts) >= 2 and len(profile_parts) >= 2 and query_parts[-1] == profile_parts[-1]:
        query_initials = [part[0] for part in query_parts[:-1] if part]
        profile_initials = [part[0] for part in profile_parts[:-1] if part]
        if query_initials and profile_initials[: len(query_initials)] == query_initials:
            return "initial_name"
    return ""


def scholar_author_profile_url(profile_url: str, locale: str) -> str:
    user = scholar_query_value(profile_url, "user")
    if not user:
        return profile_url
    return "https://scholar.google.com/citations?" + urllib.parse.urlencode(
        {"user": user, "hl": locale, "pagesize": 100, "view_op": "list_works", "sortby": "pubdate"}
    )


def google_author_metrics_selenium(
    driver,
    name: str,
    titles: Sequence[str],
    locale: str,
    min_delay: float,
    max_delay: float,
    debug_dir: Path,
    captcha_action: str,
    captcha_timeout: float,
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        url = "https://scholar.google.com/citations?" + urllib.parse.urlencode(
            {"view_op": "search_authors", "mauthors": name, "hl": locale}
        )
        append_scholar_event(events, "author_search_start", driver, author=name, requested_url=url)
        driver.get(url)
        time.sleep(random.uniform(min_delay, max_delay))
        if wait_for_scholar_captcha(driver, url, captcha_action, debug_dir, events, captcha_timeout):
            append_scholar_event(events, "author_search_captcha_resolved", driver, author=name)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        candidates = google_author_candidates_from_soup(soup)
        append_scholar_event(events, "author_search_loaded", driver, author=name, candidates=len(candidates))
        matches: List[Tuple[str, Dict[str, Any]]] = []
        for item in candidates:
            status = author_name_match_status(name, item.get("name", ""))
            if status:
                matches.append((status, item))
        if not matches:
            return {"match_status": "not_found", "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION}
        for status, candidate in matches:
            profile_url = scholar_author_profile_url(candidate.get("profile_url", ""), locale)
            if not profile_url:
                continue
            append_scholar_event(events, "author_profile_start", driver, author=name, profile_name=candidate.get("name", ""), profile_url=profile_url)
            driver.get(profile_url)
            time.sleep(random.uniform(min_delay, max_delay))
            if wait_for_scholar_captcha(driver, profile_url, captcha_action, debug_dir, events, captcha_timeout):
                append_scholar_event(events, "author_profile_captcha_resolved", driver, author=name, profile_name=candidate.get("name", ""))
            profile_soup = BeautifulSoup(driver.page_source, "html.parser")
            if profile_soup_mentions_paper(profile_soup, candidate, titles):
                candidate["match_status"] = f"{status}_paper_match"
                candidate["enrichment_version"] = GOOGLE_AUTHOR_ENRICHMENT_VERSION
                return candidate
        return {
            "match_status": f"{matches[0][0]}_low_confidence" if len(matches) == 1 else "ambiguous",
            "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION,
        }
    except ScholarCaptchaError:
        raise
    except Exception as exc:
        return {"match_status": "error", "error": str(exc), "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION}


def google_author_metrics(
    session: requests.Session,
    name: str,
    titles: Sequence[str],
    locale: str,
    min_delay: float,
    max_delay: float,
) -> Dict[str, Any]:
    try:
        candidates = google_author_search(session, name, locale)
        exact = [item for item in candidates if normalized_author_name(item.get("name", "")) == normalized_author_name(name)]
        if not exact:
            return {"match_status": "not_found", "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION}
        for candidate in exact:
            time.sleep(random.uniform(min_delay, max_delay))
            if google_profile_mentions_paper(session, candidate, titles, locale):
                candidate["match_status"] = "exact_name_paper_match"
                candidate["enrichment_version"] = GOOGLE_AUTHOR_ENRICHMENT_VERSION
                return candidate
        return {
            "match_status": "exact_name_low_confidence" if len(exact) == 1 else "ambiguous",
            "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION,
        }
    except Exception as exc:
        return {"match_status": "error", "error": str(exc), "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION}


def google_author_metrics_with_interactive_retry(
    session: requests.Session,
    candidate: Dict[str, Any],
    locale: str,
    min_delay: float,
    max_delay: float,
    output: str | Path,
    browser: str,
    captcha_action: str,
    captcha_timeout: float,
    retry_events: List[Dict[str, Any]],
    max_captcha_retries: int = 3,
) -> Dict[str, Any]:
    name = candidate["name"]
    titles = [paper["citing_title"] for paper in candidate.get("papers", []) if paper.get("citing_title")]
    gs = google_author_metrics(session, name, titles, locale, min_delay, max_delay)
    error_text = str(gs.get("error") or "")
    if (
        gs.get("match_status") == "error"
        and "google_scholar_author_captcha_or_blocked" in error_text
        and captcha_action == "wait"
        and len(retry_events) < max_captcha_retries
    ):
        print(
            "Google Scholar author profile query hit captcha/block. "
            f"Opening a visible browser for manual verification: {name}",
            file=sys.stderr,
        )
        diagnostics = prime_google_scholar_author_session(
            session,
            browser,
            locale,
            output,
            captcha_action,
            captcha_timeout,
            seed_query=name,
        )
        retry_events.append(
            {
                "author": name,
                "status": diagnostics.get("status", ""),
                "captcha_status": diagnostics.get("captcha_status", ""),
                "cookie_count": diagnostics.get("cookie_count", ""),
                "final_url": diagnostics.get("final_url", ""),
                "final_title": diagnostics.get("final_title", ""),
            }
        )
        if diagnostics.get("status") == "ok":
            time.sleep(random.uniform(min_delay, max_delay))
            gs = google_author_metrics(session, name, titles, locale, min_delay, max_delay)
    return gs


EXPERT_EVIDENCE_RE = re.compile(
    r"\b(Fellow|Fellowship|IEEE|ACM|AAAI|AAAS|IAPR|SPIE|ACM Fellow|IEEE Fellow|AAAI Fellow|"
    r"Academy|National Academy|Royal Society|Royal Academy|Academia Europaea|Academician|"
    r"Turing Award|Gödel Prize|Fields Medal|Highly Cited Researcher|"
    r"editor-?in-?chief|editorial board|editor|program chair|general chair|professor|"
    r"chair|chairman|chairperson|dean|director|"
    r"award|recipient|prize|medal|laureate|distinguished|named professor|endowed chair|"
    r"chair professor|president|vice president|founder|member|associate editor|"
    r"chief scientist|principal scientist)\b",
    re.I,
)

HONOR_RE = re.compile(
    r"\b(Fellow|Fellowship|IEEE Fellow|ACM Fellow|AAAI Fellow|AAAS Fellow|IAPR Fellow|SPIE Fellow|"
    r"National Academy|Academy of Sciences|Academy of Engineering|Royal Society|Royal Academy|"
    r"Academia Europaea|Academician|Turing Award|Gödel Prize|Fields Medal|award|prize|medal|"
    r"laureate|recipient|distinguished|honou?red|highly cited researcher)\b",
    re.I,
)

TITLE_RE = re.compile(
    r"\b(professor|associate professor|assistant professor|distinguished professor|emeritus professor|"
    r"chair professor|named professor|endowed chair|research professor|scientist|chief scientist|"
    r"principal scientist|researcher|faculty|lecturer|dean|director)\b",
    re.I,
)

LEADERSHIP_RE = re.compile(
    r"\b(editor-?in-?chief|associate editor|editorial board|chair|chairman|chairperson|president|"
    r"vice president|dean|director|head of|founder|co-?founder|program chair|general chair|editor)\b",
    re.I,
)

MEMBERSHIP_RE = re.compile(
    r"\b(member of|fellow of|IEEE|ACM|AAAI|AAAS|IAPR|SPIE|Academy|Society|Association)\b",
    re.I,
)

ACADEMIC_HINT_RE = re.compile(
    r"\b(computer scientist|scientist|professor|engineer|researcher|academic|scholar|faculty|"
    r"university|laboratory|institute)\b",
    re.I,
)

EDUCATION_BACKGROUND_RE = re.compile(
    r"\b(Ph\.?D\.?|doctorate|doctoral|M\.?S\.?|MSc|master'?s|B\.?S\.?|BSc|bachelor'?s|"
    r"degree|graduated|education|educated at|alumnus|alumna|postdoctoral|postdoc)\b",
    re.I,
)

IDENTITY_STOPWORDS = {
    "and",
    "at",
    "by",
    "center",
    "centre",
    "college",
    "department",
    "for",
    "group",
    "in",
    "inc",
    "institute",
    "lab",
    "laboratory",
    "labs",
    "of",
    "research",
    "school",
    "science",
    "technology",
    "the",
    "university",
}

WIKIDATA_EVIDENCE_PROPERTIES = {
    "P39": "position held",
    "P69": "educated at",
    "P101": "field of work",
    "P106": "occupation",
    "P108": "employer",
    "P1416": "affiliation",
    "P166": "award received",
    "P463": "member of",
}

WIKIDATA_PROFILE_PROPERTIES = {
    **WIKIDATA_EVIDENCE_PROPERTIES,
    "P184": "doctoral advisor",
    "P185": "doctoral student",
    "P551": "residence",
    "P800": "notable work",
    "P1026": "academic thesis",
    "P1082": "population",
    "P1128": "employees",
    "P1412": "languages spoken",
    "P1598": "consecrator",
    "P802": "student",
    "P937": "work location",
    "P2868": "subject has role",
}

CLAIM_CATEGORY_BY_PROP = {
    "P39": "leadership_roles",
    "P106": "academic_titles",
    "P108": "academic_titles",
    "P1416": "academic_titles",
    "P166": "honors_awards",
    "P463": "professional_memberships",
}

ACADEMIC_OCCUPATION_TERMS = {
    "academic",
    "researcher",
    "scientist",
    "computer scientist",
    "engineer",
    "professor",
    "university teacher",
    "teacher",
    "scholar",
    "mathematician",
    "physicist",
}


def append_unique(items: List[str], value: Any, limit: int = 12) -> None:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ;,")
    if not text:
        return
    existing = {normalize_text(item) for item in items}
    key = normalize_text(text)
    if key and key not in existing and len(items) < limit:
        items.append(text)


def split_evidence_parts(text: str) -> List[str]:
    return [
        part.strip(" ;")
        for part in re.split(r"\s+\|\s+|;", str(text or ""))
        if part.strip(" ;")
    ]


def classify_profile_evidence(parts: Sequence[str]) -> Dict[str, str]:
    buckets = {
        "academic_titles": [],
        "honors_awards": [],
        "professional_memberships": [],
        "leadership_roles": [],
    }
    for part in parts:
        if HONOR_RE.search(part):
            append_unique(buckets["honors_awards"], part)
        if LEADERSHIP_RE.search(part):
            append_unique(buckets["leadership_roles"], part)
        if MEMBERSHIP_RE.search(part):
            append_unique(buckets["professional_memberships"], part)
        if TITLE_RE.search(part) or ACADEMIC_HINT_RE.search(part):
            append_unique(buckets["academic_titles"], part)
    return {key: " | ".join(values) for key, values in buckets.items()}


def profile_evidence_summary(fields: Dict[str, str]) -> str:
    labels = [
        ("academic_titles", "titles"),
        ("honors_awards", "honors"),
        ("professional_memberships", "memberships"),
        ("leadership_roles", "roles"),
    ]
    return " | ".join(f"{label}: {fields.get(key)}" for key, label in labels if fields.get(key))


def evidence_snippets(text: str, max_snippets: int = 4, radius: int = 95) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return ""
    snippets: List[str] = []
    seen: set[str] = set()
    for match in EXPERT_EVIDENCE_RE.finditer(cleaned):
        start = max(0, match.start() - radius)
        end = min(len(cleaned), match.end() + radius)
        snippet = cleaned[start:end].strip(" ,.;")
        if start > 0:
            snippet = "..." + snippet
        if end < len(cleaned):
            snippet = snippet + "..."
        key = normalize_text(snippet)
        if key and key not in seen:
            snippets.append(snippet)
            seen.add(key)
        if len(snippets) >= max_snippets:
            break
    return " | ".join(snippets)


def evidence_terms(text: str) -> str:
    terms = sorted({match.group(0) for match in EXPERT_EVIDENCE_RE.finditer(str(text or ""))}, key=str.lower)
    return "; ".join(terms)


def identity_tokens(text: str) -> List[str]:
    tokens = normalize_text(str(text or "")).split()
    return [token for token in tokens if len(token) > 2 and token not in IDENTITY_STOPWORDS]


def split_identity_candidates(text: str) -> List[str]:
    parts = []
    for part in re.split(r"\s*[;|]\s*|\s{2,}", str(text or "")):
        part = re.sub(r"\s+", " ", part).strip(" ,.;")
        if part:
            parts.append(part)
    return parts


def profile_text_match_evidence(profile_text: str, candidates: str, label: str, min_overlap: float = 0.58) -> str:
    profile_norm = normalize_text(profile_text)
    profile_tokens = set(identity_tokens(profile_text))
    evidence = []
    for item in split_identity_candidates(candidates):
        item_norm = normalize_text(item)
        if not item_norm:
            continue
        item_tokens = set(identity_tokens(item))
        if item_norm and item_norm in profile_norm:
            append_unique(evidence, f"{label}: {item}", limit=6)
            continue
        if len(item_tokens) >= 2:
            overlap = len(item_tokens & profile_tokens) / max(1, len(item_tokens))
            if overlap >= min_overlap:
                append_unique(evidence, f"{label}: {item}", limit=6)
    return " | ".join(evidence)


def education_background_evidence(profile_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(profile_text or "")).strip()
    snippets: List[str] = []
    seen: set[str] = set()
    for match in EDUCATION_BACKGROUND_RE.finditer(cleaned):
        start = max(0, match.start() - 100)
        end = min(len(cleaned), match.end() + 100)
        snippet = cleaned[start:end].strip(" ,.;")
        if start > 0:
            snippet = "..." + snippet
        if end < len(cleaned):
            snippet = snippet + "..."
        key = normalize_text(snippet)
        if key and key not in seen:
            snippets.append(f"education: {snippet}")
            seen.add(key)
        if len(snippets) >= 3:
            break
    return " | ".join(snippets)


def homepage_identity_validation(
    name: str,
    profile_text: str,
    affiliations: str = "",
    interests: str = "",
    source_context: str = "deep_search",
    homepage_url: str = "",
) -> Dict[str, str]:
    name_norm = normalized_author_name(name)
    early_text = profile_text[:1600]
    name_confidence = "high" if name_norm and name_norm in normalized_author_name(early_text) else "low"
    if name_confidence == "low" and name_norm and name_norm in normalized_author_name(profile_text):
        name_confidence = "medium"
    affiliation_evidence = profile_text_match_evidence(profile_text, affiliations, "affiliation")
    interest_evidence = profile_text_match_evidence(profile_text, interests, "research_interest", min_overlap=0.5)
    education_evidence = education_background_evidence(profile_text)
    academic_hint = bool(ACADEMIC_HINT_RE.search(profile_text or ""))
    parsed_homepage = urllib.parse.urlparse(str(homepage_url or ""))
    homepage_context = " ".join([parsed_homepage.netloc.lower(), parsed_homepage.path.lower()])
    academic_url_hint = bool(
        re.search(
            r"\b(edu|ac\.|university|college|institute|school|faculty|people|profile|staff|lab|laboratory|research)\b",
            homepage_context,
            re.I,
        )
    )
    strong_identity_evidence = [item for item in [affiliation_evidence, interest_evidence] if item]
    trusted_profile_link = source_context in {"google_scholar_homepage", "semantic_scholar_homepage"}

    if name_confidence in {"high", "medium"} and strong_identity_evidence:
        status = "verified"
        rejection = ""
    elif (
        source_context == "deep_search"
        and name_confidence == "high"
        and education_evidence
        and academic_hint
        and academic_url_hint
    ):
        status = "verified"
        rejection = ""
    elif trusted_profile_link and name_confidence in {"high", "medium"} and academic_hint:
        status = "verified_by_profile_link"
        rejection = ""
    elif source_context == "deep_search":
        status = "rejected"
        if name_confidence == "low":
            rejection = "low_name_confidence"
        elif not (strong_identity_evidence or education_evidence):
            rejection = "no_affiliation_research_or_education_evidence"
        elif education_evidence and not academic_url_hint:
            rejection = "education_evidence_without_academic_profile_url"
        else:
            rejection = "insufficient_identity_evidence"
    elif name_confidence == "low":
        status = "rejected"
        rejection = "low_name_confidence"
    else:
        status = "unverified"
        rejection = "no_affiliation_or_research_match"

    evidence = " | ".join(
        part
        for part in [
            f"name_confidence: {name_confidence}",
            affiliation_evidence,
            interest_evidence,
            education_evidence,
            "url_context: academic_profile_url" if academic_url_hint else "",
            f"source: {source_context}",
        ]
        if part
    )
    return {
        "homepage_identity_status": status,
        "homepage_identity_confidence": name_confidence,
        "homepage_identity_evidence": evidence,
        "homepage_rejection_reason": rejection,
    }


def wikidata_entity(session: requests.Session, qid: str) -> Dict[str, Any]:
    if not qid:
        return {}
    response = session.get(
        f"https://www.wikidata.org/wiki/Special:EntityData/{urllib.parse.quote(qid)}.json",
        timeout=20,
    )
    if not response.ok:
        return {}
    return response.json().get("entities", {}).get(qid, {}) or {}


def wikidata_label_map(session: requests.Session, qids: Sequence[str]) -> Dict[str, str]:
    unique = [qid for qid in dict.fromkeys(qids) if qid]
    labels: Dict[str, str] = {}
    for idx in range(0, len(unique), 50):
        batch = unique[idx : idx + 50]
        response = session.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": "labels",
                "languages": "en",
                "format": "json",
            },
            timeout=20,
        )
        if not response.ok:
            continue
        for qid, entity in (response.json().get("entities") or {}).items():
            label = (entity.get("labels") or {}).get("en", {}).get("value", "")
            if label:
                labels[qid] = label
    return labels


def wikidata_evidence(session: requests.Session, qid: str) -> Dict[str, str]:
    entity = wikidata_entity(session, qid)
    if not entity:
        return {
            "wikidata_description": "",
            "wikidata_evidence": "",
            "academic_titles": "",
            "honors_awards": "",
            "professional_memberships": "",
            "leadership_roles": "",
        }
    description = (entity.get("descriptions") or {}).get("en", {}).get("value", "")
    claim_ids: List[Tuple[str, str, str]] = []
    for prop, prop_label in WIKIDATA_PROFILE_PROPERTIES.items():
        for claim in (entity.get("claims") or {}).get(prop, [])[:10]:
            value = (
                claim.get("mainsnak", {})
                .get("datavalue", {})
                .get("value", {})
            )
            if isinstance(value, dict) and value.get("id"):
                claim_ids.append((prop, prop_label, value["id"]))
    labels = wikidata_label_map(session, [claim_qid for _, _, claim_qid in claim_ids])
    evidence_parts = []
    buckets = {
        "academic_titles": [],
        "honors_awards": [],
        "professional_memberships": [],
        "leadership_roles": [],
    }
    for prop, prop_label, claim_qid in claim_ids:
        label = labels.get(claim_qid, "")
        if not label:
            continue
        phrase = f"{prop_label}: {label}"
        category = CLAIM_CATEGORY_BY_PROP.get(prop, "")
        normalized_label = normalize_text(label)
        if category == "academic_titles":
            if (
                prop in {"P108", "P1416"}
                and not re.search(r"\b(university|college|institute|laboratory|lab|school|academy|research|science|technology)\b", label, re.I)
            ):
                category = ""
            elif prop == "P106" and normalized_label not in ACADEMIC_OCCUPATION_TERMS and not ACADEMIC_HINT_RE.search(label):
                category = ""
        if category:
            append_unique(buckets[category], phrase)
        text_buckets = classify_profile_evidence([phrase])
        for bucket_name, bucket_text in text_buckets.items():
            for part in split_evidence_parts(bucket_text):
                append_unique(buckets[bucket_name], part)
        if prop_label in {"award received", "member of", "position held"} or EXPERT_EVIDENCE_RE.search(phrase):
            evidence_parts.append(phrase)
    evidence_text = " | ".join(dict.fromkeys(evidence_parts))
    return {
        "wikidata_description": description,
        "wikidata_evidence": evidence_text,
        "academic_titles": " | ".join(buckets["academic_titles"]),
        "honors_awards": " | ".join(buckets["honors_awards"]),
        "professional_memberships": " | ".join(buckets["professional_memberships"]),
        "leadership_roles": " | ".join(buckets["leadership_roles"]),
    }


def wikipedia_wikidata_id(session: requests.Session, title: str) -> str:
    response = session.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "prop": "pageprops",
            "titles": title,
            "redirects": 1,
            "format": "json",
        },
        timeout=20,
    )
    if not response.ok:
        return ""
    pages = (response.json().get("query") or {}).get("pages") or {}
    for page in pages.values():
        qid = (page.get("pageprops") or {}).get("wikibase_item", "")
        if qid:
            return qid
    return ""


def wikidata_search_person(session: requests.Session, name: str) -> Dict[str, Any]:
    try:
        response = session.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "type": "item",
                "limit": 8,
                "format": "json",
            },
            timeout=20,
        )
        if not response.ok:
            return {}
        name_norm = normalized_author_name(name)
        best: Dict[str, Any] = {}
        best_score = 0.0
        for item in response.json().get("search", []):
            label = item.get("label", "")
            description = item.get("description", "")
            label_norm = normalized_author_name(label)
            if not label_norm:
                continue
            if label_norm == name_norm:
                score = 1.0
            elif name_norm in label_norm or label_norm in name_norm:
                score = 0.92
            else:
                score = SequenceMatcher(None, name_norm, label_norm).ratio()
            if not ACADEMIC_HINT_RE.search(description):
                score -= 0.15
            if score > best_score:
                best_score = score
                best = item
        if best and best_score >= 0.82:
            best["match_score"] = best_score
            return best
    except Exception:
        return {}
    return {}


def wikipedia_page_profile_text(session: requests.Session, title: str) -> Dict[str, str]:
    try:
        response = session.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "parse",
                "page": title,
                "prop": "text|categories",
                "redirects": 1,
                "format": "json",
            },
            timeout=25,
        )
        if not response.ok:
            return {"text": "", "categories": "", "infobox": ""}
        parsed = response.json().get("parse") or {}
        html = ((parsed.get("text") or {}).get("*")) or ""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.select("style,script,sup.reference,.mw-editsection,.navbox,.metadata"):
            tag.decompose()
        paragraphs = [
            re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True)).strip()
            for paragraph in soup.select("p")
            if paragraph.get_text(" ", strip=True)
        ][:5]
        infobox_parts = []
        for table in soup.select("table.infobox")[:1]:
            for row in table.select("tr"):
                header = row.select_one("th")
                data = row.select_one("td")
                if not header or not data:
                    continue
                header_text = re.sub(r"\s+", " ", header.get_text(" ", strip=True)).strip()
                data_text = re.sub(r"\s+", " ", data.get_text(" ", strip=True)).strip()
                if header_text and data_text:
                    append_unique(infobox_parts, f"{header_text}: {data_text}", limit=20)
        categories = [
            str(item.get("*") or "").strip()
            for item in parsed.get("categories", [])
            if item.get("*")
        ]
        return {
            "text": " ".join(paragraphs),
            "categories": " | ".join(categories[:30]),
            "infobox": " | ".join(infobox_parts),
        }
    except Exception:
        return {"text": "", "categories": "", "infobox": ""}


def plausible_personal_homepage_url(url: Any) -> str:
    text = str(url or "").strip()
    if not text or text.lower() == "nan":
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = parsed.netloc.lower()
    blocked_hosts = (
        "scholar.google.",
        "semanticscholar.org",
        "wikipedia.org",
        "wikidata.org",
        "doi.org",
        "orcid.org",
        "dblp.org",
    )
    if any(blocked in host for blocked in blocked_hosts):
        return ""
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def homepage_profile_summary(
    session: requests.Session,
    url: str,
    name: str,
    affiliations: str = "",
    interests: str = "",
    source_context: str = "direct_homepage",
) -> Dict[str, Any]:
    url = plausible_personal_homepage_url(url)
    if not url:
        return {"homepage_query_status": "no_homepage_url", "enrichment_version": PROFILE_ENRICHMENT_VERSION}
    try:
        response = session.get(url, timeout=20, allow_redirects=True)
        content_type = response.headers.get("content-type", "").lower()
        if not response.ok:
            return {
                "homepage_url": url,
                "homepage_query_status": "homepage_http_error",
                "homepage_error": f"http_{response.status_code}",
                "enrichment_version": PROFILE_ENRICHMENT_VERSION,
            }
        if content_type and not any(kind in content_type for kind in ("text/html", "application/xhtml", "text/plain")):
            return {
                "homepage_url": url,
                "homepage_query_status": "homepage_unsupported_content_type",
                "homepage_error": content_type[:120],
                "enrichment_version": PROFILE_ENRICHMENT_VERSION,
            }
        soup = BeautifulSoup(response.text[:800000], "html.parser")
        for tag in soup.select("style,script,noscript,svg,nav,footer"):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        meta_description = ""
        meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_tag:
            meta_description = str(meta_tag.get("content") or "").strip()
        headings = [
            item.get_text(" ", strip=True)
            for item in soup.select("h1,h2,h3")
            if item.get_text(" ", strip=True)
        ][:8]
        paragraphs = [
            re.sub(r"\s+", " ", item.get_text(" ", strip=True)).strip()
            for item in soup.select("p,li,td")
            if item.get_text(" ", strip=True)
        ][:80]
        profile_text = " ".join([title, meta_description, " | ".join(headings), " ".join(paragraphs)])
        profile_text = re.sub(r"\s+", " ", profile_text).strip()
        identity = homepage_identity_validation(name, profile_text, affiliations, interests, source_context, response.url or url)
        name_confidence = identity.get("homepage_identity_confidence", "low")
        evidence = evidence_snippets(profile_text, max_snippets=6, radius=120) or evidence_terms(profile_text)
        classified = classify_profile_evidence(split_evidence_parts(" | ".join([evidence, title, meta_description, " | ".join(headings)])))
        academic_hint = bool(ACADEMIC_HINT_RE.search(profile_text))
        explicit_evidence = bool(
            classified.get("honors_awards")
            or classified.get("professional_memberships")
            or classified.get("leadership_roles")
            or re.search(r"\b(distinguished professor|chair professor|endowed chair|named professor)\b", classified.get("academic_titles", ""), re.I)
        )
        identity_verified = identity.get("homepage_identity_status") in {"verified", "verified_by_profile_link"}
        return {
            "homepage_url": response.url or url,
            "homepage_title": title,
            "homepage_query_status": "queried",
            "homepage_name_confidence": name_confidence,
            "homepage_summary": text_value(profile_text)[:1200],
            "homepage_evidence": evidence,
            "academic_titles": classified.get("academic_titles", ""),
            "honors_awards": classified.get("honors_awards", ""),
            "professional_memberships": classified.get("professional_memberships", ""),
            "leadership_roles": classified.get("leadership_roles", ""),
            **identity,
            "is_notable": bool(identity_verified and academic_hint and explicit_evidence),
            "notable_reason": evidence if identity_verified and explicit_evidence else "",
            "enrichment_version": PROFILE_ENRICHMENT_VERSION,
        }
    except Exception as exc:
        return {
            "homepage_url": url,
            "homepage_query_status": "homepage_error",
            "homepage_error": str(exc)[:300],
            "enrichment_version": PROFILE_ENRICHMENT_VERSION,
        }


def decode_search_result_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    params = urllib.parse.parse_qs(parsed.query)
    for key in ("uddg", "u", "url"):
        value = (params.get(key) or [""])[0]
        if value:
            return urllib.parse.unquote(value)
    return text


def url_is_low_value_author_profile(url: str) -> bool:
    host = urllib.parse.urlparse(str(url or "")).netloc.lower()
    path = urllib.parse.urlparse(str(url or "")).path.lower()
    blocked = (
        "linkedin.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "researchgate.net",
        "academia.edu",
        "orcid.org",
        "dblp.org",
        "semanticscholar.org",
        "scholar.google.",
        "wikipedia.org",
        "wikidata.org",
    )
    return any(item in host for item in blocked) or path.endswith((".pdf", ".ppt", ".pptx", ".doc", ".docx"))


def score_author_homepage_candidate(name: str, url: str, title: str, snippet: str) -> float:
    url = plausible_personal_homepage_url(url)
    if not url or url_is_low_value_author_profile(url):
        return -100.0
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    haystack = normalize_text(" ".join([title, snippet, url]))
    name_norm = normalized_author_name(name)
    tokens = [token for token in name_norm.split() if len(token) > 1]
    score = 0.0
    if name_norm and name_norm in haystack:
        score += 6.0
    elif tokens and all(token in haystack for token in tokens[-2:]):
        score += 3.0
    elif tokens and tokens[-1] in haystack:
        score += 1.0
    if re.search(r"\b(edu|ac\.|university|college|institute|lab|laboratory|research|school)\b", host, re.I):
        score += 2.5
    if re.search(r"/(~|people|person|faculty|staff|profile|users?|members?|team|about)", path, re.I):
        score += 2.0
    if re.search(r"\b(professor|researcher|scientist|phd|faculty|university|institute|lab)\b", " ".join([title, snippet]), re.I):
        score += 1.5
    return score


def search_author_homepage_candidates(
    session: requests.Session,
    name: str,
    affiliations: str = "",
    interests: str = "",
    limit: int = 8,
) -> List[Dict[str, Any]]:
    queries = [
        f'"{name}" professor researcher homepage',
        f'"{name}" university faculty profile',
    ]
    if affiliations:
        queries.insert(0, f'"{name}" "{str(affiliations).split(";")[0].strip()}"')
    if interests:
        first_interest = str(interests).split(";")[0].strip()
        if first_interest:
            queries.append(f'"{name}" "{first_interest}" researcher')
    candidates: Dict[str, Dict[str, Any]] = {}
    for query in queries[:4]:
        try:
            response = session.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                timeout=20,
            )
            if not response.ok:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            for block in soup.select(".result")[:12]:
                link = block.select_one(".result__a") or block.find("a", href=True)
                if not link:
                    continue
                url = decode_search_result_url(link.get("href", ""))
                url = plausible_personal_homepage_url(url)
                if not url:
                    continue
                title = link.get_text(" ", strip=True)
                snippet_tag = block.select_one(".result__snippet")
                snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else block.get_text(" ", strip=True)
                score = score_author_homepage_candidate(name, url, title, snippet)
                if score <= 0:
                    continue
                existing = candidates.get(url)
                row = {"url": url, "title": title, "snippet": snippet, "score": score, "query": query}
                if not existing or score > float(existing.get("score") or 0):
                    candidates[url] = row
        except Exception:
            continue
    ranked = sorted(candidates.values(), key=lambda item: float(item.get("score") or 0), reverse=True)
    return ranked[:limit]


def homepage_search_summary(
    session: requests.Session,
    name: str,
    affiliations: str = "",
    interests: str = "",
    max_candidates: int = 4,
) -> Dict[str, Any]:
    candidates = search_author_homepage_candidates(session, name, affiliations, interests, limit=max_candidates)
    if not candidates:
        return {
            "homepage_query_status": "homepage_search_not_found",
            "homepage_search_candidates_json": "[]",
            "enrichment_version": PROFILE_ENRICHMENT_VERSION,
        }
    profiles = []
    for candidate in candidates:
        profile = homepage_profile_summary(
            session,
            candidate.get("url", ""),
            name,
            affiliations,
            interests,
            source_context="deep_search",
        )
        profile["homepage_search_score"] = candidate.get("score", "")
        profile["homepage_search_title"] = candidate.get("title", "")
        profile["homepage_search_snippet"] = candidate.get("snippet", "")
        profiles.append(profile)
    def profile_rank(profile: Dict[str, Any]) -> Tuple[int, int, int, float]:
        verified = profile.get("homepage_identity_status") == "verified"
        return (
            1 if verified else 0,
            1 if profile.get("is_notable") else 0,
            1 if profile.get("homepage_evidence") else 0,
            1 if profile.get("homepage_summary") else 0,
            float(profile.get("homepage_search_score") or 0),
        )
    best = max(profiles, key=profile_rank)
    if best.get("homepage_identity_status") != "verified":
        return {
            "homepage_query_status": "homepage_search_rejected_identity",
            "homepage_rejection_reason": best.get("homepage_rejection_reason", "insufficient_identity_evidence"),
            "homepage_identity_status": best.get("homepage_identity_status", "rejected"),
            "homepage_identity_confidence": best.get("homepage_identity_confidence", ""),
            "homepage_identity_evidence": best.get("homepage_identity_evidence", ""),
            "homepage_search_candidates_json": json.dumps(candidates, ensure_ascii=False),
            "homepage_search_profiles_json": json.dumps(profiles, ensure_ascii=False),
            "enrichment_version": PROFILE_ENRICHMENT_VERSION,
        }
    best["homepage_query_status"] = "homepage_search_found_verified"
    best["homepage_search_candidates_json"] = json.dumps(candidates, ensure_ascii=False)
    best["enrichment_version"] = PROFILE_ENRICHMENT_VERSION
    return best


def profile_page_match_confidence(name: str, title: str, summary_text: str) -> str:
    name_norm = normalized_author_name(name)
    title_norm = normalized_author_name(title)
    summary_norm = normalized_author_name(summary_text[:240])
    if name_norm and title_norm == name_norm:
        return "high"
    if name_norm and (name_norm in title_norm or title_norm in name_norm):
        return "high"
    if name_norm and name_norm in summary_norm:
        return "high"
    similarity = SequenceMatcher(None, name_norm, title_norm).ratio() if name_norm and title_norm else 0.0
    if similarity >= 0.86:
        return "medium"
    return "low"


def wikipedia_summary(session: requests.Session, name: str) -> Dict[str, Any]:
    rejection_reason = "no_wikipedia_or_wikidata_match"
    try:
        search = session.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": name, "format": "json", "srlimit": 8},
            timeout=20,
        )
        if not search.ok:
            return {
                "is_notable": False,
                "expert_query_status": "wiki_api_error",
                "expert_rejection_reason": f"wikipedia_search_http_{search.status_code}",
                "enrichment_version": PROFILE_ENRICHMENT_VERSION,
            }
        results = search.json().get("query", {}).get("search", [])
        name_norm = normalized_author_name(name)
        for result in results:
            title = result.get("title", "")
            title_norm = normalized_author_name(title)
            snippet_norm = normalized_author_name(result.get("snippet", ""))
            if name_norm not in title_norm and title_norm not in name_norm and name_norm not in snippet_norm:
                continue
            summary = session.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}",
                timeout=20,
            )
            if not summary.ok:
                rejection_reason = "wiki_api_error"
                continue
            data = summary.json()
            extract = data.get("extract", "") or ""
            page_type = data.get("type", "")
            matched_title = data.get("title", title)
            match_confidence = profile_page_match_confidence(name, matched_title, extract)
            if match_confidence == "low":
                rejection_reason = "low_name_confidence"
                continue
            qid = wikipedia_wikidata_id(session, matched_title)
            wikidata = wikidata_evidence(session, qid) if qid else {
                "wikidata_description": "",
                "wikidata_evidence": "",
                "academic_titles": "",
                "honors_awards": "",
                "professional_memberships": "",
                "leadership_roles": "",
            }
            page_profile = wikipedia_page_profile_text(session, matched_title)
            combined_evidence_text = " ".join(
                [
                    extract,
                    page_profile.get("text", ""),
                    page_profile.get("infobox", ""),
                    page_profile.get("categories", ""),
                    wikidata.get("wikidata_description", ""),
                    wikidata.get("wikidata_evidence", ""),
                    wikidata.get("academic_titles", ""),
                    wikidata.get("honors_awards", ""),
                    wikidata.get("professional_memberships", ""),
                    wikidata.get("leadership_roles", ""),
                ]
            )
            wiki_evidence_text = " ".join([extract, page_profile.get("text", ""), page_profile.get("infobox", ""), page_profile.get("categories", "")])
            wiki_evidence = evidence_snippets(wiki_evidence_text) or evidence_terms(wiki_evidence_text)
            wiki_data_evidence = wikidata.get("wikidata_evidence", "")
            classified = classify_profile_evidence(
                split_evidence_parts(" | ".join([wiki_evidence, wiki_data_evidence, page_profile.get("infobox", ""), page_profile.get("categories", "")]))
            )
            for key in ["academic_titles", "honors_awards", "professional_memberships", "leadership_roles"]:
                merged_parts = split_evidence_parts(classified.get(key, "")) + split_evidence_parts(wikidata.get(key, ""))
                classified[key] = " | ".join(dict.fromkeys(part for part in merged_parts if part))
            structured_summary = profile_evidence_summary(classified)
            all_evidence = " | ".join([part for part in [wiki_evidence, wiki_data_evidence, structured_summary] if part])
            scholar_hint = bool(ACADEMIC_HINT_RE.search(combined_evidence_text))
            explicit_profile_evidence = any(classified.get(key) for key in ["honors_awards", "professional_memberships", "leadership_roles"])
            if not explicit_profile_evidence:
                explicit_profile_evidence = bool(EXPERT_EVIDENCE_RE.search(all_evidence))
            is_notable = page_type != "disambiguation" and match_confidence in {"high", "medium"} and scholar_hint and explicit_profile_evidence
            if is_notable:
                expert_query_status = "notable"
                expert_rejection_reason = ""
            elif page_type == "disambiguation":
                expert_query_status = "rejected"
                expert_rejection_reason = "disambiguation_page"
            elif match_confidence not in {"high", "medium"}:
                expert_query_status = "rejected"
                expert_rejection_reason = "low_name_confidence"
            elif not scholar_hint:
                expert_query_status = "rejected"
                expert_rejection_reason = "no_academic_profile_hint"
            elif not explicit_profile_evidence:
                expert_query_status = "rejected"
                expert_rejection_reason = "no_explicit_honor_or_role"
            else:
                expert_query_status = "rejected"
                expert_rejection_reason = "notability_criteria_not_met"
            evidence_sources = []
            if wiki_evidence:
                evidence_sources.append("wikipedia")
            if page_profile.get("infobox"):
                evidence_sources.append("wikipedia_infobox")
            if wiki_data_evidence or any(wikidata.get(key) for key in ["academic_titles", "honors_awards", "professional_memberships", "leadership_roles"]):
                evidence_sources.append("wikidata")
            return {
                "title": matched_title,
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "wikidata_id": qid,
                "wikidata_description": wikidata.get("wikidata_description", ""),
                "summary": extract,
                "evidence": wiki_evidence,
                "wikidata_evidence": wiki_data_evidence,
                "academic_titles": classified.get("academic_titles", ""),
                "honors_awards": classified.get("honors_awards", ""),
                "professional_memberships": classified.get("professional_memberships", ""),
                "leadership_roles": classified.get("leadership_roles", ""),
                "profile_evidence_sources": "; ".join(dict.fromkeys(evidence_sources)),
                "notability_confidence": match_confidence if is_notable else ("low_evidence" if match_confidence in {"high", "medium"} else "low_match"),
                "expert_query_status": expert_query_status,
                "expert_rejection_reason": expert_rejection_reason,
                "is_notable": is_notable,
                "notable_reason": all_evidence if is_notable else "",
                "enrichment_version": PROFILE_ENRICHMENT_VERSION,
            }
        wd_item = wikidata_search_person(session, name)
        qid = wd_item.get("id", "")
        if qid:
            wikidata = wikidata_evidence(session, qid)
            classified = {
                key: wikidata.get(key, "")
                for key in ["academic_titles", "honors_awards", "professional_memberships", "leadership_roles"]
            }
            all_evidence = profile_evidence_summary(classified)
            explicit_profile_evidence = any(classified.get(key) for key in ["honors_awards", "professional_memberships", "leadership_roles"])
            scholar_hint = bool(ACADEMIC_HINT_RE.search(" ".join([wd_item.get("description", ""), wikidata.get("wikidata_description", ""), all_evidence])))
            is_notable = bool(explicit_profile_evidence and scholar_hint)
            if is_notable:
                expert_query_status = "notable"
                expert_rejection_reason = ""
            else:
                expert_query_status = "rejected"
                expert_rejection_reason = "no_explicit_honor_or_role" if scholar_hint else "no_academic_profile_hint"
            return {
                "title": wd_item.get("label", name),
                "url": f"https://www.wikidata.org/wiki/{qid}",
                "wikidata_id": qid,
                "wikidata_description": wikidata.get("wikidata_description", "") or wd_item.get("description", ""),
                "summary": wd_item.get("description", ""),
                "evidence": "",
                "wikidata_evidence": wikidata.get("wikidata_evidence", ""),
                "academic_titles": classified.get("academic_titles", ""),
                "honors_awards": classified.get("honors_awards", ""),
                "professional_memberships": classified.get("professional_memberships", ""),
                "leadership_roles": classified.get("leadership_roles", ""),
                "profile_evidence_sources": "wikidata",
                "notability_confidence": "medium" if is_notable else "wikidata_profile",
                "expert_query_status": expert_query_status,
                "expert_rejection_reason": expert_rejection_reason,
                "is_notable": is_notable,
                "notable_reason": " | ".join([part for part in [wikidata.get("wikidata_evidence", ""), all_evidence] if part]) if is_notable else "",
                "enrichment_version": PROFILE_ENRICHMENT_VERSION,
            }
    except Exception as exc:
        return {
            "error": str(exc),
            "is_notable": False,
            "expert_query_status": "wiki_api_error",
            "expert_rejection_reason": str(exc)[:300],
            "enrichment_version": PROFILE_ENRICHMENT_VERSION,
        }
    return {
        "is_notable": False,
        "expert_query_status": "not_found",
        "expert_rejection_reason": rejection_reason,
        "enrichment_version": PROFILE_ENRICHMENT_VERSION,
    }


def fetch_wikipedia_profile(author_key: str, name: str) -> Tuple[str, Dict[str, Any]]:
    session = make_session()
    return author_key, wikipedia_summary(session, name)


def fetch_homepage_profile(
    author_key: str,
    name: str,
    homepage_url: str,
    affiliations: str = "",
    interests: str = "",
    source_context: str = "direct_homepage",
) -> Tuple[str, Dict[str, Any]]:
    session = make_session()
    return author_key, homepage_profile_summary(session, homepage_url, name, affiliations, interests, source_context)


def fetch_homepage_search_profile(
    author_key: str,
    name: str,
    affiliations: str,
    interests: str,
) -> Tuple[str, Dict[str, Any]]:
    session = make_session()
    return author_key, homepage_search_summary(session, name, affiliations, interests)


def target_author_identity(target: Dict[str, Any]) -> Tuple[set[str], set[str]]:
    target_ids: set[str] = set()
    target_names: set[str] = set()
    for author in target.get("authors") or []:
        if isinstance(author, dict):
            author_id = str(author.get("authorId") or "").strip()
            name = str(author.get("name") or "").strip()
        else:
            author_id = ""
            name = str(author or "").strip()
        if author_id:
            target_ids.add(author_id)
        name_norm = normalized_author_name(name)
        if name_norm:
            target_names.add(name_norm)
    return target_ids, target_names


def target_author_match(candidate: Dict[str, Any], target_ids: set[str], target_names: set[str]) -> Tuple[bool, str]:
    author_id = str(candidate.get("semantic_author_id") or "").strip()
    if author_id and author_id in target_ids:
        return True, "semantic_author_id"
    name_norm = str(candidate.get("normalized_name") or normalized_author_name(candidate.get("name", "")))
    if name_norm and name_norm in target_names:
        return True, "normalized_name"
    return False, ""


def profile_url_for_author(row: Dict[str, Any]) -> str:
    return str(row.get("google_scholar_profile_url") or row.get("semantic_scholar_profile_url") or "")


def homepage_url_for_author(row: Dict[str, Any]) -> str:
    for key in ("personal_homepage_url", "google_scholar_homepage_url", "semantic_scholar_homepage_url"):
        url = plausible_personal_homepage_url(row.get(key, ""))
        if url:
            return url
    return ""


def merge_evidence_field(*values: Any) -> str:
    parts: List[str] = []
    for value in values:
        for part in split_evidence_parts(str(value or "")):
            append_unique(parts, part, limit=20)
    return " | ".join(parts)


def author_report_row(candidate: Dict[str, Any], wiki: Dict[str, Any]) -> Dict[str, Any]:
    row = {column: candidate.get(column, "") for column in AUTHOR_COLUMNS}
    homepage = wiki.get("homepage_profile") if isinstance(wiki.get("homepage_profile"), dict) else {}
    profile_affiliations = " | ".join(
        dict.fromkeys(
            part
            for part in [
                str(candidate.get("semantic_scholar_affiliations") or "").strip(),
                str(candidate.get("google_scholar_affiliation") or "").strip(),
            ]
            if part
        )
    )
    research_interests = str(candidate.get("google_scholar_interests") or "").strip()
    evidence_sources = split_evidence_parts(str(wiki.get("profile_evidence_sources", "")).replace("; ", " | "))
    homepage_identity_status = str(homepage.get("homepage_identity_status") or "")
    homepage_verified = homepage_identity_status in {"verified", "verified_by_profile_link"}
    homepage_url = homepage.get("homepage_url", "") if homepage_verified else ""
    if not homepage_url and not homepage:
        homepage_url = homepage_url_for_author(candidate)
    homepage_evidence = homepage.get("homepage_evidence", "")
    if profile_affiliations:
        evidence_sources.append("semantic_scholar/google_scholar_profile")
    if research_interests:
        evidence_sources.append("google_scholar_profile")
    if homepage_url or (homepage_verified and homepage_evidence):
        evidence_sources.append("personal_or_school_homepage")
    academic_titles = merge_evidence_field(wiki.get("academic_titles", ""), homepage.get("academic_titles", ""))
    honors_awards = merge_evidence_field(wiki.get("honors_awards", ""), homepage.get("honors_awards", ""))
    professional_memberships = merge_evidence_field(wiki.get("professional_memberships", ""), homepage.get("professional_memberships", ""))
    leadership_roles = merge_evidence_field(wiki.get("leadership_roles", ""), homepage.get("leadership_roles", ""))
    homepage_notable = bool(homepage.get("is_notable"))
    is_notable = bool(wiki.get("is_notable") or homepage_notable)
    notable_reason = wiki.get("notable_reason", "") or (homepage.get("notable_reason", "") if homepage_notable else "")
    if wiki:
        expert_query_status = "notable" if is_notable else (wiki.get("expert_query_status") or "queried")
        expert_rejection_reason = "" if is_notable else wiki.get("expert_rejection_reason", "")
    elif candidate.get("_expert_query_selected"):
        expert_query_status = "notable" if homepage_notable else "not_found"
        expert_rejection_reason = "" if homepage_notable else "no_wikipedia_or_wikidata_match"
    else:
        expert_query_status = "not_queried_outside_expert_scope"
        expert_rejection_reason = "not_in_top_100_or_top_paper_authors"
    row.update(
        {
            "wikipedia_title": wiki.get("title", ""),
            "wikipedia_url": wiki.get("url", ""),
            "wikidata_id": wiki.get("wikidata_id", ""),
            "wikidata_description": wiki.get("wikidata_description", ""),
            "wikipedia_summary": wiki.get("summary", ""),
            "wikipedia_evidence": wiki.get("evidence", ""),
            "wikidata_evidence": wiki.get("wikidata_evidence", ""),
            "academic_titles": academic_titles,
            "honors_awards": honors_awards,
            "professional_memberships": professional_memberships,
            "leadership_roles": leadership_roles,
            "profile_affiliations": profile_affiliations,
            "research_interests": research_interests,
            "personal_homepage_url": homepage_url,
            "personal_homepage_evidence": homepage_evidence,
            "personal_homepage_summary": homepage.get("homepage_summary", ""),
            "personal_homepage_identity_status": homepage_identity_status,
            "personal_homepage_identity_confidence": homepage.get("homepage_identity_confidence", ""),
            "personal_homepage_identity_evidence": homepage.get("homepage_identity_evidence", ""),
            "personal_homepage_rejection_reason": homepage.get("homepage_rejection_reason", ""),
            "profile_evidence_sources": "; ".join(dict.fromkeys(evidence_sources)),
            "notability_confidence": wiki.get("notability_confidence", "") or homepage.get("homepage_name_confidence", ""),
            "expert_query_status": expert_query_status,
            "expert_rejection_reason": expert_rejection_reason,
            "is_notable": is_notable,
            "notable_reason": notable_reason,
        }
    )
    return row


def author_key_for_entry(entry: Dict[str, str], name_to_key: Dict[str, str]) -> str:
    author_id = str(entry.get("authorId") or "").strip()
    if author_id:
        return f"s2:{author_id}"
    name_norm = normalized_author_name(entry.get("name", ""))
    return name_to_key.get(name_norm, f"name:{name_norm}")


def build_paper_author_outputs(
    papers: pd.DataFrame,
    enriched: List[Dict[str, Any]],
    author_report_by_key: Dict[str, Dict[str, Any]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    author_by_key = {item["author_key"]: item for item in enriched}
    name_to_key = {
        str(item.get("normalized_name") or ""): item["author_key"]
        for item in enriched
        if item.get("normalized_name")
    }
    paper_author_rows: List[Dict[str, Any]] = []
    updated_papers: List[Dict[str, Any]] = []
    for paper in clean_frame_for_report(papers, PAPER_COLUMNS).to_dict("records"):
        entries = author_entries_for_row(paper)
        candidates_for_paper: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []
        target_count = 0
        for order, entry in enumerate(entries, 1):
            key = author_key_for_entry(entry, name_to_key)
            author = author_by_key.get(key, {})
            report_row = author_report_by_key.get(key, {})
            is_target = bool(author.get("is_target_author"))
            if is_target:
                target_count += 1
            row = {
                "dedupe_key": paper.get("dedupe_key", ""),
                "citing_title": paper.get("citing_title", ""),
                "publication_year": paper.get("publication_year", ""),
                "venue": paper.get("venue", ""),
                "author_order": order,
                "author_key": key,
                "name": author.get("name", entry.get("name", "")),
                "normalized_name": author.get("normalized_name", normalized_author_name(entry.get("name", ""))),
                "semantic_author_id": author.get("semantic_author_id", entry.get("authorId", "")),
                "is_target_author": is_target,
                "target_author_match": author.get("target_author_match", ""),
                "selected_citation_count": author.get("selected_citation_count", ""),
                "selected_citation_source": author.get("selected_citation_source", ""),
                "google_scholar_citations": author.get("google_scholar_citations", ""),
                "semantic_scholar_citations": author.get("semantic_scholar_citations", ""),
                "semantic_scholar_h_index": author.get("semantic_scholar_h_index", ""),
                "google_scholar_profile_url": author.get("google_scholar_profile_url", ""),
                "google_scholar_homepage_url": author.get("google_scholar_homepage_url", ""),
                "semantic_scholar_profile_url": author.get("semantic_scholar_profile_url", ""),
                "semantic_scholar_homepage_url": author.get("semantic_scholar_homepage_url", ""),
                "personal_homepage_url": report_row.get("personal_homepage_url", "") or homepage_url_for_author(author),
                "profile_query_status": author.get("profile_query_status", ""),
                "notes": author.get("notes", ""),
            }
            paper_author_rows.append(row)
            if author and not is_target:
                candidates_for_paper.append((order, author, row))
        if not entries:
            paper["top_author_status"] = "no_authors"
        elif not candidates_for_paper:
            paper["top_author_status"] = "all_authors_excluded_target"
        else:
            candidates_for_paper.sort(
                key=lambda item: (
                    -parse_int(item[1].get("selected_citation_count")),
                    -parse_int(item[1].get("semantic_scholar_h_index")),
                    item[0],
                    str(item[1].get("name", "")).lower(),
                )
            )
            _, top_author, _ = candidates_for_paper[0]
            report_row = author_report_by_key.get(top_author["author_key"], {})
            paper["top_author_key"] = top_author.get("author_key", "")
            paper["top_author_name"] = top_author.get("name", "")
            paper["top_author_selected_citation_count"] = top_author.get("selected_citation_count", "")
            paper["top_author_selected_citation_source"] = top_author.get("selected_citation_source", "")
            paper["top_author_profile_url"] = profile_url_for_author(top_author)
            paper["top_author_homepage_url"] = homepage_url_for_author(report_row) or homepage_url_for_author(top_author)
            paper["top_author_is_notable"] = bool(report_row.get("is_notable"))
            paper["top_author_status"] = "ok"
        paper["target_author_excluded_count"] = target_count
        updated_papers.append(paper)
    return (
        clean_frame_for_report(pd.DataFrame(updated_papers), PAPER_COLUMNS),
        clean_frame_for_report(pd.DataFrame(paper_author_rows), PAPER_AUTHOR_COLUMNS),
    )


def top_author_keys_for_papers(papers: pd.DataFrame, enriched: List[Dict[str, Any]]) -> List[str]:
    author_by_key = {item["author_key"]: item for item in enriched}
    name_to_key = {
        str(item.get("normalized_name") or ""): item["author_key"]
        for item in enriched
        if item.get("normalized_name")
    }
    keys: List[str] = []
    seen: set[str] = set()
    for paper in clean_frame_for_report(papers, PAPER_COLUMNS).to_dict("records"):
        entries = author_entries_for_row(paper)
        candidates_for_paper: List[Tuple[int, Dict[str, Any]]] = []
        for order, entry in enumerate(entries, 1):
            key = author_key_for_entry(entry, name_to_key)
            author = author_by_key.get(key, {})
            if author and not author.get("is_target_author"):
                candidates_for_paper.append((order, author))
        if not candidates_for_paper:
            continue
        candidates_for_paper.sort(
            key=lambda item: (
                -parse_int(item[1].get("selected_citation_count")),
                -parse_int(item[1].get("semantic_scholar_h_index")),
                item[0],
                str(item[1].get("name", "")).lower(),
            )
        )
        key = str(candidates_for_paper[0][1].get("author_key") or "")
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def enrich_authors(args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    output = ensure_dir(args.output)
    papers = read_papers(output)
    if papers.empty:
        citing_path = output / "citing_papers.csv"
        if not citing_path.exists():
            raise RuntimeError(f"Missing papers in citation_report.xlsx or legacy citing papers: {citing_path}")
        candidates, papers = collect_author_candidates(citing_path)
        papers = clean_frame_for_report(papers, PAPER_COLUMNS)
    else:
        candidates, papers = collect_author_candidates_from_papers(papers)
    target = load_target(output)
    target_ids, target_names = target_author_identity(target)
    session = make_session()
    api_key = getattr(args, "s2_api_key", "") or os.environ.get(getattr(args, "s2_api_key_env", "SEMANTIC_SCHOLAR_API_KEY"), "")
    scholar_locale = getattr(args, "scholar_locale", "en") or "en"
    scholar_browser = getattr(args, "browser", "edge") or "edge"
    scholar_captcha_action = getattr(args, "scholar_captcha_action", "fail") or "fail"
    scholar_captcha_timeout = numeric_arg(args, "scholar_captcha_timeout", 600.0, float)
    min_delay = numeric_arg(args, "min_delay", 1.0, float)
    max_delay = numeric_arg(args, "max_delay", 3.0, float)
    top_n = numeric_arg(args, "author_top_n", 20, int)
    max_profiles = numeric_arg(args, "max_author_profiles", 200, int)
    author_workers = max(1, numeric_arg(args, "author_workers", 4, int))
    wiki_workers = max(1, numeric_arg(args, "wiki_workers", 2, int))
    homepage_search_limit = max(0, numeric_arg(args, "homepage_search_limit", 50, int))
    skip_google_scholar_authors = bool(getattr(args, "skip_google_scholar_authors", False))
    if max_delay < min_delay:
        max_delay = min_delay
    google_cache_path = output / "author_profile_cache.json"
    wiki_cache_path = output / "wikipedia_profile_cache.json"
    profile_cache = prepare_author_profile_cache(load_cache(google_cache_path))
    google_cache = profile_cache["google_scholar"]
    s2_cache = profile_cache["semantic_scholar"]
    wiki_cache = load_cache(wiki_cache_path)
    for candidate in candidates:
        is_target, match = target_author_match(candidate, target_ids, target_names)
        candidate["is_target_author"] = is_target
        candidate["target_author_match"] = match

    candidates.sort(key=lambda item: (not bool(item.get("is_target_author")), *author_profile_priority(item)), reverse=True)
    profile_keys = {
        candidate["author_key"]
        for candidate in candidates[: max(0, max_profiles)]
    }

    metric_jobs: List[Tuple[str, Dict[str, Any]]] = []
    for candidate in candidates:
        candidate["profile_query_status"] = "queried" if candidate["author_key"] in profile_keys else "not_queried_profile_limit"
        cache_key = author_metric_cache_key(candidate, candidate["name"])
        if candidate["author_key"] in profile_keys and cache_key not in s2_cache:
            metric_jobs.append((cache_key, candidate.copy()))
    queried_profiles = len(profile_keys)
    if metric_jobs:
        if author_workers > 1:
            completed = 0
            with ThreadPoolExecutor(max_workers=min(author_workers, len(metric_jobs))) as executor:
                futures = {
                    executor.submit(fetch_s2_author_metric, cache_key, candidate, api_key): cache_key
                    for cache_key, candidate in metric_jobs
                }
                for future in as_completed(futures):
                    cache_key = futures[future]
                    try:
                        _, metrics = future.result()
                    except Exception as exc:
                        metrics = {"error": str(exc)}
                    s2_cache[cache_key] = metrics
                    completed += 1
                    if completed % 25 == 0 or completed == len(metric_jobs):
                        print(f"Semantic Scholar author profiles fetched: {completed}/{len(metric_jobs)}")
        else:
            for completed, (cache_key, candidate) in enumerate(metric_jobs, 1):
                s2_cache[cache_key] = s2_author_metrics(make_session(), candidate.get("semantic_author_id", ""), candidate.get("name", ""), api_key)
                if completed % 25 == 0 or completed == len(metric_jobs):
                    print(f"Semantic Scholar author profiles fetched: {completed}/{len(metric_jobs)}")

    enriched: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(candidates, 1):
        name = candidate["name"]
        cache_key = author_metric_cache_key(candidate, name)
        if candidate["author_key"] in profile_keys:
            s2 = s2_cache.get(cache_key, {})
        else:
            s2 = {}
        if s2.get("error"):
            candidate["profile_query_status"] = "queried_s2_error"
        s2_citations = parse_int(s2.get("citationCount"))
        s2_h = parse_int(s2.get("hIndex"))
        s2_papers = parse_int(s2.get("paperCount"))
        candidate.update(
            {
                "semantic_author_id": candidate.get("semantic_author_id") or s2.get("authorId", ""),
                "semantic_scholar_citations": s2_citations,
                "semantic_scholar_h_index": s2_h,
                "semantic_scholar_paper_count": s2_papers,
                "semantic_scholar_affiliations": "; ".join(s2.get("affiliations") or []),
                "semantic_scholar_profile_url": s2.get("url", ""),
                "semantic_scholar_homepage_url": s2.get("homepage", ""),
            }
        )
        enriched.append(candidate)
        if idx % 25 == 0:
            print(f"Author candidates processed: {idx}/{len(candidates)}; profile queries {queried_profiles}/{len(profile_keys)}")

    enriched.sort(
        key=lambda item: (
            parse_int(item.get("semantic_scholar_citations")),
            len(item.get("papers", [])),
        ),
        reverse=True,
    )

    google_pool = [
        candidate
        for candidate in enriched
        if candidate.get("profile_query_status") in {"queried", "queried_s2_error"}
    ][:max_profiles]
    author_scholar_diagnostics: Dict[str, Any] = {"status": "not_started", "captcha_status": "none"}
    author_scholar_retry_events: List[Dict[str, Any]] = []
    author_driver = None
    author_debug_dir = ensure_dir(output / "scholar_debug")
    author_scholar_blocked = False
    if google_pool and skip_google_scholar_authors:
        author_scholar_diagnostics.update({"status": "skipped_by_user", "captcha_status": "skipped", "events": []})
    elif google_pool and scholar_captcha_action == "wait":
        print(
            "Opening a visible Google Scholar author-profile browser session. "
            "If a human verification page appears, complete it in that browser window."
        )
        author_driver = create_webdriver(scholar_browser)
        author_scholar_diagnostics.update(
            {
                "status": "ok",
                "browser": scholar_browser,
                "locale": scholar_locale,
                "events": [],
                "browser_pid": scholar_driver_state(author_driver).get("browser_pid", ""),
            }
        )
        append_scholar_event(author_scholar_diagnostics["events"], "author_browser_started", author_driver, browser=scholar_browser, locale=scholar_locale)
    elif google_pool:
        author_scholar_diagnostics.update({"status": "skipped_fail_mode", "events": []})
    try:
        for idx, candidate in enumerate(google_pool, 1):
            key = candidate["author_key"]
            if (
                key in google_cache
                and google_cache.get(key, {}).get("enrichment_version") == GOOGLE_AUTHOR_ENRICHMENT_VERSION
            ):
                gs = google_cache[key]
            elif skip_google_scholar_authors:
                gs = {
                    "match_status": "skipped_by_user",
                    "error": "google_scholar_author_profiles_skipped_by_user_no_cached_profile",
                    "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION,
                }
            elif author_scholar_blocked:
                gs = {
                    "match_status": "captcha_blocked_not_queried",
                    "error": "google_scholar_author_captcha_blocked_for_run",
                    "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION,
                }
            elif author_driver is not None:
                try:
                    gs = google_author_metrics_selenium(
                        author_driver,
                        candidate["name"],
                        [paper["citing_title"] for paper in candidate.get("papers", []) if paper.get("citing_title")],
                        scholar_locale,
                        min_delay,
                        max_delay,
                        author_debug_dir,
                        scholar_captcha_action,
                        scholar_captcha_timeout,
                        author_scholar_diagnostics["events"],
                    )
                except ScholarCaptchaError as exc:
                    gs = {"match_status": "error", "error": str(exc), "enrichment_version": GOOGLE_AUTHOR_ENRICHMENT_VERSION}
                    author_scholar_diagnostics["captcha_status"] = "blocked"
                    author_scholar_blocked = True
                    print(
                        "Google Scholar author captcha timed out; skipping remaining Scholar author profile queries for this run.",
                        file=sys.stderr,
                    )
            else:
                gs = google_author_metrics_with_interactive_retry(
                    session,
                    candidate,
                    scholar_locale,
                    min_delay,
                    max_delay,
                    output,
                    scholar_browser,
                    scholar_captcha_action,
                    scholar_captcha_timeout,
                    author_scholar_retry_events,
                )
                time.sleep(random.uniform(min_delay, max_delay))
            if gs.get("match_status") not in {"captcha_blocked_not_queried", "skipped_by_user"}:
                google_cache[key] = gs
                if idx % 10 == 0:
                    save_cache(google_cache_path, profile_cache)
            candidate["google_scholar_citations"] = parse_int(gs.get("citations"))
            candidate["google_scholar_profile_url"] = gs.get("profile_url", "")
            candidate["google_scholar_homepage_url"] = gs.get("homepage_url", "")
            candidate["google_scholar_affiliation"] = gs.get("affiliation", "")
            candidate["google_scholar_interests"] = gs.get("interests", "")
            candidate["google_scholar_match_status"] = gs.get("match_status", "")
            if idx % 20 == 0:
                label = "Google Scholar author profiles skipped" if skip_google_scholar_authors else "Google Scholar author profiles"
                print(f"{label}: {idx}/{len(google_pool)}")
    finally:
        if author_driver is not None:
            author_scholar_diagnostics["final_url"] = scholar_driver_state(author_driver).get("current_url", "")
            author_scholar_diagnostics["final_title"] = scholar_driver_state(author_driver).get("page_title", "")
            if author_scholar_diagnostics.get("captcha_status") != "blocked":
                events = author_scholar_diagnostics.get("events", [])
                if any(event.get("event") == "captcha_detected" for event in events):
                    author_scholar_diagnostics["captcha_status"] = "resolved"
            append_scholar_event(author_scholar_diagnostics["events"], "author_browser_quit", author_driver)
            author_driver.quit()

    for candidate in enriched:
        gs_citations = parse_int(candidate.get("google_scholar_citations"))
        gs_status = str(candidate.get("google_scholar_match_status") or "")
        if gs_citations and gs_status in {"exact_name_paper_match", "initial_name_paper_match"}:
            candidate["selected_citation_count"] = gs_citations
            candidate["selected_citation_source"] = "google-scholar"
        else:
            candidate["selected_citation_count"] = parse_int(candidate.get("semantic_scholar_citations"))
            candidate["selected_citation_source"] = "semantic-scholar"
        candidate["citing_paper_count"] = len(candidate.get("papers", []))
        paper_counts = [parse_int(paper.get("citation_count")) for paper in candidate.get("papers", [])]
        candidate["max_citing_paper_citation_count"] = max(paper_counts) if paper_counts else 0
        candidate["sum_citing_paper_citation_count"] = sum(paper_counts)
        candidate["citing_titles"] = " | ".join(sorted({paper.get("citing_title", "") for paper in candidate.get("papers", []) if paper.get("citing_title")}))
        if candidate.get("profile_query_status") == "queried_s2_error":
            candidate["notes"] = f"semantic_scholar_error: {text_value(s2_cache.get(author_metric_cache_key(candidate, candidate.get('name', '')), {}).get('error'))[:300]}"
        elif candidate.get("profile_query_status") != "queried":
            candidate["notes"] = "external_profile_not_queried_due_to_profile_limit"
        elif gs_status in {"exact_name_paper_match", "initial_name_paper_match"}:
            candidate["notes"] = ""
        else:
            candidate["notes"] = f"google_scholar_{gs_status or 'not_queried'}"

    non_target_enriched = [item for item in enriched if not item.get("is_target_author")]
    non_target_enriched.sort(
        key=lambda item: (
            parse_int(item.get("selected_citation_count")),
            parse_int(item.get("semantic_scholar_h_index")),
            parse_int(item.get("citing_paper_count")),
        ),
        reverse=True,
    )
    author_rows = []
    for rank, candidate in enumerate(non_target_enriched, 1):
        candidate["rank"] = rank

    wiki_by_key: Dict[str, Dict[str, Any]] = {}
    expert_rank_limit = max(100, top_n)
    top_paper_author_keys = top_author_keys_for_papers(papers, enriched)
    target_keys: List[str] = []
    seen_target_keys: set[str] = set()
    for candidate in non_target_enriched[:expert_rank_limit]:
        key = candidate["author_key"]
        if key not in seen_target_keys:
            target_keys.append(key)
            seen_target_keys.add(key)
    by_key = {candidate["author_key"]: candidate for candidate in non_target_enriched}
    for key in top_paper_author_keys:
        if key in by_key and key not in seen_target_keys:
            target_keys.append(key)
            seen_target_keys.add(key)
        if len(target_keys) >= 150:
            break
    target_keys = target_keys[:150]
    wiki_targets = [by_key[key] for key in target_keys if key in by_key]
    selected_wiki_keys = {candidate["author_key"] for candidate in wiki_targets}
    for candidate in non_target_enriched:
        candidate["_expert_query_selected"] = candidate["author_key"] in selected_wiki_keys
    wiki_jobs = [
        (candidate["author_key"], candidate["name"])
        for candidate in wiki_targets
        if wiki_cache.get(candidate["author_key"], {}).get("enrichment_version") != PROFILE_ENRICHMENT_VERSION
    ]
    if wiki_jobs:
        if wiki_workers > 1:
            completed = 0
            with ThreadPoolExecutor(max_workers=min(wiki_workers, len(wiki_jobs))) as executor:
                futures = {
                    executor.submit(fetch_wikipedia_profile, key, name): key
                    for key, name in wiki_jobs
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        _, wiki = future.result()
                    except Exception as exc:
                        wiki = {"error": str(exc), "is_notable": False}
                    wiki_cache[key] = wiki
                    completed += 1
                    if completed % 10 == 0 or completed == len(wiki_jobs):
                        print(f"Wikipedia/Wikidata profiles fetched: {completed}/{len(wiki_jobs)}")
        else:
            for completed, (key, name) in enumerate(wiki_jobs, 1):
                wiki_cache[key] = wikipedia_summary(make_session(), name)
                if completed % 10 == 0 or completed == len(wiki_jobs):
                    print(f"Wikipedia/Wikidata profiles fetched: {completed}/{len(wiki_jobs)}")
    homepage_jobs = []
    for candidate in wiki_targets:
        key = candidate["author_key"]
        homepage_url = homepage_url_for_author(candidate)
        source_context = "direct_homepage"
        if homepage_url and plausible_personal_homepage_url(candidate.get("google_scholar_homepage_url", "")) == homepage_url:
            source_context = "google_scholar_homepage"
        elif homepage_url and plausible_personal_homepage_url(candidate.get("semantic_scholar_homepage_url", "")) == homepage_url:
            source_context = "semantic_scholar_homepage"
        cached_homepage = wiki_cache.get(key, {}).get("homepage_profile", {})
        if (
            homepage_url
            and (
                cached_homepage.get("enrichment_version") != PROFILE_ENRICHMENT_VERSION
                or cached_homepage.get("homepage_url", "") != homepage_url
            )
        ):
            affiliations = " | ".join(
                part
                for part in [
                    str(candidate.get("semantic_scholar_affiliations") or "").strip(),
                    str(candidate.get("google_scholar_affiliation") or "").strip(),
                ]
                if part
            )
            interests = str(candidate.get("google_scholar_interests") or "").strip()
            homepage_jobs.append((key, candidate["name"], homepage_url, affiliations, interests, source_context))
    if homepage_jobs:
        if wiki_workers > 1:
            completed = 0
            with ThreadPoolExecutor(max_workers=min(wiki_workers, len(homepage_jobs))) as executor:
                futures = {
                    executor.submit(fetch_homepage_profile, key, name, homepage_url, affiliations, interests, source_context): key
                    for key, name, homepage_url, affiliations, interests, source_context in homepage_jobs
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        _, homepage_profile = future.result()
                    except Exception as exc:
                        homepage_profile = {"homepage_query_status": "homepage_error", "homepage_error": str(exc)[:300]}
                    wiki_cache.setdefault(key, {})["homepage_profile"] = homepage_profile
                    completed += 1
                    if completed % 10 == 0 or completed == len(homepage_jobs):
                        print(f"Personal/school homepages fetched: {completed}/{len(homepage_jobs)}")
        else:
            for completed, (key, name, homepage_url, affiliations, interests, source_context) in enumerate(homepage_jobs, 1):
                wiki_cache.setdefault(key, {})["homepage_profile"] = homepage_profile_summary(make_session(), homepage_url, name, affiliations, interests, source_context)
                if completed % 10 == 0 or completed == len(homepage_jobs):
                    print(f"Personal/school homepages fetched: {completed}/{len(homepage_jobs)}")
    homepage_search_jobs = []
    for candidate in wiki_targets:
        if len(homepage_search_jobs) >= homepage_search_limit:
            break
        key = candidate["author_key"]
        homepage_url = homepage_url_for_author(candidate)
        cached_homepage = wiki_cache.get(key, {}).get("homepage_profile", {})
        cached_status = str(cached_homepage.get("homepage_query_status") or "")
        has_useful_homepage = bool(
            homepage_url
            or cached_homepage.get("homepage_url")
            or cached_homepage.get("homepage_summary")
            or cached_homepage.get("homepage_evidence")
        )
        if has_useful_homepage and cached_homepage.get("enrichment_version") == PROFILE_ENRICHMENT_VERSION:
            continue
        if cached_homepage.get("enrichment_version") == PROFILE_ENRICHMENT_VERSION and cached_status in {"homepage_search_found", "homepage_search_found_verified", "homepage_search_not_found", "homepage_search_rejected_identity"}:
            continue
        affiliations = " | ".join(
            part
            for part in [
                str(candidate.get("semantic_scholar_affiliations") or "").strip(),
                str(candidate.get("google_scholar_affiliation") or "").strip(),
            ]
            if part
        )
        interests = str(candidate.get("google_scholar_interests") or "").strip()
        homepage_search_jobs.append((key, candidate["name"], affiliations, interests))
    if homepage_search_jobs:
        if wiki_workers > 1:
            completed = 0
            with ThreadPoolExecutor(max_workers=min(wiki_workers, len(homepage_search_jobs))) as executor:
                futures = {
                    executor.submit(fetch_homepage_search_profile, key, name, affiliations, interests): key
                    for key, name, affiliations, interests in homepage_search_jobs
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        _, homepage_profile = future.result()
                    except Exception as exc:
                        homepage_profile = {"homepage_query_status": "homepage_search_error", "homepage_error": str(exc)[:300]}
                    wiki_cache.setdefault(key, {})["homepage_profile"] = homepage_profile
                    completed += 1
                    if completed % 10 == 0 or completed == len(homepage_search_jobs):
                        print(f"Deep-search author homepages fetched: {completed}/{len(homepage_search_jobs)}")
        else:
            for completed, (key, name, affiliations, interests) in enumerate(homepage_search_jobs, 1):
                wiki_cache.setdefault(key, {})["homepage_profile"] = homepage_search_summary(make_session(), name, affiliations, interests)
                if completed % 10 == 0 or completed == len(homepage_search_jobs):
                    print(f"Deep-search author homepages fetched: {completed}/{len(homepage_search_jobs)}")
    for candidate in wiki_targets:
        key = candidate["author_key"]
        wiki_by_key[key] = wiki_cache.get(key, {})
    for candidate in non_target_enriched:
        author_rows.append(author_report_row(candidate, wiki_by_key.get(candidate["author_key"], {})))
    author_report_by_key = {row["author_key"]: row for row in author_rows}

    papers, paper_authors = build_paper_author_outputs(papers, enriched, author_report_by_key)
    locations_df = read_locations(output)
    notable_rows = []
    notable_keys = {row["author_key"] for row in author_rows if row.get("is_notable")}
    expert_by_key = {row["author_key"]: row for row in author_rows}
    coverage_by_title = {
        normalize_text(row.get("citing_title", "")): row for row in papers.to_dict("records")
    } if not papers.empty else {}
    locations_by_title: Dict[str, List[Dict[str, Any]]] = {}
    if not locations_df.empty:
        for row in locations_df.to_dict("records"):
            locations_by_title.setdefault(normalize_text(row.get("citing_title", "")), []).append(row)
    for candidate in non_target_enriched:
        if candidate["author_key"] not in notable_keys:
            continue
        expert = expert_by_key[candidate["author_key"]]
        for paper in candidate.get("papers", []):
            title = paper.get("citing_title", "")
            title_key = normalize_text(title)
            coverage = coverage_by_title.get(title_key, {})
            location_rows = locations_by_title.get(title_key, [])
            pages = coverage.get("pages", "") or ";".join(
                str(page)
                for page in sorted(
                    {
                        parse_int(item.get("page"))
                        for item in location_rows
                        if parse_int(item.get("page"))
                    }
                )
            )
            citation_markers = "; ".join(
                sorted({str(item.get("citation_marker", "")).strip() for item in location_rows if str(item.get("citation_marker", "")).strip()})
            ) or coverage.get("reference_marker", "")
            status = coverage.get("analysis_status", "")
            location_count = coverage.get("location_count", "") or str(len(location_rows) if location_rows else "")
            if parse_int(location_count):
                location_status = f"located on pages {pages}" if pages else "located in body"
            else:
                location_status = status or "not_analyzed"
            context_sample = ""
            if location_rows:
                context_sample = text_value(location_rows[0].get("context"))[:600]
            notable_rows.append(
                {
                    "author_name": candidate.get("name", ""),
                    "selected_citation_count": candidate.get("selected_citation_count", ""),
                    "selected_citation_source": candidate.get("selected_citation_source", ""),
                    "notable_reason": expert.get("notable_reason", ""),
                    "wikipedia_url": expert.get("wikipedia_url", ""),
                    "citing_title": title,
                    "publication_year": paper.get("publication_year", ""),
                    "venue": paper.get("venue", ""),
                    "source_platforms": paper.get("source_platforms", ""),
                    "analysis_status": status,
                    "location_count": location_count,
                    "pages": pages,
                    "citation_markers": citation_markers,
                    "citation_location_status": location_status,
                    "citation_context_sample": context_sample,
                }
            )

    candidates_path = output / "author_candidates.csv"
    experts_path = output / "author_expert_profiles.csv"
    notable_path = output / "notable_scholar_citing_papers.csv"
    expert_status_counts = (
        pd.Series([row.get("expert_query_status", "") for row in author_rows])
        .replace("", "unknown")
        .value_counts()
        .to_dict()
        if author_rows
        else {}
    )
    expert_rejection_counts = (
        pd.Series([row.get("expert_rejection_reason", "") for row in author_rows if row.get("expert_rejection_reason")])
        .value_counts()
        .to_dict()
        if author_rows
        else {}
    )
    google_match_counts = (
        pd.Series([item.get("google_scholar_match_status", "") for item in non_target_enriched])
        .replace("", "not_queried")
        .value_counts()
        .to_dict()
        if non_target_enriched
        else {}
    )
    google_selected_count = sum(1 for item in non_target_enriched if item.get("selected_citation_source") == "google-scholar")
    notes = append_run_notes(
        output,
        {
            "authors.total_candidates": len(enriched),
            "authors.non_target_candidates": len(non_target_enriched),
            "authors.target_authors_excluded": sum(1 for item in enriched if item.get("is_target_author")),
            "authors.profile_queries": queried_profiles,
            "authors.semantic_scholar_workers": author_workers,
            "authors.google_scholar.skip_author_profiles": skip_google_scholar_authors,
            "authors.google_scholar.browser": scholar_browser,
            "authors.google_scholar.captcha_action": scholar_captcha_action,
            "authors.google_scholar.captcha_timeout": scholar_captcha_timeout,
            "authors.google_scholar.browser_status": author_scholar_diagnostics.get("status", ""),
            "authors.google_scholar.captcha_status": author_scholar_diagnostics.get("captcha_status", ""),
            "authors.google_scholar.cookie_count": author_scholar_diagnostics.get("cookie_count", ""),
            "authors.google_scholar.final_url": author_scholar_diagnostics.get("final_url", ""),
            "authors.google_scholar.page_title": author_scholar_diagnostics.get("final_title", ""),
            "authors.google_scholar.events_json": json.dumps(author_scholar_diagnostics.get("events", []), ensure_ascii=False),
            "authors.google_scholar.retry_events_json": json.dumps(author_scholar_retry_events, ensure_ascii=False),
            "authors.google_scholar.match_status_counts_json": json.dumps(google_match_counts, ensure_ascii=False),
            "authors.google_scholar.selected_count": google_selected_count,
            "authors.wikipedia_checked": len(wiki_targets),
            "authors.wikipedia_scope": "top_100_non_target_plus_top_author_per_paper_cap_150",
            "authors.wikipedia_workers": wiki_workers,
            "authors.homepage_checked": len(homepage_jobs),
            "authors.homepage_search_checked": len(homepage_search_jobs),
            "authors.expert_status_counts_json": json.dumps(expert_status_counts, ensure_ascii=False),
            "authors.expert_rejection_counts_json": json.dumps(expert_rejection_counts, ensure_ascii=False),
        },
    )
    report = write_report(
        output,
        {
            "papers": papers,
            "paper_authors": paper_authors,
            "authors": pd.DataFrame(author_rows, columns=AUTHOR_REPORT_COLUMNS),
            "notable_citations": pd.DataFrame(notable_rows, columns=NOTABLE_COLUMNS),
            "run_notes": notes,
        },
        export_legacy_csv=export_legacy_enabled(args),
    )
    if export_legacy_enabled(args):
        write_csv(candidates_path, author_rows, AUTHOR_REPORT_COLUMNS)
        expert_rows = [row for row in author_rows if parse_int(row.get("rank")) <= top_n]
        write_csv(experts_path, expert_rows, AUTHOR_REPORT_COLUMNS)
        write_csv(notable_path, notable_rows, NOTABLE_COLUMNS)
    save_cache(google_cache_path, profile_cache)
    save_cache(wiki_cache_path, wiki_cache)
    print(f"Saved citation report: {report}")
    print(f"Saved authors sheet: {len(author_rows)} non-target authors")
    print(f"Saved notable citations sheet: {len(notable_rows)} rows")
    return report, report, report


def cmd_authors(args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    return enrich_authors(args)


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
    input_value = getattr(args, "input", "") or ""
    input_path = Path(input_value) if input_value else Path()
    if input_value and input_path.is_file():
        df = pd.read_csv(input_path, dtype=str).fillna("")
    else:
        df = read_papers(output)
    df = clean_frame_for_report(df, PAPER_COLUMNS if "dedupe_key" in df.columns else CITING_COLUMNS)
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
    papers = clean_frame_for_report(pd.DataFrame(manifest), PAPER_COLUMNS)
    manual = clean_frame_for_report(pd.DataFrame(manual_todo), MANUAL_COLUMNS)
    notes = append_run_notes(
        output,
        {
            "download.total": len(manifest),
            "download.downloaded": sum(1 for row in manifest if row.get("download_status") == "downloaded"),
            "download.failed": len(failures),
            "download.workers": workers,
        },
    )
    report = write_report(
        output,
        {
            "papers": papers,
            "manual_download_todo": manual,
            "run_notes": notes,
        },
        export_legacy_csv=export_legacy_enabled(args),
    )
    if export_legacy_enabled(args):
        pd.DataFrame(manifest).to_csv(manifest_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(failures).to_csv(failures_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(manual_todo).to_csv(manual_todo_path, index=False, encoding="utf-8-sig")
        print(f"Saved download manifest: {manifest_path}")
        print(f"Saved download failures: {failures_path}")
        print(f"Saved manual download todo list: {manual_todo_path}")
    print(f"Saved citation report: {report}")
    return manifest_path, failures_path


def load_target_for_analysis(args: argparse.Namespace) -> Dict[str, Any]:
    if args.target_json and Path(args.target_json).exists():
        return json.loads(Path(args.target_json).read_text(encoding="utf-8"))
    target = load_target(args.output)
    if target:
        return target
    target_path = Path(args.output) / "target.json"
    if target_path.exists():
        return json.loads(target_path.read_text(encoding="utf-8"))
    return {"title": args.target_title or ""}


def rows_for_analysis(args: argparse.Namespace) -> List[Dict[str, Any]]:
    papers = read_papers(args.output)
    manual_df = read_manual_todo(args.output)
    rows: List[Dict[str, Any]] = []
    if not papers.empty:
        rows = papers.to_dict("records")
    if not manual_df.empty:
        existing = {
            str(Path(row.get("pdf_path", "")).resolve())
            for row in rows
            if row.get("pdf_path") and Path(row.get("pdf_path", "")).exists()
        }
        for row in manual_df.to_dict("records"):
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
    pdf_dir = Path(args.pdf_dir) if getattr(args, "pdf_dir", "") else Path(args.output) / "pdfs"
    for pdf in pdf_dir.glob("*.pdf"):
        key = safe_filename(pdf.stem, 110)
        row = by_name.get(key, {})
        row["pdf_path"] = str(pdf.resolve())
        rows.append(row)
    return rows


def merge_coverage_into_papers(papers: pd.DataFrame, coverage: List[Dict[str, Any]]) -> pd.DataFrame:
    papers = clean_frame_for_report(papers, PAPER_COLUMNS)
    coverage_by_title = {
        normalize_text(row.get("citing_title", "")): row
        for row in coverage
        if row.get("citing_title")
    }
    seen_titles: set[str] = set()
    rows: List[Dict[str, Any]] = []
    coverage_update_cols = [
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
    for row in papers.to_dict("records"):
        key = normalize_text(row.get("citing_title", ""))
        update = coverage_by_title.get(key)
        if update:
            seen_titles.add(key)
            for column in coverage_update_cols:
                if column in update:
                    row[column] = update.get(column, "")
        rows.append(row)
    for row in coverage:
        key = normalize_text(row.get("citing_title", ""))
        if not key or key in seen_titles:
            continue
        merged = {column: "" for column in PAPER_COLUMNS}
        for column in PAPER_COLUMNS:
            if column in row:
                merged[column] = row.get(column, "")
        rows.append(merged)
    return clean_frame_for_report(pd.DataFrame(rows), PAPER_COLUMNS)


def dashboard_records(df: pd.DataFrame, columns: Sequence[str]) -> List[Dict[str, Any]]:
    subset = df.reindex(columns=columns).fillna("")
    return [{key: text_value(value) for key, value in row.items()} for row in subset.to_dict("records")]


def dashboard_counts(series: pd.Series) -> Dict[str, int]:
    return {str(key): int(value) for key, value in series.fillna("Unknown").value_counts().items()}


def latest_run_note_values(notes: pd.DataFrame) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if notes.empty:
        return values
    for row in notes.fillna("").to_dict("records"):
        key = str(row.get("key") or "")
        value = text_value(row.get("value"))
        note_key = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+", "", key)
        if note_key:
            values[note_key] = value
    return values


def nonempty_counts(df: pd.DataFrame, column: str) -> Dict[str, int]:
    if df.empty or column not in df:
        return {}
    series = df[column].fillna("").astype(str).str.strip()
    series = series[series.ne("")]
    return {str(key): int(value) for key, value in series.value_counts().items()}


def build_dashboard_payload(output: Path) -> Dict[str, Any]:
    target = load_target(output)
    papers = read_papers(output)
    locations = read_locations(output)
    sheets = load_report_sheets(output)
    authors = sheets["authors"]
    notable = sheets["notable_citations"]
    downloaded = sheets["downloaded_papers"]
    download_failures = sheets["download_failures"]
    run_notes = sheets["run_notes"]
    run_note_values = latest_run_note_values(run_notes)
    if papers.empty:
        raise RuntimeError(f"Cannot build dashboard; missing papers sheet in {report_path(output)} or legacy citing_papers.csv")

    normalized_titles = (
        papers["citing_title"].fillna("").astype(str).str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    )
    year_counts = (
        papers["publication_year"]
        .fillna("Unknown")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .value_counts()
        .sort_index()
    )
    paper_location_counts = pd.to_numeric(papers["location_count"], errors="coerce").fillna(0).astype(int)
    papers_ranked = papers.assign(_location_count=paper_location_counts)
    top_locations = (
        papers_ranked[papers_ranked["_location_count"] > 0]
        .sort_values(["_location_count", "citing_title"], ascending=[False, True])
        .head(12)
    )
    if not authors.empty and "rank" in authors:
        top_authors = (
            authors.assign(_rank=pd.to_numeric(authors["rank"], errors="coerce"))
            .sort_values("_rank")
            .head(20)
        )
        expert_profiles = (
            authors.assign(_rank=pd.to_numeric(authors["rank"], errors="coerce"))
            .sort_values("_rank")
            .head(100)
        )
    else:
        top_authors = authors
        expert_profiles = authors
    external = target.get("externalIds") or {}
    has_author_files = not authors.empty or not notable.empty
    google_rows = int(papers["source_platforms"].fillna("").astype(str).str.contains("google-scholar", regex=False).sum())
    semantic_rows = int(papers["source_platforms"].fillna("").astype(str).str.contains("semantic-scholar", regex=False).sum())
    expert_status_series = (
        authors["expert_query_status"].fillna("").astype(str).str.strip()
        if not authors.empty and "expert_query_status" in authors
        else pd.Series(dtype=str)
    )
    source_status = {
        "googleScholarRows": google_rows,
        "semanticScholarRows": semantic_rows,
        "googleScholarRawRows": run_note_values.get("find.google_scholar.raw_rows", ""),
        "googleScholarStatus": run_note_values.get("find.google_scholar.status", ""),
        "googleScholarPartialFailure": run_note_values.get("find.google_scholar.partial_failure", ""),
        "googleScholarCaptchaStatus": run_note_values.get("find.google_scholar.captcha_status", "") or run_note_values.get("find.google_scholar_status", ""),
        "googleScholarReportedCitedByCount": run_note_values.get("find.google_scholar.reported_cited_by_count", ""),
        "googleScholarTargetFound": run_note_values.get("find.google_scholar.target_found", ""),
        "googleScholarTargetTitle": run_note_values.get("find.google_scholar.target_title", ""),
        "googleScholarTargetCitedByUrl": run_note_values.get("find.google_scholar.target_cited_by_url", ""),
        "googleScholarCurrentUrl": run_note_values.get("find.google_scholar.current_url", ""),
        "googleScholarPageTitle": run_note_values.get("find.google_scholar.page_title", ""),
        "googleScholarBrowserPid": run_note_values.get("find.google_scholar.browser_pid", ""),
        "googleScholarAttempted": run_note_values.get("find.google_scholar.attempted", "") or run_note_values.get("find.google_scholar_attempted", ""),
        "requireGoogleScholar": run_note_values.get("find.require_google_scholar", ""),
        "scholarCaptchaAction": run_note_values.get("find.scholar_captcha_action", ""),
        "findStatus": run_note_values.get("find.status", ""),
        "platformErrors": run_note_values.get("find.platform_errors_json", ""),
        "authorScholarBrowserStatus": run_note_values.get("authors.google_scholar.browser_status", ""),
        "authorScholarCaptchaStatus": run_note_values.get("authors.google_scholar.captcha_status", ""),
        "authorScholarSkipAuthorProfiles": run_note_values.get("authors.google_scholar.skip_author_profiles", ""),
        "authorScholarCookieCount": run_note_values.get("authors.google_scholar.cookie_count", ""),
        "authorScholarSelectedCount": run_note_values.get("authors.google_scholar.selected_count", ""),
        "authorScholarMatchStatusCounts": run_note_values.get("authors.google_scholar.match_status_counts_json", ""),
        "authorScholarPageTitle": run_note_values.get("authors.google_scholar.page_title", ""),
        "authorScholarFinalUrl": run_note_values.get("authors.google_scholar.final_url", ""),
    }
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
            "citingRows": int(len(papers)),
            "titleUniqueRows": int(normalized_titles.nunique()),
            "titleDuplicateGroups": int((normalized_titles.value_counts() > 1).sum()),
            "downloaded": int((papers["download_status"] == "downloaded").sum()),
            "failed": int((papers["download_status"] == "failed").sum()),
            "locationRows": int(len(locations)),
            "locatedPapers": int(locations["citing_title"].nunique()) if len(locations) else 0,
            "positiveLocations": int(locations["is_positive"].astype(str).str.lower().eq("true").sum()) if "is_positive" in locations else 0,
            "authorRows": int(len(authors)),
            "notableScholars": int(authors["is_notable"].astype(str).str.lower().eq("true").sum()) if not authors.empty and "is_notable" in authors else 0,
            "notableCitingRows": int(len(notable)),
            "downloadedPaperRows": int(len(downloaded)),
            "downloadFailureRows": int(len(download_failures)),
            "hasAuthorFiles": bool(has_author_files),
            "googleScholarRows": google_rows,
            "semanticScholarRows": semantic_rows,
            "expertQueried": int((expert_status_series.ne("") & (expert_status_series != "not_queried_outside_expert_scope")).sum()) if len(expert_status_series) else 0,
        },
        "sourceStatus": source_status,
        "expertRejections": nonempty_counts(authors, "expert_rejection_reason"),
        "expertStatuses": nonempty_counts(authors, "expert_query_status"),
        "charts": {
            "sourcePlatforms": dashboard_counts(papers["source_platforms"]),
            "publicationYears": {str(key): int(value) for key, value in year_counts.items()},
            "downloadStatus": dashboard_counts(papers["download_status"]),
            "analysisStatus": dashboard_counts(papers["analysis_status"]),
            "matchType": dashboard_counts(locations["match_type"]) if len(locations) else {},
        },
        "topLocations": dashboard_records(
            top_locations.assign(location_count=top_locations["_location_count"].astype(str)),
            ["citing_title", "analysis_status", "location_count", "pages", "reference_marker", "source_platforms"],
        ),
        "authors": dashboard_records(
            top_authors,
            [
                "rank",
                "name",
                "selected_citation_count",
                "selected_citation_source",
                "google_scholar_citations",
                "semantic_scholar_citations",
                "semantic_scholar_h_index",
                "citing_paper_count",
                "citing_titles",
                "google_scholar_profile_url",
                "google_scholar_homepage_url",
                "google_scholar_affiliation",
                "google_scholar_interests",
                "semantic_scholar_profile_url",
                "semantic_scholar_homepage_url",
                "semantic_scholar_affiliations",
                "wikipedia_url",
                "academic_titles",
                "honors_awards",
                "professional_memberships",
                "leadership_roles",
                "profile_affiliations",
                "research_interests",
                "personal_homepage_url",
                "personal_homepage_evidence",
                "personal_homepage_summary",
                "personal_homepage_identity_status",
                "personal_homepage_identity_confidence",
                "personal_homepage_identity_evidence",
                "personal_homepage_rejection_reason",
                "profile_evidence_sources",
                "notability_confidence",
                "is_notable",
                "notable_reason",
            ],
        ),
        "experts": dashboard_records(
            expert_profiles,
            [
                "rank",
                "name",
                "selected_citation_count",
                "selected_citation_source",
                "semantic_scholar_h_index",
                "google_scholar_profile_url",
                "google_scholar_homepage_url",
                "google_scholar_affiliation",
                "google_scholar_interests",
                "semantic_scholar_profile_url",
                "semantic_scholar_homepage_url",
                "semantic_scholar_affiliations",
                "wikipedia_title",
                "wikipedia_url",
                "wikidata_id",
                "wikidata_description",
                "wikipedia_summary",
                "wikipedia_evidence",
                "wikidata_evidence",
                "academic_titles",
                "honors_awards",
                "professional_memberships",
                "leadership_roles",
                "profile_affiliations",
                "research_interests",
                "personal_homepage_url",
                "personal_homepage_evidence",
                "personal_homepage_summary",
                "personal_homepage_identity_status",
                "personal_homepage_identity_confidence",
                "personal_homepage_identity_evidence",
                "personal_homepage_rejection_reason",
                "profile_evidence_sources",
                "notability_confidence",
                "expert_query_status",
                "expert_rejection_reason",
                "is_notable",
                "notable_reason",
            ],
        ),
        "notableCitations": dashboard_records(
            notable,
            [
                "author_name",
                "selected_citation_count",
                "selected_citation_source",
                "notable_reason",
                "wikipedia_url",
                "citing_title",
                "publication_year",
                "venue",
                "source_platforms",
                "analysis_status",
                "location_count",
                "pages",
                "citation_markers",
                "citation_location_status",
                "citation_context_sample",
            ],
        ),
        "papers": dashboard_records(
            papers,
            [
                "citing_title",
                "citing_authors",
                "publication_year",
                "venue",
                "doi",
                "url",
                "citation_count",
                "source_platforms",
                "download_status",
                "analysis_status",
                "location_count",
                "pages",
                "reference_marker",
                "top_author_name",
                "top_author_selected_citation_count",
                "top_author_profile_url",
                "top_author_homepage_url",
                "top_author_status",
                "reference_evidence",
                "failure_reason",
                "abstract",
            ],
        ),
        "downloadedPapers": dashboard_records(
            downloaded,
            [
                "citing_title",
                "publication_year",
                "venue",
                "doi",
                "url",
                "pdf_path",
                "download_status",
                "download_url",
                "source_platforms",
                "candidate_urls",
            ],
        ),
        "downloadFailures": dashboard_records(
            download_failures,
            [
                "citing_title",
                "publication_year",
                "venue",
                "doi",
                "url",
                "pdf_url",
                "open_access_pdf_url",
                "download_status",
                "failure_reason",
                "candidate_urls",
                "expected_pdf_path",
                "manual_pdf_path",
                "source_platforms",
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
    .status-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
    .status-item { border:1px solid #edf0f4; border-radius:8px; padding:10px; background:#fbfcfd; min-height:72px; }
    .status-value { margin-top:5px; font-weight:700; color:#26313d; word-break:break-word; }
    input,select { width:100%; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font:inherit; background:#fff; color:var(--ink); }
    table { width:100%; border-collapse:collapse; table-layout:fixed; }
    th,td { padding:9px 8px; border-bottom:1px solid #edf0f4; vertical-align:top; text-align:left; }
    th { color:#475569; font-size:12px; background:#fafafa; position:sticky; top:0; z-index:1; }
    td { color:#26313d; word-wrap:break-word; }
    .table-wrap { max-height:520px; overflow:auto; border:1px solid var(--line); border-radius:8px; }
    .pill { display:inline-flex; align-items:center; min-height:22px; padding:2px 7px; border-radius:999px; font-size:12px; border:1px solid transparent; white-space:nowrap; }
    .ok { color:#166534; background:#ecfdf3; border-color:#bbf7d0; } .warn { color:#92400e; background:#fffbeb; border-color:#fde68a; } .bad { color:#9f1239; background:#fff1f2; border-color:#fecdd3; } .neutral { color:#475569; background:#f8fafc; border-color:#e2e8f0; }
    .context { color:#334155; max-width:760px; } .muted { color:var(--muted); }
    .hidden { display:none !important; }
    @media (max-width:980px) { .title-row,.filters { grid-template-columns:1fr; } .links { justify-content:flex-start; } .stats,.status-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .span-4,.span-5,.span-7,.span-12 { grid-column:span 12; } }
    @media (max-width:620px) { .status-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header><div class="wrap title-row"><div><h1>引用调查可视化</h1><div class="subline" id="targetMeta"></div></div><nav class="links"><a class="button" href="citation_report.xlsx">综合报告 Excel</a></nav></div></header>
  <main class="wrap">
    <section class="stats" id="stats"></section>
    <section class="panel"><h2>数据源状态</h2><div class="panel-body" id="sourceStatus"></div></section>
    <section class="grid">
      <article class="panel span-4"><h2>来源分布</h2><div class="panel-body" id="sourceChart"></div></article>
      <article class="panel span-4"><h2>下载状态</h2><div class="panel-body" id="downloadChart"></div></article>
      <article class="panel span-4"><h2>第三步覆盖状态</h2><div class="panel-body" id="coverageChart"></div></article>
      <article class="panel span-5"><h2>发表年份</h2><div class="panel-body" id="yearChart"></div></article>
      <article class="panel span-7"><h2>引用位置最多的论文</h2><div class="panel-body" id="topChart"></div></article>
      <article class="panel span-5 author-only" id="authorPanel"><h2>高引用作者排行</h2><div class="panel-body" id="authorChart"></div></article>
      <article class="panel span-7 author-only" id="notablePanel"><h2>著名学者引用</h2><div class="panel-body"><div class="table-wrap"><table><thead><tr><th style="width:18%">学者</th><th style="width:14%">引用量</th><th style="width:24%">证据</th><th style="width:34%">引用论文</th><th style="width:10%">位置</th></tr></thead><tbody id="notableRows"></tbody></table></div></div></article>
      <article class="panel span-12 author-only" id="expertProfilePanel"><h2>作者画像、头衔与荣誉</h2><div class="panel-body"><div class="filters"><input id="expertSearch" placeholder="搜索作者、单位、研究方向、头衔、荣誉、会员身份、任职证据"><select id="expertNotableFilter"><option value="">全部作者证据</option><option value="true">仅著名学者</option><option value="false">非著名/证据不足</option></select><select id="expertSourceFilter"><option value="">全部证据来源</option></select></div><div class="table-wrap"><table><thead><tr><th style="width:14%">作者</th><th style="width:10%">引用量</th><th style="width:18%">单位/研究方向</th><th style="width:15%">头衔/职位</th><th style="width:15%">荣誉/奖项</th><th style="width:13%">会员/领导职务</th><th style="width:15%">证据/诊断</th></tr></thead><tbody id="expertRows"></tbody></table></div></div></article>
      <article class="panel span-12"><h2>调研论文信息与覆盖</h2><div class="panel-body"><div class="filters"><input id="paperSearch" placeholder="搜索论文、作者、venue、URL、DOI、摘要"><select id="statusFilter"></select><select id="sourceFilter"></select></div><div class="table-wrap"><table><thead><tr><th style="width:36%">论文信息</th><th style="width:6%">年份</th><th style="width:7%">引用</th><th style="width:11%">来源</th><th style="width:13%">覆盖/下载</th><th style="width:13%">最高引用作者</th><th style="width:7%">位置</th><th style="width:7%">链接</th></tr></thead><tbody id="paperRows"></tbody></table></div></div></article>
      <article class="panel span-12"><h2>下载明细</h2><div class="panel-body"><div class="filters"><input id="downloadSearch" placeholder="搜索下载论文、DOI、URL、失败原因、本地路径"><select id="downloadKindFilter"><option value="">全部下载记录</option><option value="downloaded">成功下载</option><option value="failed">未成功下载</option></select><select id="downloadSourceFilter"></select></div><div class="table-wrap"><table><thead><tr><th style="width:28%">论文</th><th style="width:8%">状态</th><th style="width:20%">PDF/本地路径</th><th style="width:22%">候选地址</th><th style="width:22%">失败原因/手动路径</th></tr></thead><tbody id="downloadRows"></tbody></table></div></div></article>
      <article class="panel span-12"><h2>可靠引用位置</h2><div class="panel-body"><div class="filters"><input id="locationSearch" placeholder="搜索论文、引用标记、上下文"><select id="matchFilter"></select><select id="positiveFilter"><option value="">全部情感/用途</option><option value="true">positive</option><option value="false">not positive</option></select></div><div class="table-wrap"><table><thead><tr><th style="width:25%">论文</th><th style="width:8%">页/行</th><th style="width:14%">标记</th><th style="width:14%">匹配类型</th><th style="width:39%">上下文</th></tr></thead><tbody id="locationRows"></tbody></table></div></div></article>
    </section>
  </main>
  <script id="payload" type="application/json">__DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById('payload').textContent);
    const colors = ['#0f766e','#2563eb','#b7791f','#be123c','#7c3aed','#15803d','#6b7280'];
    function esc(v){ return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch])); }
    function pillClass(v){ if(['downloaded','cited_in_body'].includes(v)) return 'ok'; if(['failed','pdf_not_downloaded','target_reference_not_found','pdf_missing','pdf_parse_failed'].includes(v)) return 'bad'; if(v==='target_reference_found_no_body_hits') return 'warn'; return 'neutral'; }
    function shortText(v,n=220){ const text=String(v||''); return text.length>n?text.slice(0,n)+'...':text; }
    function extLink(url,label){ return url?`<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(label)}</a>`:esc(label); }
    function barChart(id,obj,limit=12){ const entries=Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,limit); const max=Math.max(1,...entries.map(([,v])=>v)); document.getElementById(id).innerHTML='<div class="bars">'+entries.map(([label,value],idx)=>`<div class="bar-row"><div class="bar-label" title="${esc(label)}">${esc(label)}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(3,value/max*100)}%;background:${colors[idx%colors.length]}"></div></div><div class="bar-value">${value}</div></div>`).join('')+'</div>'; }
    function fillSelect(id,label,values){ const el=document.getElementById(id); el.innerHTML=`<option value="">${esc(label)}</option>`+[...new Set(values.filter(Boolean))].sort().map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join(''); }
    function renderTarget(){ const t=data.target; document.getElementById('targetMeta').innerHTML=[`目标论文：${esc(t.title)}`,`年份：${esc(t.year)}`,`Semantic Scholar citationCount：${esc(t.citationCount)}`,t.doi?`DOI：${esc(t.doi)}`:'',t.arxiv?`arXiv：${esc(t.arxiv)}`:''].filter(Boolean).map(x=>`<span>${x}</span>`).join(''); }
    function renderStats(){ const s=data.stats; const items=[['被引记录',s.citingRows,`${s.titleUniqueRows} 个标题去重后唯一项`],['Google Scholar',s.googleScholarRows||0,`${s.semanticScholarRows||0} 条含 Semantic Scholar 来源`],['PDF 下载成功',s.downloaded,`${s.downloadFailureRows ?? s.failed} 个未成功下载`],['可靠引用位置',s.locationRows,`覆盖 ${s.locatedPapers} 篇论文`]]; if(s.hasAuthorFiles){ items.push(['作者候选',s.authorRows||0,`${s.expertQueried||0} 人已查专家证据`],['著名学者',s.notableScholars||0,`${s.notableCitingRows||0} 条著名学者引用记录`]); } items.push(['Positive 位置',s.positiveLocations,'关键词启发式标记']); document.getElementById('stats').innerHTML=items.map(([label,value,note])=>`<article class="stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="note">${esc(note)}</div></article>`).join(''); }
    function parseCountMap(text){ if(!text) return {}; try{ const obj=JSON.parse(text); return obj&&typeof obj==='object'&&!Array.isArray(obj)?obj:{}; }catch(_){ return {}; } }
    function formatAuthorGsCounts(text){ const obj=parseCountMap(text); const matched=Number(obj.exact_name_paper_match||0)+Number(obj.initial_name_paper_match||0); const errors=Number(obj.error||0)+Number(obj.captcha_blocked_not_queried||0); const skipped=Number(obj.not_queried||0)+Number(obj.skipped_by_user||0); const other=Object.entries(obj).filter(([k])=>!['exact_name_paper_match','initial_name_paper_match','error','captcha_blocked_not_queried','not_queried','skipped_by_user'].includes(k)).map(([k,v])=>`${k} ${v}`).join('; '); const parts=[`matched ${matched}`,`errors ${errors}`,`skipped ${skipped}`]; if(other) parts.push(other); return Object.keys(obj).length?parts.join(' / '):''; }
    function meaningfulUrl(v){ const text=String(v||'').trim(); return !text||text==='data:,'||text.startsWith('data:')?'':text; }
    function renderSourceStatus(){
      const s=data.sourceStatus||{};
      const errors=s.platformErrors?shortText(s.platformErrors,260):'';
      const authorCountMap=parseCountMap(s.authorScholarMatchStatusCounts);
      const authorCounts=formatAuthorGsCounts(s.authorScholarMatchStatusCounts);
      const authorTotal=Object.values(authorCountMap).reduce((sum,v)=>sum+Number(v||0),0);
      const authorPage=[s.authorScholarPageTitle,meaningfulUrl(s.authorScholarFinalUrl)].filter(Boolean).join(' ');
      const authorSkip=String(s.authorScholarSkipAuthorProfiles||'').toLowerCase()==='true';
      const authorProfileValue=authorSkip?'Skipped for this refresh':(authorCounts||'not available');
      const authorProfileNote=authorSkip?`${authorTotal||0} author profiles left to Google Scholar; citation counts use Semantic Scholar fallback.`:(authorPage||'Google Scholar author profile lookup diagnostics.');
      const gsNote=[`raw ${s.googleScholarRawRows||0}`,`captcha ${s.googleScholarCaptchaStatus||'unknown'}`,`attempted ${s.googleScholarAttempted||'unknown'}`,s.googleScholarStatus?`status ${s.googleScholarStatus}`:'',s.googleScholarPartialFailure?`partial: ${shortText(s.googleScholarPartialFailure,120)}`:''].filter(Boolean).join('; ');
      const items=[['Google Scholar rows',s.googleScholarRows ?? 0,gsNote],['Semantic Scholar rows',s.semanticScholarRows ?? 0,`find status ${s.findStatus||'unknown'}`],['GS target',s.googleScholarTargetFound||'unknown',s.googleScholarTargetTitle||''],['Reported cited-by',s.googleScholarReportedCitedByCount||'',s.googleScholarTargetCitedByUrl||''],['Find browser PID',s.googleScholarBrowserPid||'',`captcha action ${s.scholarCaptchaAction||''}`],['Last GS page',s.googleScholarPageTitle||'',meaningfulUrl(s.googleScholarCurrentUrl)],['Require GS',String(s.requireGoogleScholar||false),errors],['Author GS browser',s.authorScholarBrowserStatus||'not_run',`captcha ${s.authorScholarCaptchaStatus||'unknown'}; cookies ${s.authorScholarCookieCount||0}; selected ${s.authorScholarSelectedCount||0}`],['Author GS profiles',authorProfileValue,authorProfileNote]];
      document.getElementById('sourceStatus').innerHTML=`<div class="status-grid">${items.map(([label,value,note])=>`<div class="status-item"><div class="label">${esc(label)}</div><div class="status-value">${esc(value||'')}</div><div class="note">${esc(note||'')}</div></div>`).join('')}</div>`;
    }
    function renderPaperRows(){ const q=document.getElementById('paperSearch').value.toLowerCase(); const status=document.getElementById('statusFilter').value; const source=document.getElementById('sourceFilter').value; const rows=data.papers.filter(row=>{ const hay=[row.citing_title,row.citing_authors,row.venue,row.doi,row.url,row.abstract,row.reference_evidence,row.top_author_name,row.top_author_profile_url,row.top_author_homepage_url].join(' ').toLowerCase(); return (!q||hay.includes(q))&&(!status||row.analysis_status===status)&&(!source||row.source_platforms===source); }); document.getElementById('paperRows').innerHTML=rows.map(row=>`<tr><td>${extLink(row.url,row.citing_title||'(untitled)')}<div class="muted">${esc(row.citing_authors||'')}</div><div class="muted">${esc(row.venue||'')}</div>${row.abstract?`<div class="muted">${esc(shortText(row.abstract))}</div>`:''}</td><td>${esc(String(row.publication_year||'').replace(/\.0$/,''))}</td><td>${esc(row.citation_count||0)}</td><td>${esc(row.source_platforms)}</td><td><span class="pill ${pillClass(row.analysis_status)}">${esc(row.analysis_status||'not_analyzed')}</span><div class="muted">${esc(row.download_status||'')}</div></td><td>${esc(row.top_author_name||row.top_author_status||'')}<div class="muted">${esc(row.top_author_selected_citation_count||'')}</div>${row.top_author_profile_url?`<div>${extLink(row.top_author_profile_url,'profile')}</div>`:''}${row.top_author_homepage_url?`<div>${extLink(row.top_author_homepage_url,'homepage')}</div>`:''}</td><td>${esc(row.location_count||0)}<div class="muted">${esc(row.pages||'')}</div><div class="muted">${esc(row.reference_marker||'')}</div></td><td>${row.doi?`<div>DOI</div><div class="muted">${esc(row.doi)}</div>`:''}${row.url?`<div>${extLink(row.url,'URL')}</div>`:''}</td></tr>`).join(''); }
    function renderDownloadRows(){ const q=document.getElementById('downloadSearch').value.toLowerCase(); const kind=document.getElementById('downloadKindFilter').value; const source=document.getElementById('downloadSourceFilter').value; const rows=[...(data.downloadedPapers||[]).map(row=>({...row,_kind:'downloaded'})),...(data.downloadFailures||[]).map(row=>({...row,_kind:'failed'}))].filter(row=>{ const hay=[row.citing_title,row.venue,row.doi,row.url,row.pdf_path,row.download_url,row.pdf_url,row.open_access_pdf_url,row.candidate_urls,row.failure_reason,row.expected_pdf_path,row.manual_pdf_path].join(' ').toLowerCase(); return (!q||hay.includes(q))&&(!kind||row._kind===kind)&&(!source||row.source_platforms===source); }); document.getElementById('downloadRows').innerHTML=rows.length?rows.map(row=>`<tr><td>${extLink(row.url,row.citing_title||'(untitled)')}<div class="muted">${esc(row.venue||'')}</div>${row.doi?`<div class="muted">DOI ${esc(row.doi)}</div>`:''}</td><td><span class="pill ${row._kind==='downloaded'?'ok':'bad'}">${esc(row.download_status||row._kind)}</span><div class="muted">${esc(row.source_platforms||'')}</div></td><td>${row.pdf_path?`<div class="muted">${esc(row.pdf_path)}</div>`:''}${row.download_url?`<div>${extLink(row.download_url,'download URL')}</div>`:''}</td><td>${esc(shortText(row.candidate_urls||row.pdf_url||row.open_access_pdf_url||'',360))}</td><td>${esc(shortText(row.failure_reason||'',360))}${row.expected_pdf_path?`<div class="muted">expected: ${esc(row.expected_pdf_path)}</div>`:''}${row.manual_pdf_path?`<div class="muted">manual: ${esc(row.manual_pdf_path)}</div>`:''}</td></tr>`).join(''):`<tr><td colspan="5" class="muted">没有匹配的下载记录。</td></tr>`; }
    function renderLocationRows(){ const q=document.getElementById('locationSearch').value.toLowerCase(); const match=document.getElementById('matchFilter').value; const positive=document.getElementById('positiveFilter').value; const rows=data.locations.filter(row=>{ const hay=[row.citing_title,row.citation_marker,row.match_type,row.context].join(' ').toLowerCase(); const isPositive=String(row.is_positive).toLowerCase(); return (!q||hay.includes(q))&&(!match||row.match_type===match)&&(!positive||isPositive===positive); }); document.getElementById('locationRows').innerHTML=rows.map(row=>`<tr><td>${esc(row.citing_title)}</td><td>p.${esc(row.page)}<div class="muted">L${esc(row.line_start)}-${esc(row.line_end)}</div></td><td>${esc(row.citation_marker)}<div class="muted">ref ${esc(row.reference_marker||'')}</div></td><td><span class="pill neutral">${esc(row.match_type)}</span><div class="muted">conf ${esc(row.confidence)}</div></td><td class="context">${esc(row.context)}</td></tr>`).join(''); }
    function rejectionSummary(){ const entries=Object.entries(data.expertRejections||{}).sort((a,b)=>b[1]-a[1]); return entries.length?`拒绝原因统计：${entries.slice(0,6).map(([k,v])=>`${k} ${v}`).join('；')}`:'没有可显示的拒绝原因统计。'; }
    function renderNotableRows(){ const rows=data.notableCitations||[]; document.getElementById('notableRows').innerHTML=rows.length?rows.map(row=>`<tr><td>${row.wikipedia_url?`<a href="${esc(row.wikipedia_url)}">${esc(row.author_name)}</a>`:esc(row.author_name)}</td><td>${esc(row.selected_citation_count)}<div class="muted">${esc(row.selected_citation_source)}</div></td><td>${esc(row.notable_reason||'')}</td><td>${esc(row.citing_title)}<div class="muted">${esc(row.venue||'')}</div>${row.citation_context_sample?`<div class="muted">${esc(row.citation_context_sample)}</div>`:''}</td><td>${esc(row.citation_location_status||row.pages||row.analysis_status||'')}</td></tr>`).join(''):`<tr><td colspan="5" class="muted">authors 阶段已运行，但未发现满足严格 Wikipedia/Wikidata notable 规则的高置信专家证据。${esc(rejectionSummary())}</td></tr>`; }
    function renderExpertRows(){ const q=document.getElementById('expertSearch').value.toLowerCase(); const notable=document.getElementById('expertNotableFilter').value; const source=document.getElementById('expertSourceFilter').value; const rows=(data.experts||[]).filter(row=>{ const hay=[row.name,row.wikipedia_title,row.wikidata_description,row.wikipedia_summary,row.wikipedia_evidence,row.wikidata_evidence,row.academic_titles,row.honors_awards,row.professional_memberships,row.leadership_roles,row.profile_affiliations,row.research_interests,row.google_scholar_affiliation,row.google_scholar_interests,row.semantic_scholar_affiliations,row.google_scholar_profile_url,row.semantic_scholar_profile_url,row.google_scholar_homepage_url,row.semantic_scholar_homepage_url,row.personal_homepage_url,row.personal_homepage_evidence,row.personal_homepage_summary,row.personal_homepage_identity_status,row.personal_homepage_identity_evidence,row.personal_homepage_rejection_reason,row.notable_reason,row.profile_evidence_sources,row.expert_query_status,row.expert_rejection_reason,row.citing_titles].join(' ').toLowerCase(); const isNotable=String(row.is_notable).toLowerCase(); const sources=String(row.profile_evidence_sources||''); return (!q||hay.includes(q))&&(!notable||isNotable===notable)&&(!source||sources.includes(source)); }); document.getElementById('expertRows').innerHTML=rows.length?rows.map(row=>`<tr><td>${row.wikipedia_url?`<a href="${esc(row.wikipedia_url)}" target="_blank" rel="noreferrer">${esc(row.name)}</a>`:esc(row.name)}<div class="muted">rank ${esc(row.rank||'')}</div><div class="muted">${esc(row.notability_confidence||'')}</div>${row.google_scholar_profile_url?`<div>${extLink(row.google_scholar_profile_url,'Scholar')}</div>`:''}${row.semantic_scholar_profile_url?`<div>${extLink(row.semantic_scholar_profile_url,'Semantic Scholar')}</div>`:''}${row.google_scholar_homepage_url?`<div>${extLink(row.google_scholar_homepage_url,'Scholar homepage')}</div>`:''}${row.semantic_scholar_homepage_url?`<div>${extLink(row.semantic_scholar_homepage_url,'S2 homepage')}</div>`:''}${row.personal_homepage_url?`<div>${extLink(row.personal_homepage_url,'homepage')}</div>`:''}</td><td>${esc(row.selected_citation_count||0)}<div class="muted">${esc(row.selected_citation_source||'')}</div></td><td>${esc(shortText(row.profile_affiliations||row.semantic_scholar_affiliations||row.google_scholar_affiliation||'',260))}${row.research_interests||row.google_scholar_interests?`<div class="muted">${esc(shortText(row.research_interests||row.google_scholar_interests,220))}</div>`:''}</td><td>${esc(shortText(row.academic_titles||row.wikidata_description||'',260))}</td><td>${esc(shortText(row.honors_awards||'',260))}</td><td>${esc(shortText([row.professional_memberships,row.leadership_roles].filter(Boolean).join(' | '),260))}</td><td>${row.is_notable?'<span class="pill ok">notable</span>':'<span class="pill neutral">profile</span>'}<div class="muted">${esc(row.expert_query_status||'')}</div>${row.expert_rejection_reason?`<div class="muted">reason: ${esc(row.expert_rejection_reason)}</div>`:''}${row.personal_homepage_identity_status?`<div class="muted">homepage identity: ${esc(row.personal_homepage_identity_status)} ${esc(row.personal_homepage_identity_confidence||'')}</div>`:''}${row.personal_homepage_rejection_reason?`<div class="muted">homepage reason: ${esc(row.personal_homepage_rejection_reason)}</div>`:''}<div class="muted">${esc(row.profile_evidence_sources||'')}</div><div class="muted">${esc(shortText(row.personal_homepage_identity_evidence||row.notable_reason||row.personal_homepage_evidence||row.personal_homepage_summary||row.wikipedia_evidence||row.wikidata_evidence||'',260))}</div></td></tr>`).join(''):`<tr><td colspan="7" class="muted">没有匹配的作者画像/头衔/荣誉记录。</td></tr>`; }
    function init(){ renderTarget(); renderStats(); renderSourceStatus(); barChart('sourceChart',data.charts.sourcePlatforms); barChart('downloadChart',data.charts.downloadStatus); barChart('coverageChart',data.charts.analysisStatus); barChart('yearChart',data.charts.publicationYears); barChart('topChart',Object.fromEntries(data.topLocations.map(row=>[row.citing_title,Number(row.location_count)||0])),12); if(data.stats.hasAuthorFiles){ barChart('authorChart',Object.fromEntries((data.authors||[]).map(row=>[row.name,Number(row.selected_citation_count)||0])),12); renderNotableRows(); renderExpertRows(); } else { document.querySelectorAll('.author-only').forEach(el=>el.classList.add('hidden')); } fillSelect('statusFilter','全部覆盖状态',data.papers.map(row=>row.analysis_status)); fillSelect('sourceFilter','全部来源',data.papers.map(row=>row.source_platforms)); fillSelect('downloadSourceFilter','全部来源',data.papers.map(row=>row.source_platforms)); fillSelect('matchFilter','全部匹配类型',data.locations.map(row=>row.match_type)); fillSelect('expertSourceFilter','全部证据来源',(data.experts||[]).flatMap(row=>String(row.profile_evidence_sources||'').split(/;\\s*/)).filter(Boolean)); ['paperSearch','statusFilter','sourceFilter'].forEach(id=>document.getElementById(id).addEventListener('input',renderPaperRows)); ['downloadSearch','downloadKindFilter','downloadSourceFilter'].forEach(id=>document.getElementById(id).addEventListener('input',renderDownloadRows)); ['locationSearch','matchFilter','positiveFilter'].forEach(id=>document.getElementById(id).addEventListener('input',renderLocationRows)); ['expertSearch','expertNotableFilter','expertSourceFilter'].forEach(id=>document.getElementById(id).addEventListener('input',renderExpertRows)); renderPaperRows(); renderDownloadRows(); renderLocationRows(); }
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
    coverage_path = output / "citation_paper_coverage_reliable.csv"
    workbook_path = output / "citation_locations_reliable.xlsx"
    papers = merge_coverage_into_papers(read_papers(output), coverage)
    notes = append_run_notes(
        output,
        {
            "analyze.rows": len(rows),
            "analyze.location_rows": len(contexts),
            "analyze.cited_in_body": sum(1 for row in coverage if row.get("analysis_status") == "cited_in_body"),
            "analyze.scope": args.analysis_scope,
        },
    )
    report = write_report(
        output,
        {
            "target": target_to_frame(target),
            "papers": papers,
            "citation_locations": pd.DataFrame(contexts, columns=CONTEXT_COLUMNS),
            "run_notes": notes,
        },
        export_legacy_csv=export_legacy_enabled(args),
    )
    if export_legacy_enabled(args):
        write_csv(contexts_path, contexts, CONTEXT_COLUMNS)
        write_csv(coverage_path, coverage, COVERAGE_COLUMNS)
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
    print(f"Saved citation report: {report}")
    dashboard_path = write_dashboard(output)
    print(f"Saved citation dashboard: {dashboard_path}")
    return contexts_path


def cmd_dashboard(args: argparse.Namespace) -> Path:
    output = ensure_dir(args.output)
    papers = read_papers(output)
    manual = read_manual_todo(output)
    if not papers.empty:
        write_report(
            output,
            {
                "papers": papers,
                "manual_download_todo": manual,
            },
            export_legacy_csv=export_legacy_enabled(args),
        )
    dashboard_path = write_dashboard(output)
    print(f"Saved citation dashboard: {dashboard_path}")
    return dashboard_path


def cmd_run(args: argparse.Namespace) -> None:
    find_args = argparse.Namespace(**vars(args))
    _, citing_path = cmd_find(find_args)
    author_args = argparse.Namespace(
        output=args.output,
        browser=args.browser,
        scholar_locale=args.scholar_locale,
        scholar_captcha_action=args.scholar_captcha_action,
        scholar_captcha_timeout=args.scholar_captcha_timeout,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        s2_api_key=args.s2_api_key,
        s2_api_key_env=args.s2_api_key_env,
        author_top_n=args.author_top_n,
        max_author_profiles=args.max_author_profiles,
        author_workers=args.author_workers,
        wiki_workers=args.wiki_workers,
        homepage_search_limit=args.homepage_search_limit,
        skip_google_scholar_authors=getattr(args, "skip_google_scholar_authors", False),
        export_legacy_csv=args.export_legacy_csv,
    )
    print("Running author enrichment after find.")
    cmd_authors(author_args)
    download_args = argparse.Namespace(
        input=str(citing_path),
        output=args.output,
        arxiv_fallback=args.arxiv_fallback,
        download_workers=args.download_workers,
        export_legacy_csv=args.export_legacy_csv,
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
        export_legacy_csv=args.export_legacy_csv,
    )
    cmd_analyze(analyze_args)
    print("Refreshing author enrichment with citation-location coverage.")
    cmd_authors(author_args)
    cmd_dashboard(argparse.Namespace(output=args.output))


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
    parser.add_argument("--find-workers", type=int, default=2, help="Parallel platform workers for find; Google Scholar itself remains single-browser serial (default: 2)")
    parser.add_argument("--require-google-scholar", action="store_true", help="Fail the find/run if Google Scholar produces no citing rows")
    parser.add_argument("--scholar-captcha-action", choices=["wait", "fail"], default="wait", help="How to handle Google Scholar captcha pages (default: wait)")
    parser.add_argument("--scholar-captcha-timeout", type=float, default=600.0, help="Seconds to wait for manual Google Scholar captcha completion when action is wait (default: 600)")
    parser.add_argument("--export-legacy-csv", action="store_true", help="Also export legacy CSV/XLSX tables for debugging")


def add_common_author_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True, help="Output directory containing citation_report.xlsx or legacy citing_papers.csv")
    parser.add_argument("--author-top-n", type=int, default=20, help="Top authors to enrich with Wikipedia evidence (default: 20)")
    parser.add_argument("--max-author-profiles", type=int, default=200, help="Maximum author profiles to query across Semantic Scholar and Google Scholar (default: 200)")
    parser.add_argument("--browser", choices=["chrome", "edge", "firefox"], default="edge", help="Visible browser for Google Scholar author captcha verification (default: edge)")
    parser.add_argument("--scholar-locale", default="en", help="Google Scholar UI locale for author profile search (default: en)")
    parser.add_argument("--scholar-captcha-action", choices=["wait", "fail"], default="wait", help="How to handle Google Scholar author captcha pages (default: wait)")
    parser.add_argument("--scholar-captcha-timeout", type=float, default=600.0, help="Seconds to wait for manual Google Scholar author captcha completion (default: 600)")
    parser.add_argument("--skip-google-scholar-authors", action="store_true", help="Skip Google Scholar author profile queries; useful for unattended dashboard/report refreshes")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=3.0)
    parser.add_argument("--s2-api-key", default="")
    parser.add_argument("--s2-api-key-env", default="SEMANTIC_SCHOLAR_API_KEY")
    parser.add_argument("--author-workers", type=int, default=4, help="Parallel Semantic Scholar author profile workers (default: 4)")
    parser.add_argument("--wiki-workers", type=int, default=2, help="Parallel Wikipedia/Wikidata profile workers (default: 2)")
    parser.add_argument("--homepage-search-limit", type=int, default=50, help="Maximum expert-scope authors to search for personal/school homepages when profiles do not provide one (default: 50)")
    parser.add_argument("--export-legacy-csv", action="store_true", help="Also export legacy author CSV tables for debugging")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find, enrich authors, download, analyze, and visualize papers citing a target paper.")
    sub = parser.add_subparsers(dest="command", required=True)

    find_p = sub.add_parser("find", help="Find citing papers")
    add_common_find_args(find_p)
    find_p.set_defaults(func=cmd_find)

    download_p = sub.add_parser("download", help="Download open PDFs from citation_report.xlsx or a legacy citing_papers.csv")
    download_p.add_argument("--input", default="")
    download_p.add_argument("--output", required=True)
    download_p.add_argument("--arxiv-fallback", action=argparse.BooleanOptionalAction, default=True)
    download_p.add_argument("--download-workers", type=int, default=4, help="Parallel PDF download workers (default: 4)")
    download_p.add_argument("--export-legacy-csv", action="store_true", help="Also export legacy download CSV tables for debugging")
    download_p.set_defaults(func=cmd_download)

    authors_p = sub.add_parser("authors", help="Enrich citing-paper authors with impact and notability evidence")
    add_common_author_args(authors_p)
    authors_p.set_defaults(func=cmd_authors)

    analyze_p = sub.add_parser("analyze", help="Analyze downloaded PDFs for citation contexts")
    analyze_p.add_argument("--target-title", default="")
    analyze_p.add_argument("--target-json", default="")
    analyze_p.add_argument("--metadata", default="")
    analyze_p.add_argument("--pdf-dir", default="")
    analyze_p.add_argument("--output", required=True)
    analyze_p.add_argument("--context-lines", type=int, default=2)
    analyze_p.add_argument("--analysis-scope", choices=["all-contexts", "positive-only", "summary-only"], default="all-contexts")
    analyze_p.add_argument("--export-legacy-csv", action="store_true", help="Also export legacy analysis CSV/XLSX tables for debugging")
    analyze_p.set_defaults(func=cmd_analyze)

    dashboard_p = sub.add_parser("dashboard", help="Build the citation dashboard from existing outputs")
    dashboard_p.add_argument("--output", required=True)
    dashboard_p.set_defaults(func=cmd_dashboard)

    run_p = sub.add_parser("run", help="Run find, authors, download, analyze, and dashboard")
    add_common_find_args(run_p)
    run_p.add_argument("--arxiv-fallback", action=argparse.BooleanOptionalAction, default=True)
    run_p.add_argument("--download-workers", type=int, default=4, help="Parallel PDF download workers (default: 4)")
    run_p.add_argument("--context-lines", type=int, default=2)
    run_p.add_argument("--analysis-scope", choices=["all-contexts", "positive-only", "summary-only"], default="all-contexts")
    run_p.add_argument("--author-top-n", type=int, default=20, help="Top authors to enrich with Wikipedia evidence (default: 20)")
    run_p.add_argument("--max-author-profiles", type=int, default=200, help="Maximum author profiles to query across Semantic Scholar and Google Scholar (default: 200)")
    run_p.add_argument("--author-workers", type=int, default=4, help="Parallel Semantic Scholar author profile workers (default: 4)")
    run_p.add_argument("--wiki-workers", type=int, default=2, help="Parallel Wikipedia/Wikidata profile workers (default: 2)")
    run_p.add_argument("--homepage-search-limit", type=int, default=50, help="Maximum expert-scope authors to search for personal/school homepages when profiles do not provide one (default: 50)")
    run_p.add_argument("--skip-google-scholar-authors", action="store_true", help="Skip Google Scholar author profile queries during run")
    # --export-legacy-csv is added by add_common_find_args.
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

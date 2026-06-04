#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup


def load_skill_module():
    path = Path(__file__).with_name("paper_citation_researcher.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_google_preferred_merge(module) -> None:
    semantic = {
        "source_platforms": "semantic-scholar",
        "source_record_ids": "s2:abc",
        "citing_title": "Shared Paper Title",
        "citing_authors": "Semantic Authors",
        "publication_year": "2025",
        "venue": "Semantic Venue",
        "doi": "10.1234/example",
        "url": "https://semanticscholar.org/paper/abc",
        "pdf_url": "",
        "open_access_pdf_url": "https://example.org/oa.pdf",
        "citation_count": "1",
        "semantic_scholar_paper_id": "abc",
        "google_scholar_cited_by_url": "",
        "arxiv_id": "2501.00001",
        "acl_id": "",
        "abstract": "Semantic abstract",
    }
    google = {
        "source_platforms": "google-scholar",
        "source_record_ids": "https://scholar.google.com/scholar?cites=1",
        "citing_title": "Shared Paper Title",
        "citing_authors": "Google Authors",
        "publication_year": "2025",
        "venue": "Google Venue",
        "doi": "",
        "url": "https://publisher.example/paper",
        "pdf_url": "https://publisher.example/paper.pdf",
        "open_access_pdf_url": "",
        "citation_count": "42",
        "semantic_scholar_paper_id": "",
        "google_scholar_cited_by_url": "https://scholar.google.com/scholar?cites=2",
        "arxiv_id": "",
        "acl_id": "",
        "abstract": "",
    }

    rows = module.merge_records([semantic, google])
    assert len(rows) == 1
    row = rows[0]
    assert row["dedupe_key"] == "title:shared paper title:2025"
    assert row["source_platforms"] == "google-scholar;semantic-scholar"
    assert row["citing_authors"] == "Google Authors"
    assert row["venue"] == "Google Venue"
    assert row["citation_count"] == "42"
    assert row["pdf_url"] == "https://publisher.example/paper.pdf"
    assert row["doi"] == "10.1234/example"
    assert row["open_access_pdf_url"] == "https://example.org/oa.pdf"
    assert row["semantic_scholar_paper_id"] == "abc"
    assert row["abstract"] == "Semantic abstract"


def test_url_alias_duplicate_merge(module) -> None:
    first = {
        "source_platforms": "semantic-scholar",
        "source_record_ids": "s2:url-a",
        "citing_title": "Semantic URL Title",
        "publication_year": "2025",
        "doi": "",
        "url": "https://example.org/landing-a",
        "pdf_url": "https://files.example.org/shared.pdf",
        "open_access_pdf_url": "",
        "citation_count": "1",
        "semantic_scholar_paper_id": "url-a",
    }
    second = {
        "source_platforms": "google-scholar",
        "source_record_ids": "https://scholar.google.com/scholar?cites=42",
        "citing_title": "Google URL Title",
        "citing_authors": "Google Authors",
        "publication_year": "2025",
        "doi": "",
        "url": "https://example.org/landing-b",
        "pdf_url": "https://files.example.org/shared.pdf#page=1",
        "open_access_pdf_url": "",
        "citation_count": "8",
    }

    rows = module.merge_records([first, second])
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == "title:google url title:2025"
    assert rows[0]["citing_title"] == "Google URL Title"
    assert rows[0]["citation_count"] == "8"
    assert rows[0]["semantic_scholar_paper_id"] == "url-a"


def test_open_access_url_duplicate_merge(module) -> None:
    first = {
        "source_platforms": "semantic-scholar",
        "source_record_ids": "s2:oa-a",
        "citing_title": "Open Access A",
        "publication_year": "2025",
        "open_access_pdf_url": "https://oa.example.org/shared.pdf",
    }
    second = {
        "source_platforms": "semantic-scholar",
        "source_record_ids": "s2:oa-b",
        "citing_title": "Open Access B",
        "publication_year": "2025",
        "open_access_pdf_url": "https://oa.example.org/shared.pdf/",
    }

    rows = module.merge_records([first, second])
    assert len(rows) == 1
    assert rows[0]["dedupe_key"].startswith("title:")
    assert rows[0]["source_platforms"] == "semantic-scholar"


def test_doi_conflict_blocks_alias_merge(module) -> None:
    first = {
        "source_platforms": "semantic-scholar",
        "source_record_ids": "s2:conflict-a",
        "citing_title": "Conflict Paper",
        "publication_year": "2025",
        "doi": "10.1234/a",
        "pdf_url": "https://files.example.org/conflict.pdf",
    }
    second = {
        "source_platforms": "google-scholar",
        "source_record_ids": "https://scholar.google.com/scholar?cites=99",
        "citing_title": "Conflict Paper",
        "publication_year": "2025",
        "doi": "10.1234/b",
        "pdf_url": "https://files.example.org/conflict.pdf",
    }

    rows = module.merge_records([first, second])
    assert len(rows) == 2
    assert all(row["dedupe_key"].startswith("title:") for row in rows)
    assert len({row["dedupe_key"] for row in rows}) == 2


def test_captcha_detection(module) -> None:
    assert module.is_scholar_captcha_page("<html>Please show you're not a robot</html>")
    assert module.is_scholar_captcha_page("<form action='/sorry/index'>captcha</form>")
    assert not module.is_scholar_captcha_page("<div class='gs_ri'>Scholar result</div>")


class FakeS2Response:
    def __init__(self, status_code: int, payload: Any = None, url: str = "https://api.example.test") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.url = url
        self.headers = {}
        self.text = ""
        self.reason = "OK" if status_code < 400 else "Error"

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        return self._payload


class FakeS2Session:
    def __init__(self, responses: list[FakeS2Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}, "timeout": timeout})
        response = self.responses.pop(0)
        response.url = url
        return response


def test_semantic_scholar_title_resolve_uses_normalized_search(module) -> None:
    session = FakeS2Session(
        [
            FakeS2Response(404),
            FakeS2Response(
                200,
                {
                    "data": [
                        {
                            "paperId": "emr",
                            "title": "EMR-Merging: Tuning-Free High-Performance Model Merging",
                            "year": 2025,
                        }
                    ]
                },
            ),
        ]
    )

    paper = module.s2_resolve_paper(session, "EMR-Merging: Tuning-Free High-Performance Model Merging")

    assert paper["paperId"] == "emr"
    assert "paper/search/match" in session.calls[0]["url"]
    assert session.calls[1]["params"]["query"] == "emr merging tuning free high performance model merging"


def test_semantic_scholar_match_payload_can_resolve_directly(module) -> None:
    session = FakeS2Session(
        [
            FakeS2Response(
                200,
                {
                    "data": [
                        {
                            "paperId": "emr",
                            "title": "EMR-Merging: Tuning-Free High-Performance Model Merging",
                            "year": 2024,
                        }
                    ]
                },
            ),
        ]
    )

    paper = module.s2_resolve_paper(session, "EMR-Merging: Tuning-Free High-Performance Model Merging")

    assert paper["paperId"] == "emr"
    assert len(session.calls) == 1
    assert "paper/search/match" in session.calls[0]["url"]


def test_semantic_scholar_citation_fields_are_nested(module) -> None:
    session = FakeS2Session(
        [
            FakeS2Response(
                200,
                {
                    "data": [
                        {
                            "citingPaper": {
                                "paperId": "cite-1",
                                "title": "A citing paper",
                                "authors": [{"name": "Ada Lovelace"}],
                                "year": 2026,
                                "venue": "TestConf",
                                "externalIds": {"DOI": "10.1234/cite"},
                                "url": "https://example.test/cite",
                                "openAccessPdf": {"url": "https://example.test/cite.pdf"},
                                "citationCount": 3,
                                "abstract": "Example abstract",
                            }
                        }
                    ]
                },
            )
        ]
    )

    rows = module.s2_fetch_citations(session, {"paperId": "target-1"}, 1)

    assert rows[0]["citing_title"] == "A citing paper"
    assert rows[0]["citing_authors"] == "Ada Lovelace"
    assert rows[0]["doi"] == "10.1234/cite"
    assert rows[0]["citation_count"] == "3"
    fields = session.calls[0]["params"]["fields"]
    assert "citingPaper.title" in fields
    assert not fields.startswith("title,")


def test_semantic_scholar_empty_citation_count_defaults_to_zero(module) -> None:
    session = FakeS2Session(
        [
            FakeS2Response(
                200,
                {
                    "data": [
                        {"citingPaper": {"paperId": "missing-count", "title": "Missing Count"}},
                        {"citingPaper": {"paperId": "zero-count", "title": "Zero Count", "citationCount": 0}},
                        {"citingPaper": {"paperId": "none-count", "title": "None Count", "citationCount": None}},
                    ]
                },
            )
        ]
    )

    rows = module.s2_fetch_citations(session, {"paperId": "target-1"}, 3)

    assert [row["citation_count"] for row in rows] == ["0", "0", "0"]


def test_google_scholar_forced_start_url(module) -> None:
    url = "https://scholar.google.com/scholar?cites=123&hl=en&as_sdt=2005&sciodt=0,5"
    next_url = module.scholar_results_url_with_start(url, 100)

    assert module.scholar_query_value(next_url, "cites") == "123"
    assert module.scholar_start(next_url) == 100


def test_google_scholar_default_locale(module) -> None:
    url = module.scholar_url("example paper")

    assert module.scholar_query_value(url, "hl") == "zh-CN"


def test_google_scholar_parse_reported_count(module) -> None:
    assert module.parse_count("Cited by 1,234") == 1234
    assert module.parse_count("") is None


def test_google_result_blocks_excludes_search_within_box(module) -> None:
    soup = BeautifulSoup(
        """
        <div class="gs_r"><h3>Search within citing articles</h3></div>
        <div class="gs_r"><h3><a href="https://example.test">Real paper</a></h3></div>
        """,
        "html.parser",
    )

    blocks = module.google_result_blocks(soup)

    assert len(blocks) == 1
    assert "Real paper" in blocks[0].get_text(" ", strip=True)


def test_google_citation_count_english(module) -> None:
    block = BeautifulSoup(
        """
        <div class="gs_ri">
          <h3><a href="https://example.test/paper">Paper</a></h3>
          <a href="/scholar?cites=123">Cited by 7</a>
        </div>
        """,
        "html.parser",
    )

    row = module.parse_google_result(block)

    assert row["citation_count"] == "7"
    assert row["google_scholar_cited_by_url"] == "https://scholar.google.com/scholar?cites=123"


def test_google_citation_count_chinese(module) -> None:
    block = BeautifulSoup(
        """
        <div class="gs_ri">
          <h3><a href="https://example.test/paper">Paper</a></h3>
          <a href="/scholar?cites=123">被引用次数：7</a>
        </div>
        """,
        "html.parser",
    )

    row = module.parse_google_result(block)

    assert row["citation_count"] == "7"
    assert row["google_scholar_cited_by_url"] == "https://scholar.google.com/scholar?cites=123"


def test_google_citation_count_defaults_to_zero(module) -> None:
    block = BeautifulSoup(
        """
        <div class="gs_ri">
          <h3><a href="https://example.test/paper">Paper</a></h3>
          <div class="gs_a">A Author - Venue, 2026</div>
        </div>
        """,
        "html.parser",
    )

    row = module.parse_google_result(block)

    assert row["citation_count"] == "0"
    assert row["google_scholar_cited_by_url"] == ""


def test_google_zero_citation_count_overrides_semantic_merge(module) -> None:
    semantic = {
        "source_platforms": "semantic-scholar",
        "source_record_ids": "s2:zero-merge",
        "citing_title": "Zero Merge",
        "publication_year": "2026",
        "citation_count": "5",
        "semantic_scholar_paper_id": "zero-merge",
    }
    google = {
        "source_platforms": "google-scholar",
        "source_record_ids": "https://example.test/zero-merge",
        "citing_title": "Zero Merge",
        "publication_year": "2026",
        "citation_count": "0",
        "url": "https://example.test/zero-merge",
    }

    rows = module.merge_records([semantic, google])

    assert len(rows) == 1
    assert rows[0]["citation_count"] == "0"


def test_parallel_download_manifest(module) -> None:
    original_try_download_url = module.try_download_url
    original_arxiv_fallback = module.arxiv_fallback

    def fake_try_download_url(session, url, path):
        if url == "mock://ok":
            path.write_bytes(b"%PDF-1.4\n% mock\n")
            return True, url
        return False, "mock failure"

    def fake_arxiv_fallback(session, title, path):
        return False, "mock arxiv disabled"

    module.try_download_url = fake_try_download_url
    module.arxiv_fallback = fake_arxiv_fallback
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "citing_papers.csv"
            pd.DataFrame(
                [
                    {
                        "citing_title": "Download OK",
                        "pdf_url": "mock://ok",
                        "open_access_pdf_url": "",
                    },
                    {
                        "citing_title": "Download Fails",
                        "pdf_url": "mock://bad",
                        "open_access_pdf_url": "",
                    },
                ]
            ).to_csv(input_path, index=False, encoding="utf-8-sig")

            args = argparse.Namespace(
                input=str(input_path),
                output=str(tmp_path),
                arxiv_fallback=False,
                download_workers=2,
            )
            module.cmd_download(args)

            manifest = pd.read_csv(tmp_path / "download_manifest.csv", dtype=str).fillna("")
            failures = pd.read_csv(tmp_path / "download_failures.csv", dtype=str).fillna("")
            manual = pd.read_csv(tmp_path / "manual_download_todo.csv", dtype=str).fillna("")
            assert list(manifest["download_status"]) == ["downloaded", "failed"]
            assert len(failures) == 1
            assert len(manual) == 1
            assert Path(manifest.loc[0, "pdf_path"]).exists()
    finally:
        module.try_download_url = original_try_download_url
        module.arxiv_fallback = original_arxiv_fallback


def main() -> None:
    module = load_skill_module()
    test_google_preferred_merge(module)
    test_url_alias_duplicate_merge(module)
    test_open_access_url_duplicate_merge(module)
    test_doi_conflict_blocks_alias_merge(module)
    test_captcha_detection(module)
    test_semantic_scholar_title_resolve_uses_normalized_search(module)
    test_semantic_scholar_match_payload_can_resolve_directly(module)
    test_semantic_scholar_citation_fields_are_nested(module)
    test_semantic_scholar_empty_citation_count_defaults_to_zero(module)
    test_google_scholar_forced_start_url(module)
    test_google_scholar_default_locale(module)
    test_google_scholar_parse_reported_count(module)
    test_google_result_blocks_excludes_search_within_box(module)
    test_google_citation_count_english(module)
    test_google_citation_count_chinese(module)
    test_google_citation_count_defaults_to_zero(module)
    test_google_zero_citation_count_overrides_semantic_merge(module)
    test_parallel_download_manifest(module)
    print("OK merge and parallel download logic")


if __name__ == "__main__":
    main()

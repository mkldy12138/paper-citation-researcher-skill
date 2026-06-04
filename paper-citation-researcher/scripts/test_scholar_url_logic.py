#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

from bs4 import BeautifulSoup


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_paths() -> list[Path]:
    cwd = Path.cwd()
    paths = [
        cwd / ".claude" / "skills" / "citation-tracker" / "scripts" / "citation_tracker.py",
        cwd / ".claude" / "skills" / "google-scholar-scraper" / "scripts" / "google_scholar_scraper.py",
        Path(__file__).with_name("paper_citation_researcher.py"),
    ]
    return [path for path in paths if path.exists()]


def run_checks(module) -> None:
    valid = "/scholar?hl=en&cites=123&as_sdt=2006"
    settings = "/scholar_settings?hl=en&start=10&as_sdt=2006&cites=123"

    assert module.normalize_scholar_results_url(valid, require_cites=True)
    assert module.normalize_scholar_results_url(settings, require_cites=True) is None

    cited_block = BeautifulSoup(
        """
        <div class="gs_ri">
          <a href="/scholar_settings?hl=en&amp;start=10&amp;cites=123">Settings</a>
          <a href="/scholar?hl=en&amp;cites=123">Cited by 7</a>
        </div>
        """,
        "html.parser",
    )
    cited_url, count = module.find_cited_by_link(cited_block)
    assert cited_url == "https://scholar.google.com/scholar?hl=en&cites=123"
    assert str(count) == "7"

    current_url = "https://scholar.google.com/scholar?hl=en&cites=123&start=0"
    next_soup = BeautifulSoup(
        """
        <html><body>
          <a href="/scholar_settings?hl=en&amp;start=10&amp;cites=123">Settings</a>
          <div id="gs_n">
            <a href="/scholar?hl=en&amp;start=10&amp;as_sdt=2006&amp;cites=999">
              <span class="gs_ico gs_ico_nav_next"></span><b>Next</b>
            </a>
            <a href="/scholar?hl=en&amp;start=10&amp;as_sdt=2006&amp;cites=123">
              <span class="gs_ico gs_ico_nav_next"></span><b>Next</b>
            </a>
          </div>
        </body></html>
        """,
        "html.parser",
    )
    assert module.find_next_scholar_page(next_soup, current_url) == (
        "https://scholar.google.com/scholar?hl=en&start=10&as_sdt=2006&cites=123"
    )

    wrong_cites_soup = BeautifulSoup(
        """
        <div id="gs_n">
          <a href="/scholar?hl=en&amp;start=10&amp;cites=999">
            <span class="gs_ico gs_ico_nav_next"></span><b>Next</b>
          </a>
        </div>
        """,
        "html.parser",
    )
    assert module.find_next_scholar_page(wrong_cites_soup, current_url) is None

    numeric_nav_soup = BeautifulSoup(
        """
        <div id="gs_n">
          <a href="/scholar?hl=en&amp;start=0&amp;cites=123">1</a>
          <a href="/scholar?hl=en&amp;start=10&amp;cites=123">2</a>
          <a href="/scholar?hl=en&amp;start=20&amp;cites=123">3</a>
        </div>
        """,
        "html.parser",
    )
    assert module.find_next_scholar_page(numeric_nav_soup, current_url) == (
        "https://scholar.google.com/scholar?hl=en&start=10&cites=123"
    )


def main() -> None:
    paths = module_paths()
    if not paths:
        raise RuntimeError("No citation scripts found to test.")
    for path in paths:
        module = load_module(path)
        run_checks(module)
        print(f"OK {path}")


if __name__ == "__main__":
    main()

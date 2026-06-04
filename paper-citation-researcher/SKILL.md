---
name: paper-citation-researcher
description: Find and analyze citation status for an academic paper by title or DOI across Google Scholar and Semantic Scholar. Use when Codex needs to find citing papers, download open-access PDFs, extract in-body citation contexts, mark positive/affirmative citations, or produce CSV/Excel citation reports.
---

# Paper Citation Researcher

Use this skill for citation-status research on a target paper. The workflow has three phases: find citing papers, download open PDFs, and analyze citation contexts in the downloaded PDFs.

## Quick Start

Run the full workflow:

```powershell
python scripts/paper_citation_researcher.py run --paper "Attention Is All You Need" --output ".\citation-output" --max-papers 1000 --browser edge --scholar-locale zh-CN --download-workers 4
```

Run phases separately:

```powershell
python scripts/paper_citation_researcher.py find --paper "<title-or-doi>" --output ".\out"
python scripts/paper_citation_researcher.py download --input ".\out\citing_papers.csv" --output ".\out" --download-workers 4
python scripts/paper_citation_researcher.py analyze --target-title "<title>" --metadata ".\out\citing_papers.csv" --pdf-dir ".\out\pdfs" --output ".\out"
```

## Initial Setup

When using this skill on a new machine or from a project-local copy, initialize the environment before running workflows:

```powershell
cd path\to\paper-citation-researcher
py -m pip install -r requirements.txt
```

Use `python` instead of `py` on systems where the Python launcher is unavailable. Run commands from the skill directory, or keep the `scripts/paper_citation_researcher.py` path relative to the skill copy.

Required runtime setup:

- Python 3.10+.
- A supported browser for Google Scholar Selenium runs: Edge, Chrome, or Firefox. Edge is the default (`--browser edge`).
- Network access to Google Scholar, Semantic Scholar Graph API, publisher pages, arXiv, and open PDF URLs.
- Write access to the chosen output directory.

Optional configuration:

- `SEMANTIC_SCHOLAR_API_KEY`: set this environment variable to use authenticated Semantic Scholar requests. Leave it unset for anonymous requests.
- `--s2-api-key` / `--s2-api-key-env`: use these only when overriding the default API-key source.
- `--scholar-locale`: defaults to `zh-CN`; keep this unless a specific Google Scholar locale is needed.
- `--max-papers`: defaults to `1000`; confirm this value at the start of each new target-paper topic.

No OpenAI API key is required for find/download/analyze.

When downloads fail, open `manual_download_todo.csv`. Download those PDFs manually, then either:

- save each PDF to its `expected_pdf_path`, or
- fill `manual_pdf_path` with the actual local PDF path.

Then rerun `analyze`; it automatically includes manually supplied PDFs.

## Before Running

For each new target-paper topic, ask whether to use the default `--max-papers 1000` before starting. Within an ongoing workflow for the same target paper, use defaults without re-asking unless the required paper identifier or output directory is missing, or the user explicitly wants to customize parameters.

Required values:

- Target paper identifier: title or DOI.
- Output directory.

When the user asks what can be changed, explain only the relevant phase:

- `find`: `--platforms`, `--max-papers`, `--browser`, `--scholar-locale`, `--min-delay`, `--max-delay`, `--s2-api-key-env`.
- `download`: `--download-workers`, `--arxiv-fallback` / `--no-arxiv-fallback`.
- `analyze`: `--context-lines`, `--analysis-scope`, `--pdf-dir`, `--metadata`.

## Behavior

- Google Scholar uses Selenium and may pause for manual captcha completion.
- Google Scholar defaults to `--scholar-locale zh-CN` because cited-by pagination can expose different pages by locale; use `--scholar-locale en` only when needed.
- Google Scholar target pages can report a larger cited-by count than the Next links expose. Read the reported cited-by count from the target page, then keep trying cited-by pages with `start += 10` until the reported count, `--max-papers`, or consecutive empty pages stop the run. Log when Google reports more citations than it exposes through result pages.
- Google Scholar and Semantic Scholar citing-paper rows must always include `citation_count`: parse the source count when present, otherwise write `0` instead of leaving the field empty.
- Semantic Scholar uses the Graph API and supports an optional API key. Leave `--s2-api-key` empty for anonymous requests, or use `--s2-api-key-env SEMANTIC_SCHOLAR_API_KEY` to enable authenticated requests later without changing workflows.
- Resolve Semantic Scholar targets in this order: DOI lookup as `DOI:<doi>`, then `paper/search/match`, then normalized title search. Handle `search/match` responses that return either a paper object or `{"data": [...]}`.
- Fetch Semantic Scholar citations from `/graph/v1/paper/{paperId}/citations` with nested `citingPaper.*` fields. Do not fetch citing papers by re-searching titles.
- For Semantic Scholar 429/5xx responses, read `Retry-After`, use backoff, and include status, URL, and a short response-body excerpt in `platform_errors.semantic-scholar`.
- `dedupe_key` in outputs always uses normalized title plus year. DOI, Semantic Scholar IDs, landing URLs, PDF URLs, OA PDF URLs, arXiv, and ACL links are internal duplicate-detection aliases.
- When Google Scholar and Semantic Scholar return the same citing paper, Google Scholar display fields take priority while Semantic Scholar DOI/open-access metadata is retained.
- PDF downloading uses parallel workers by default (`--download-workers 4`).
- PDF download only uses open/direct links, publisher metadata links, arXiv, or ACL Anthology. Do not use paywall bypasses.
- Analysis first locates the target paper's reference entry in each PDF, then reports only reliable body locations: verified numeric citation markers tied to that reference entry, or explicit `ShapeGPT` mentions. It writes reliable location and coverage outputs and marks positive contexts with a conservative keyword heuristic.

## Outputs

The output directory contains:

- `target.json`: resolved target-paper metadata.
- `citing_papers.csv`: deduplicated citing-paper list.
- `download_manifest.csv`: every download attempt with status and local path.
- `download_failures.csv`: failed download rows and reasons.
- `manual_download_todo.csv`: failed papers to download manually, with candidate URLs and expected paths.
- `pdfs/`: downloaded open-access PDFs.
- `citation_locations_reliable.csv`: reliable body citation locations with citing paper, PDF path, page, line range, citation marker, match type, and context.
- `citation_paper_coverage_reliable.csv`: per-paper analysis coverage, including papers whose PDFs were not downloaded or whose downloaded PDFs only contained the target in references.
- `citation_locations_reliable.xlsx`: workbook with `locations`, `per_paper_summary`, and `coverage` sheets.

## Script Reference

Use `python scripts/paper_citation_researcher.py <command> --help` for current flags.

Detailed output columns are documented in `references/output-schema.md`.

---
name: paper-citation-researcher
description: Find and analyze citation status for an academic paper by title or DOI across Google Scholar and Semantic Scholar. Use when Codex needs to find citing papers, enrich citing-paper authors, download open-access PDFs, extract reliable in-body citation contexts, or produce a consolidated citation workbook and dashboard.
---

# Paper Citation Researcher

Use this skill for citation-status research on a target paper. The workflow finds citing papers, enriches citing-paper authors, downloads open PDFs, analyzes reliable citation locations, and builds a self-contained dashboard.

## Quick Start

Run the full workflow:

```powershell
python scripts/paper_citation_researcher.py run --paper "Attention Is All You Need" --output ".\citation-output" --max-papers 1000 --browser edge --scholar-locale zh-CN --download-workers 4
```

Run phases separately:

```powershell
python scripts/paper_citation_researcher.py find --paper "<title-or-doi>" --output ".\out"
python scripts/paper_citation_researcher.py authors --output ".\out"
python scripts/paper_citation_researcher.py download --output ".\out" --download-workers 4
python scripts/paper_citation_researcher.py analyze --output ".\out"
python scripts/paper_citation_researcher.py dashboard --output ".\out"
```

The primary tabular output is `citation_report.xlsx`. The script can read older output directories that still contain CSV files; after a successful workbook write, legacy table files are removed unless `--export-legacy-csv` is explicitly supplied.

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
- Network access to Google Scholar, Semantic Scholar Graph API, publisher pages, arXiv, ACL Anthology, Wikipedia, and Wikidata.
- Write access to the chosen output directory.

Optional configuration:

- `SEMANTIC_SCHOLAR_API_KEY`: set this environment variable to use authenticated Semantic Scholar requests. Leave it unset for anonymous requests.
- `--s2-api-key` / `--s2-api-key-env`: use these only when overriding the default API-key source.
- `--scholar-locale`: defaults to `zh-CN` for paper search and `en` for author profile search.
- `--max-papers`: defaults to `1000`; confirm this value at the start of each new target-paper topic.
- `--find-workers`: defaults to `2`; runs independent source platforms in parallel. Google Scholar itself remains one browser session with serial pagination.
- `--require-google-scholar`: fail `find`/`run` if Google Scholar produces no citing rows, while still writing failure diagnostics to `citation_report.xlsx`.
- `--scholar-captcha-action wait|fail`: defaults to `wait`; when Google Scholar shows captcha, keep the visible browser open and wait for manual verification.
- `--scholar-captcha-timeout`: defaults to `600` seconds; maximum wait time for manual Google Scholar verification.
- `--author-workers`: defaults to `4`; controls parallel Semantic Scholar Author API profile queries.
- `--wiki-workers`: defaults to `2`; controls parallel Wikipedia/Wikidata enrichment for top non-target authors.
- `--homepage-search-limit`: defaults to `50`; for expert-scope authors without a known profile homepage, searches for likely personal/school homepages and extracts profile evidence.
- `--skip-google-scholar-authors`: optional refresh/debug flag. It preserves already cached Google Scholar author profiles and only marks uncached profiles as skipped.
- `--export-legacy-csv`: debugging option that also writes old CSV/XLSX tables. Do not use it for normal runs.

No OpenAI or LLM API key is required for find/authors/download/analyze/dashboard. Author enrichment uses deterministic page/API retrieval and caches results.

When downloads fail, open `citation_report.xlsx`, sheet `manual_download_todo`. Download those PDFs manually, then either:

- save each PDF to its `expected_pdf_path`, or
- fill `manual_pdf_path` with the actual local PDF path.

Then rerun `analyze`; it automatically includes manually supplied PDFs.

## Before Running

For each new target-paper topic, ask whether to use the default `--max-papers 1000` before starting. Within an ongoing workflow for the same target paper, use defaults without re-asking unless the required paper identifier or output directory is missing, or the user explicitly wants to customize parameters.

Required values:

- Target paper identifier: title or DOI.
- Output directory.

When the user asks what can be changed, explain only the relevant phase:

- `find`: `--platforms`, `--max-papers`, `--find-workers`, `--browser`, `--scholar-locale`, `--scholar-captcha-action`, `--scholar-captcha-timeout`, `--require-google-scholar`, `--min-delay`, `--max-delay`, `--s2-api-key-env`, `--export-legacy-csv`.
- `authors`: `--author-top-n`, `--max-author-profiles`, `--browser`, `--scholar-locale`, `--scholar-captcha-action`, `--scholar-captcha-timeout`, `--skip-google-scholar-authors`, `--author-workers`, `--wiki-workers`, `--homepage-search-limit`, `--min-delay`, `--max-delay`, `--s2-api-key-env`, `--export-legacy-csv`.
- `download`: `--download-workers`, `--arxiv-fallback` / `--no-arxiv-fallback`, `--export-legacy-csv`.
- `analyze`: `--context-lines`, `--analysis-scope`, `--pdf-dir`, `--metadata`, `--export-legacy-csv`.

## Behavior

- Google Scholar uses Selenium. Captcha handling is explicit: by default `--scholar-captcha-action wait` keeps the visible browser open, shows a Windows popup when verification is detected, saves `scholar_debug/` URL/HTML/screenshot evidence, records status in `run_notes`, and waits up to `--scholar-captcha-timeout` seconds for manual verification. Use `--scholar-captcha-action fail` only for non-interactive diagnostic runs.
- Google Scholar is enabled by default through `--platforms google-scholar,semantic-scholar`. Confirm actual use by checking dashboard data-source status, `run_notes` (`find.google_scholar.*`), or the `papers.source_platforms` values in `citation_report.xlsx`; rows containing `google-scholar` came from Google Scholar.
- Use `--require-google-scholar` when the report must include Google Scholar discovery. If Google Scholar is blocked or yields zero citing rows, the command fails after writing diagnostics and must not be treated as a complete Google Scholar investigation.
- `find` can run Google Scholar and Semantic Scholar in parallel when both platforms are enabled. Do not open multiple Google Scholar browser sessions for the same run; Google Scholar pagination stays serial so target matching, cited-by pagination, and captcha handling remain reliable.
- Google Scholar defaults to `--scholar-locale zh-CN` because cited-by pagination can expose different pages by locale; use `--scholar-locale en` only when needed.
- Google Scholar target pages can report a larger cited-by count than the Next links expose. Read the reported cited-by count from the target page, then keep trying cited-by pages with `start += 10` until the reported count, `--max-papers`, or consecutive empty pages stop the run. Log when Google reports more citations than it exposes through result pages.
- If Google Scholar target matching succeeds and some cited-by pages are already collected, a later pagination/captcha/driver interruption preserves the partial Google Scholar rows, records `partial_error` or `partial_captcha_blocked`, and continues downstream instead of discarding collected rows.
- Google Scholar and Semantic Scholar citing-paper rows must always include `citation_count`: parse the source count when present, otherwise write `0` instead of leaving the field empty.
- Semantic Scholar uses the Graph API and supports an optional API key. Leave `--s2-api-key` empty for anonymous requests, or use `--s2-api-key-env SEMANTIC_SCHOLAR_API_KEY` to enable authenticated requests later without changing workflows.
- Resolve Semantic Scholar targets in this order: DOI lookup as `DOI:<doi>`, then `paper/search/match`, then normalized title search. Handle `search/match` responses that return either a paper object or `{"data": [...]}`.
- Fetch Semantic Scholar citations from `/graph/v1/paper/{paperId}/citations` with nested `citingPaper.*` fields. Do not fetch citing papers by re-searching titles.
- For Semantic Scholar 429/5xx responses, read `Retry-After`, use backoff, and include status, URL, and a short response-body excerpt in `platform_errors.semantic-scholar`.
- `dedupe_key` in outputs always uses normalized title plus year. DOI, Semantic Scholar IDs, landing URLs, PDF URLs, OA PDF URLs, arXiv, and ACL links are internal duplicate-detection aliases.
- When Google Scholar and Semantic Scholar return the same citing paper, Google Scholar display fields take priority while Semantic Scholar DOI/open-access metadata is retained.
- The `papers` sheet always includes both the display author string and structured author fields (`citing_authors_json`, `citing_author_ids`) when available. Google-only rows may have only parsed names.
- The `authors` stage deduplicates authors by Semantic Scholar `authorId` first, then normalized name. It queries at most `--max-author-profiles` authors by default, prioritizing candidates with Semantic Scholar IDs, highly cited source papers, and repeated appearances. Semantic Scholar Author API lookups use `--author-workers` parallel workers.
- Author ranking, notable-scholar detection, dashboard author charts, and each paper's `top_author_*` fields exclude all target-paper authors, using `authorId` first and normalized names as a fallback.
- Each row in the `papers` sheet records the highest-cited non-target author when one is available. If all authors are target authors, `top_author_status` is `all_authors_excluded_target`.
- Author citation counts prefer a high-confidence Google Scholar author profile. Accept Google Scholar only on exact-name matches with paper-list evidence from one of the current citing-paper titles. Otherwise record the low-confidence or ambiguous status and fall back to Semantic Scholar Author API metrics.
- Google Scholar author profile lookups remain serial by default because they have no stable public API, rely on profile work-list evidence to avoid homonym errors, and are sensitive to captcha/rate limiting. The `authors` stage opens a visible Google Scholar author-search browser session by default; if a verification page appears, complete it in that browser window and the script transfers the verified cookies back to the author-profile requests. When a high-confidence profile is found, capture its personal citation count, affiliation, research interests, verified-email text, and Homepage link. Chinese and English Google Scholar citation labels are both parsed. If `--skip-google-scholar-authors` is used during a refresh, existing cached Scholar author profiles remain available in the workbook and dashboard.
- For unattended report/dashboard refreshes, pass `--skip-google-scholar-authors` to avoid Google Scholar author profile pages and captcha prompts. This keeps Semantic Scholar author metrics, Wikipedia/Wikidata, homepage evidence, notable-scholar tables, and dashboard generation working while marking author Google Scholar profile querying as skipped.
- Author title/honor enrichment also follows the Google Scholar or Semantic Scholar homepage URL when present, including university/lab/personal pages. If no homepage URL is available, the expert-scope fallback uses a deep-search-style web search for likely personal/school profile pages (`--homepage-search-limit`, default 50), then validates that the page is the same person by cross-checking name, known affiliation, research interests, source context, and education/background evidence before accepting it. Deep-search pages must not be accepted on name alone: they need affiliation/research overlap, or an exact name plus education/background evidence on an academic profile URL. Unverified or same-name-only pages are rejected with `personal_homepage_rejection_reason` and are not shown as author homepage links. Verified evidence is shown in the dashboard as `personal_or_school_homepage`.
- Wikipedia/Wikidata enrichment checks the Top 100 non-target authors plus each citing paper's highest-cited non-target author, capped at 150 unique authors, and uses `--wiki-workers` parallel workers. It extracts structured academic titles, honors/awards, professional memberships, and leadership/editorial roles from Wikipedia summaries, infoboxes, categories, and Wikidata claims. Include a scholar in `notable_citations` only when the page is a high-confidence scholar/person page and contains explicit honor, role, or office evidence such as Fellow, IEEE, ACM, AAAI, AAAS, Academy, editor-in-chief, professor, chair, award, or recipient. Non-matches record `expert_query_status` and `expert_rejection_reason` so empty notable results have an auditable reason.
- PDF downloading uses parallel workers by default (`--download-workers 4`).
- PDF download only uses open/direct links, publisher metadata links, arXiv, or ACL Anthology. Do not use paywall bypasses.
- Analysis first locates the target paper's reference entry in each PDF, then reports only reliable body locations: verified numeric citation markers tied to that reference entry, or explicit target-name mentions. It writes reliable location and coverage data into the workbook and automatically generates a self-contained HTML dashboard.
- The `dashboard` command regenerates the HTML dashboard from `citation_report.xlsx`. If author sheets are absent, the dashboard hides author-specific panels.

## Outputs

The output directory contains:

- `citation_report.xlsx`: consolidated workbook with all table data.
- `citation_dashboard.html`: self-contained frontend dashboard with summary metrics, data-source status, source/download/coverage charts, researched citing-paper metadata table, highest-cited non-target author per paper with profile/homepage links, author impact ranking, author title/honor evidence table with Google Scholar/Semantic Scholar/personal homepage links and rejection diagnostics, notable-scholar citing-paper table when available, and reliable citation-location table.
- `author_profile_cache.json`: cached Google Scholar and Semantic Scholar author profile lookups.
- `wikipedia_profile_cache.json`: cached Wikipedia/Wikidata enrichment lookups.
- `pdfs/`: downloaded open-access PDFs.

`citation_report.xlsx` sheets:

- `target`: resolved target-paper metadata and target authors.
- `papers`: one row per citing paper, merging discovery, download, analysis coverage, structured authors, and highest-cited non-target author fields.
- `paper_authors`: one row per citing-paper author, including order, target-author exclusion status, selected citation count, profile URLs, and personal/school homepage URLs.
- `authors`: non-target author ranking with Google Scholar/Semantic Scholar metrics, matching status, Wikipedia/Wikidata evidence, structured title/honor/role fields, notable status, and expert-query rejection diagnostics.
- `citation_locations`: reliable in-body citation locations and contexts.
- `downloaded_papers`: successfully downloaded or manually supplied papers, including local PDF path and final download URL.
- `download_failures`: papers not successfully downloaded, including landing URL, PDF candidates, expected manual path, and failure reason.
- `manual_download_todo`: failed download rows with candidate URLs, expected PDF paths, and `manual_pdf_path`.
- `notable_citations`: notable scholars and the citing papers in which they cite the target, including citation-location coverage, pages, markers, and a context sample when available.
- `run_notes`: run parameters and operational statistics, including Google Scholar rows/captcha/debug status and expert-query rejection summaries.

Legacy CSV/XLSX files such as `citing_papers.csv`, `download_manifest.csv`, `citation_locations_reliable.csv`, `author_candidates.csv`, and `notable_scholar_citing_papers.csv` are not generated by default. Use `--export-legacy-csv` only when a downstream debug workflow explicitly needs them.

## Script Reference

Use `python scripts/paper_citation_researcher.py <command> --help` for current flags.

Detailed workbook columns are documented in `references/output-schema.md`.

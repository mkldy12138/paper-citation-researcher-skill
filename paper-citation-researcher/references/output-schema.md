# Output Schema

The primary table output is `citation_report.xlsx`. Legacy CSV/XLSX tables are written only when `--export-legacy-csv` is explicitly supplied.

## `citation_report.xlsx`

### `target`

- `record_type`: `metadata` or `author`.
- `field`: metadata key for `metadata` rows.
- `value`: metadata value for `metadata` rows.
- `author_order`: 1-based target-author order for `author` rows.
- `author_name`: target-paper author name.
- `author_id`: Semantic Scholar author ID when available.

Important metadata fields include `paperId`, `title`, `venue`, `year`, `citationCount`, `url`, `doi`, `arxiv`, `externalIds_json`, `openAccessPdf_json`, and `target_json`.

### `papers`

One row per citing paper. This sheet is the main researched-paper table and merges discovery metadata, download status, analysis coverage, and highest-cited non-target author data.

Discovery columns:

- `dedupe_key`: normalized-title/year key used for merging platforms.
- `source_platforms`: semicolon-separated platforms where the citing paper was found.
- `source_record_ids`: semicolon-separated source IDs or source URLs.
- `citing_title`: title of the citing paper.
- `citing_authors`: display author string from the source platform.
- `citing_authors_json`: JSON list of structured author objects when available, e.g. `[{ "name": "...", "authorId": "..." }]`.
- `citing_author_ids`: semicolon-separated Semantic Scholar author IDs when available.
- `publication_year`, `venue`, `doi`, `url`, `pdf_url`, `open_access_pdf_url`.
- `citation_count`: citation count for the citing paper. Google Scholar and Semantic Scholar rows always provide this value; use `0` when the source has no citation count.
- `semantic_scholar_paper_id`, `google_scholar_cited_by_url`, `arxiv_id`, `acl_id`, `abstract`.

The dashboard's `调研论文信息与覆盖` table is built from this sheet and displays title, authors, venue, year, citing-paper citation count, DOI/URL, abstract snippet, download/analysis status, highest-cited non-target author, and reliable citation-location counts.

Google Scholar usage can be confirmed from this sheet: any `source_platforms` value containing `google-scholar` came from Google Scholar. The `run_notes` sheet also records `find.google_scholar.*` diagnostics, and the dashboard shows Google Scholar rows, captcha status, target URL, reported cited-by count, and platform errors.

Download and analysis columns:

- `pdf_path`: local PDF path when downloaded or manually supplied.
- `download_status`: `downloaded` or `failed`.
- `download_url`: final PDF URL used for a successful download.
- `failure_reason`: download or PDF parse failure detail.
- `analysis_status`: coverage state such as `cited_in_body`, `target_reference_found_no_body_hits`, `target_reference_not_found`, or `pdf_not_downloaded`.
- `location_count`: number of reliable body citation locations.
- `pages`: semicolon-separated pages with reliable body locations.
- `reference_marker`, `reference_score`, `reference_evidence`, `reference_entry`: target-reference evidence used to validate body citation markers.

Highest-cited non-target author columns:

- `top_author_key`: dedupe key for the selected non-target author.
- `top_author_name`: display name of the highest-cited non-target author on this citing paper.
- `top_author_selected_citation_count`: selected personal citation count.
- `top_author_selected_citation_source`: `google-scholar` when a high-confidence Google Scholar profile match was found; otherwise `semantic-scholar`.
- `top_author_profile_url`: best available profile URL.
- `top_author_homepage_url`: best available personal, school, lab, or profile-homepage URL.
- `top_author_is_notable`: whether the selected author passed Wikipedia/Wikidata notability checks.
- `top_author_status`: `ok`, `no_authors`, or `all_authors_excluded_target`.
- `target_author_excluded_count`: number of citing-paper authors excluded because they match target-paper authors.

### `paper_authors`

One row per author on each citing paper.

- `dedupe_key`, `citing_title`, `publication_year`, `venue`: citing-paper identity.
- `author_order`: 1-based author order in the citing paper when known.
- `author_key`: author dedupe key, preferring `s2:<authorId>` and falling back to `name:<normalized name>`.
- `name`, `normalized_name`, `semantic_author_id`.
- `is_target_author`: `True` when the author matches a target-paper author by `authorId` or normalized name.
- `target_author_match`: match explanation, such as `author_id` or `normalized_name`.
- `selected_citation_count`, `selected_citation_source`: personal citation count used for ranking.
- `google_scholar_profile_url`, `google_scholar_homepage_url`, `semantic_scholar_profile_url`, `semantic_scholar_homepage_url`, `personal_homepage_url`, `profile_query_status`.

### `authors`

Non-target author ranking. Target-paper authors are excluded from this sheet by design.

- `rank`: rank after selecting the best available personal citation count.
- `author_key`, `name`, `normalized_name`, `semantic_author_id`.
- `is_target_author`: should be `False` for normal rows.
- `target_author_match`: retained for auditing if a row is ever excluded or debug-exported.
- `citing_paper_count`: number of citing papers in which the author appears.
- `max_citing_paper_citation_count`: highest citation count among the author's citing papers.
- `sum_citing_paper_citation_count`: sum of citation counts among the author's citing papers.
- `citing_titles`: citing-paper titles associated with this author.
- `google_scholar_citations`, `google_scholar_profile_url`, `google_scholar_homepage_url`, `google_scholar_match_status`.
- `semantic_scholar_citations`, `semantic_scholar_h_index`, `semantic_scholar_paper_count`, `semantic_scholar_affiliations`, `semantic_scholar_profile_url`, `semantic_scholar_homepage_url`.
- `selected_citation_count`, `selected_citation_source`: metric used for ranking. Google Scholar is used only for high-confidence paper-list matches; otherwise Semantic Scholar is used.
- `profile_query_status`: whether the external profile was queried or skipped by profile limit.
- `notes`: ambiguity, fallback, profile-limit, or API-error details.
- `wikipedia_title`, `wikipedia_url`, `wikidata_id`, `wikidata_description`.
- `wikipedia_summary`, `wikipedia_evidence`, `wikidata_evidence`.
- `academic_titles`: academic/employment/title evidence from Wikipedia/Wikidata, such as professor, scientist, chair professor, employer, or affiliation.
- `honors_awards`: award and honor evidence, such as Fellow status, prizes, medals, academy memberships, or highly cited researcher notes.
- `professional_memberships`: professional society and academy membership evidence.
- `leadership_roles`: leadership, chair, director, editor, or similar role evidence.
- `personal_homepage_url`: Google Scholar/Semantic Scholar homepage URL when available and identity-verified as a personal, lab, or university profile page; otherwise a deep-search-style personal/school homepage candidate only after same-person validation.
- `personal_homepage_evidence`: title/honor/role snippets extracted from that homepage.
- `personal_homepage_summary`: short homepage title/description/body summary used when no explicit honor/title evidence is found.
- `personal_homepage_identity_status`: same-person validation status, such as `verified`, `verified_by_profile_link`, `rejected`, or `unverified`.
- `personal_homepage_identity_confidence`: name-match confidence used during homepage validation.
- `personal_homepage_identity_evidence`: matched affiliation, research-interest overlap, education/background snippets, and source-context evidence used to decide whether the homepage is the same person.
- `personal_homepage_rejection_reason`: why a homepage candidate was not accepted, such as `insufficient_identity_evidence`.
- `profile_evidence_sources`: evidence sources used for the structured profile fields, such as `wikipedia`, `wikipedia_infobox`, or `wikidata`.
- `notability_confidence`: profile-name match/evidence confidence used before adding a row to `notable_citations`.
- `expert_query_status`: Wikipedia/Wikidata enrichment outcome, such as `notable`, `rejected`, `not_found`, `wiki_api_error`, or `not_queried_outside_expert_scope`.
- `expert_rejection_reason`: reason a queried author did not enter `notable_citations`, such as `no_wikipedia_or_wikidata_match`, `low_name_confidence`, `no_academic_profile_hint`, `no_explicit_honor_or_role`, or `disambiguation_page`.
- `is_notable`: `True` only when the match is a high-confidence scholar/person page with explicit evidence.
- `notable_reason`: evidence copied into notable-scholar outputs.

### `citation_locations`

Reliable in-body citation locations.

- `citing_title`, `source_platforms`, `doi`: citing-paper metadata.
- `pdf_path`: local PDF analyzed.
- `page`: 1-based PDF page number.
- `line_start`, `line_end`: line range in the extracted page text.
- `citation_marker`: verified numeric citation marker or explicit target-name cue.
- `match_type`: reliable cue type used to keep the context.
- `confidence`: heuristic confidence score.
- `context`: extracted in-body citation context.
- `is_positive`: whether the context contains positive/affirmative language.
- `reference_marker`, `reference_score`, `reference_evidence`, `reference_entry`: target-paper reference entry evidence used to validate the body location.

### `downloaded_papers`

Successfully downloaded or manually supplied PDF rows.

- Core citing-paper metadata from `papers`, including `citing_title`, `citing_authors`, `publication_year`, `venue`, `doi`, `url`, `citation_count`, and source IDs.
- `pdf_path`: local PDF path.
- `download_status`: usually `downloaded`, or `manual` when supplied through the manual workflow.
- `download_url`: final URL that returned a PDF when available.
- `candidate_urls`: candidate PDF/landing URLs considered for the paper.
- `expected_pdf_path`, `manual_pdf_path`: manual workflow paths when present.

### `download_failures`

Papers that were not successfully downloaded.

- Core citing-paper metadata from `papers`.
- `pdf_url`, `open_access_pdf_url`, `url`, `doi`: source and candidate address fields useful for manual search.
- `download_status`, `failure_reason`: failure state and reason.
- `candidate_urls`: all candidate URLs attempted or suggested.
- `expected_pdf_path`: preferred local path for manual download.
- `manual_pdf_path`: path to fill if downloaded manually elsewhere.

### `manual_download_todo`

Failed or missing PDF rows for manual completion.

- All core citing-paper columns from `papers`.
- `candidate_urls`: semicolon-separated URLs that were attempted or may help manual search.
- `expected_pdf_path`: preferred local path to save the manually downloaded PDF.
- `manual_pdf_path`: optional path to fill when the PDF is saved somewhere else.

The `analyze` command reads this sheet automatically and includes rows whose `manual_pdf_path` or `expected_pdf_path` points to an existing PDF.

### `notable_citations`

Notable scholars and the citing papers in which they cite the target.

- `author_name`, `selected_citation_count`, `selected_citation_source`.
- `notable_reason`, `wikipedia_url`.
- `citing_title`, `publication_year`, `venue`, `source_platforms`.
- `analysis_status`, `location_count`, `pages`, `citation_markers`.
- `citation_location_status`: human-readable location/coverage status.
- `citation_context_sample`: first reliable context sample when available.

### `run_notes`

- `key`: timestamped note key, such as `find.rows`, `authors.profile_queries`, or `analyze.location_rows`.
- `value`: recorded parameter, count, status, or statistic.

Network tuning notes are recorded here when present, including `find.workers`, `authors.semantic_scholar_workers`, and `authors.wikipedia_workers`.

Google Scholar discovery diagnostics are recorded here when present:

- `find.require_google_scholar`, `find.scholar_captcha_action`, `find.scholar_captcha_timeout`, `find.status`.
- `find.google_scholar.rows`, `find.google_scholar.raw_rows`, `find.semantic_scholar.rows`.
- `find.google_scholar.status`, `find.google_scholar.partial_failure`: present when target matching succeeded but later pagination/captcha/driver handling failed after some Google Scholar rows were already collected; the partial rows remain in `papers`.
- `find.google_scholar.captcha_status`: `none`, `resolved`, or `blocked`.
- `find.google_scholar.browser_pid`, `find.google_scholar.reported_cited_by_count`.
- `find.google_scholar.target_found`, `find.google_scholar.target_title`, `find.google_scholar.target_cited_by_url`.
- `find.google_scholar.current_url`, `find.google_scholar.page_title`.
- `find.google_scholar.events_json`: timestamped browser/search/captcha/pagination events.
- `find.platform_errors_json`: platform failures such as captcha blocks or API errors.

Author expert diagnostics are also summarized:

- `authors.google_scholar.browser`, `authors.google_scholar.captcha_action`, `authors.google_scholar.captcha_timeout`.
- `authors.google_scholar.skip_author_profiles`: `True` when author Google Scholar profile pages were intentionally skipped for unattended refreshes.
- `authors.google_scholar.browser_status`, `authors.google_scholar.captcha_status`, `authors.google_scholar.cookie_count`.
- `authors.google_scholar.final_url`, `authors.google_scholar.page_title`.
- `authors.google_scholar.events_json`, `authors.google_scholar.retry_events_json`.
- `authors.google_scholar.match_status_counts_json`, `authors.google_scholar.selected_count`.
- `authors.wikipedia_checked`, `authors.wikipedia_scope`, `authors.wikipedia_workers`.
- `authors.homepage_checked`, `authors.homepage_search_checked`.
- `authors.expert_status_counts_json`.
- `authors.expert_rejection_counts_json`.

## Legacy Debug Tables

When `--export-legacy-csv` is enabled, the script also writes old-style CSV/XLSX tables for debugging or downstream compatibility:

- `target.json`
- `citing_papers.csv`
- `download_manifest.csv`
- `download_failures.csv`
- `manual_download_todo.csv`
- `citation_paper_coverage_reliable.csv`
- `citation_locations_reliable.csv`
- `citation_locations_reliable.xlsx`
- `author_candidates.csv`
- `author_expert_profiles.csv`
- `notable_scholar_citing_papers.csv`

These files are not the canonical output. Dashboard generation and later phases prefer `citation_report.xlsx`.

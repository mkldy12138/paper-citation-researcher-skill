# Output Schema

## `citing_papers.csv`

- `dedupe_key`: DOI-based or normalized-title key used for merging platforms.
- `source_platforms`: semicolon-separated platforms where the citing paper was found.
- `source_record_ids`: semicolon-separated source IDs or source URLs.
- `citing_title`: title of the citing paper.
- `citing_authors`: author string from the source platform.
- `publication_year`: publication year when available.
- `venue`: venue or source metadata string.
- `doi`: citing-paper DOI when available.
- `url`: landing page URL.
- `pdf_url`: direct PDF URL found by Google Scholar.
- `open_access_pdf_url`: open PDF URL from Semantic Scholar.
- `citation_count`: citation count for the citing paper. Google Scholar and Semantic Scholar rows always provide this value; use `0` when the source has no citation count for the paper.
- `semantic_scholar_paper_id`: Semantic Scholar paper ID.
- `google_scholar_cited_by_url`: Google Scholar cited-by URL when present.
- `arxiv_id`: arXiv external ID.
- `acl_id`: ACL Anthology external ID.
- `abstract`: Semantic Scholar abstract when available.

## `download_manifest.csv`

Includes all `citing_papers.csv` columns plus:

- `pdf_path`: local PDF path for successful downloads.
- `download_status`: `downloaded` or `failed`.
- `download_url`: final PDF URL used for a successful download.
- `failure_reason`: error details for failed downloads.

## `manual_download_todo.csv`

Includes failed download rows plus:

- `candidate_urls`: semicolon-separated URLs that were attempted or may help manual search.
- `expected_pdf_path`: preferred local path to save the manually downloaded PDF.
- `manual_pdf_path`: optional path to fill when the PDF is saved somewhere else.

The `analyze` command reads this file automatically and includes rows whose `manual_pdf_path` or `expected_pdf_path` points to an existing PDF.

## `citation_locations_reliable.csv`

- `citing_title`: title of the citing paper.
- `source_platforms`: source platforms inherited from metadata.
- `doi`: citing-paper DOI.
- `pdf_path`: local PDF analyzed.
- `page`: 1-based PDF page number.
- `line_start` / `line_end`: line range in the extracted page text.
- `citation_marker`: verified body citation marker, such as a numeric reference marker or explicit target-paper mention.
- `match_type`: heuristic used to keep the location, such as verified numeric reference or explicit title/name mention.
- `confidence`: heuristic confidence score.
- `context`: extracted in-body citation context.
- `is_positive`: whether the context contains positive/affirmative language.
- `reference_marker`: target paper's marker in the citing paper's reference section when available.
- `reference_score`: heuristic score for the matched target-paper reference entry.
- `reference_evidence`: short evidence used to match the target reference entry.
- `reference_entry`: matched reference-section entry text.

## `citation_paper_coverage_reliable.csv`

- `citing_title`: title of the citing paper.
- `source_platforms`: source platforms inherited from metadata.
- `doi`: citing-paper DOI.
- `download_status`: PDF download status from the manifest.
- `analysis_status`: per-paper analysis status, such as `cited_in_body`, `target_reference_found_no_body_hits`, `target_reference_not_found`, `pdf_not_downloaded`, `pdf_missing`, or `pdf_parse_failed`.
- `pdf_path`: local PDF analyzed or expected PDF path.
- `location_count`: number of reliable body citation locations found.
- `pages`: semicolon-separated pages where reliable body locations were found.
- `reference_marker`: target paper's marker in the citing paper's reference section when available.
- `reference_score`: heuristic score for the matched target-paper reference entry.
- `reference_evidence`: short evidence used to match the target reference entry.
- `failure_reason`: parse/download/manual-coverage failure details when available.
- `reference_entry`: matched reference-section entry text.

## `citation_locations_reliable.xlsx`

Workbook with:

- `locations`: rows from `citation_locations_reliable.csv`.
- `per_paper_summary`: reliable location counts, positive counts, pages, markers, and match types grouped by citing paper.
- `coverage`: rows from `citation_paper_coverage_reliable.csv`.

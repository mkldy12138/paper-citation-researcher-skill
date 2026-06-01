# Paper Citation Researcher Skill

这是一个可直接安装到 Codex/Claude 项目本地 skills 目录的 citation-research workflow 包。

## 文件

- `paper-citation-researcher-skill.zip`: skill 压缩包，解压后根目录为 `paper-citation-researcher/`。
- `SHA256SUMS.txt`: zip 文件的 SHA-256 校验值。

## 功能

- 按论文标题或 DOI 查询 citing papers。
- 同时支持 Google Scholar 和 Semantic Scholar。
- Google Scholar 默认使用 `--scholar-locale zh-CN`，并按 reported cited-by count 翻页。
- `citing_papers.csv` 中 Google Scholar 和 Semantic Scholar 的 `citation_count` 均不会留空；无引用数时写 `0`。
- 下载可公开访问的 PDF，并生成失败下载清单。
- 从 PDF 中抽取正文引用上下文，生成 CSV 和 Excel 汇总。

## 安装

将 zip 解压到目标环境的 skills 目录，例如：

```powershell
Expand-Archive .\paper-citation-researcher-skill.zip -DestinationPath "$env:CODEX_HOME\skills"
cd "$env:CODEX_HOME\skills\paper-citation-researcher"
py -m pip install -r requirements.txt
```

如果目标项目使用项目本地 skills 目录，也可以解压到：

```text
<project>/.claude/skills/
```

## 使用

```powershell
cd "$env:CODEX_HOME\skills\paper-citation-researcher"
py scripts/paper_citation_researcher.py run --paper "Attention Is All You Need" --output ".\citation-output" --max-papers 1000 --browser edge --scholar-locale zh-CN --download-workers 4
```

可选配置：

- `SEMANTIC_SCHOLAR_API_KEY`: Semantic Scholar API key，可不设置。
- `--s2-api-key` / `--s2-api-key-env`: 覆盖默认 API key 来源。
- `--max-papers`: 默认 `1000`。

## 验证

本包生成前已通过：

```powershell
py scripts/test_merge_and_download_logic.py
py scripts/test_scholar_url_logic.py
```

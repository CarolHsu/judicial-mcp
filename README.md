# judicial-mcp — 憲法法庭判決 MCP Server

把[憲法法庭網站「判決」](https://cons.judicial.gov.tw/judcurrentNew1.aspx?fid=38)的資料（111 年起的憲判字判決）
爬下來、正規化進 SQLite，並以 MCP server 提供查詢。除了判決本文，**每筆判決附帶的 PDF（聲請書、答辯書、
言詞辯論意旨書、專家諮詢意見書、法庭之友意見書、大法官意見書、判決摘要…）也都轉成文字並可全文搜尋**。

## 安裝到 Claude（本機）

需求：macOS、[uv](https://docs.astral.sh/uv/)。

```bash
cd /Users/shesee/Documents/work.nosync/judicial-mcp
uv sync --extra ocr          # 安裝相依套件（ocr extra 只有要自己跑 OCR 時才需要）
uv run judicial-mcp stats    # 確認資料庫在、看看資料量
```

### Claude Code

```bash
claude mcp add judicial -s user -- uv --directory /Users/shesee/Documents/work.nosync/judicial-mcp run judicial-mcp
```

然後在 Claude Code 裡輸入 `/mcp` 確認 `judicial` 是 connected。

### Claude Desktop

編輯 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "judicial": {
      "command": "/usr/local/bin/uv",
      "args": ["--directory", "/Users/shesee/Documents/work.nosync/judicial-mcp", "run", "judicial-mcp"]
    }
  }
}
```

（Desktop 不吃 shell 的 PATH，所以 `uv` 要寫絕對路徑，用 `which uv` 查。）重開 Claude Desktop。

### 免安裝（網址）模式預覽

同一份程式也能用 Streamable HTTP 跑起來，給「別人只要貼網址」的方案做 demo：

```bash
uv run judicial-mcp serve --http --port 8765
claude mcp add --transport http judicial-http http://127.0.0.1:8765/mcp
```

正式對外部署前還需要：放到雲端主機、加 HTTPS、視情況加認證與 rate limit。

## Demo 可以問的問題

- 「憲法法庭有哪些判決跟地方自治有關？各自結論是什麼？」
- 「111年憲判字第6號的主文是什麼？哪些大法官提出意見書、立場為何？」
- 「萊豬案裡，臺北市議會在言詞辯論意旨書中主張了什麼？行政院怎麼答辯？」
- 「哪些判決涉及刑法第 xx 條？」
- 「專家諮詢意見書中，有哪些學者討論到『比例原則』？引用頁碼。」
- 「找出所有提到『健康權』的判決理由段落，並附段碼。」

## 提供的工具

| 工具 | 說明 |
|---|---|
| `search_judgments` | 全文搜尋判決主文/理由，回傳字號、段碼、命中片段 |
| `search_documents` | 全文搜尋附件 PDF 文字，可限定文件類型、判決、提出者；以頁為單位回傳 |
| `get_judgment` | 判決基本資料、主文、相關法令、併案、附件統計 |
| `get_judgment_paragraphs` | 依段碼【n】讀理由原文 |
| `list_judgments` | 列出判決，可依年度/關鍵字篩選 |
| `list_documents` | 列出某判決的附件 |
| `read_document` | 分頁讀附件全文（一次最多 20 頁） |
| `find_judgments_by_statute` | 依「相關法令」找判決 |
| `corpus_info` | 資料概況、處理進度 |

判決字號可以寫 `111年憲判字第6號`、`111憲判6` 或 `111-6`。

## 資料處理流程

```
crawl ──► download ──► extract ──► index ──► ocr ──► ocr --upgrade-site-ocr
列表+內頁   附件 PDF     抽文字層     全文索引   補掃描頁   用 Apple Vision 重新辨識網站附的 OCR
```

```bash
uv run judicial-mcp update                    # crawl + download + extract + index（增量，可重複跑）
uv run judicial-mcp ocr                       # OCR 沒有文字層的頁面（macOS）
uv run judicial-mcp ocr --upgrade-site-ocr    # 也重新辨識「網站 _OCR 版」的頁面，品質較好
uv run judicial-mcp stats                     # 看進度
```

資料放在專案的 `data/`。若改用 `uv tool install` / `uvx` 等非專案目錄的安裝方式，請設定環境變數 `JUDICIAL_MCP_DATA` 指向資料目錄：

- `data/judicial.db`：SQLite（判決、段落、法令、附件、逐頁文字、FTS5 全文索引）
- `data/raw/html/`：原始網頁，解析規則改了可以直接重跑，不用重爬
- `data/raw/files/`：附件 PDF

### PDF 文字的處理細節

- 網站上很多附件有兩個版本：掃描原檔、加了 OCR 文字層的 `_OCR` 版。只下載 `_OCR` 版，原檔保留連結。
- 每一頁獨立判斷：有文字層就直接抽；沒有（純掃描）就標記 `pending_ocr`，交給 Apple Vision OCR。
- 網站附的 OCR 品質普通（例如「憲法」辨識成「蕙法」），`--upgrade-site-ocr` 會用 Apple Vision 重做；
  若新結果字數明顯較少則保留原本的。
- 清理書狀雜訊：稿紙左側行號（1 2 3 … 26）、數字被拆開（`1 1 1 年` → `111年`）、中文斷行、康熙部首字。
- 每頁記錄文字來源（`native` / `site_ocr` / `ocr`），查詢結果會回傳 `text_source`，方便判斷可信度。

### 搜尋

SQLite FTS5 + trigram tokenizer：三字以上的詞走索引；兩字詞（如「人權」「隱私」）自動改用 LIKE 比對。
多個詞以空白分隔，全部須命中。

## 開發

```bash
uv sync --extra ocr
uv run pytest --cov=judicial_mcp
```

測試使用 `tests/fixtures/` 中存下的真實網頁與 PDF，不需要網路。

## 已知限制

- 目前只涵蓋「判決」（fid=38）。裁定、不受理決議、舊大法官解釋（釋字）可沿用同一套 parser 擴充。
- 內頁中「準備程序筆錄」「說明會」「言詞辯論」等區塊是 JavaScript 動態載入，尚未抓取。
- OCR 只支援 macOS（Apple Vision）。其他平台仍可使用已建好的資料庫，只是不能自己跑 OCR。
- 網站的 SSL 憑證缺 Subject Key Identifier，Python 3.13 預設會拒絕；程式只放寬這一項檢查，其餘照常驗證。

判決書依著作權法第 9 條不得為著作權標的；附件中的書狀、意見書使用時請註明出處（工具回傳皆附 `source_url`）。

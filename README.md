# Personal Finance Pipeline

Parses ICICI bank and credit card statements, deduplicates across overlapping
periods, reconciles internal transfers, categorizes every transaction against a
fixed taxonomy, and appends the result to an Excel workbook.

Built for three accounts: one ICICI savings account and two ICICI credit cards
(Amazon and standard).

---

## Setup

Install dependencies into the project virtual environment:

```
.\.venv\Scripts\python.exe -m pip install pandas openpyxl xlwings google-genai
```

Set the classification API key as an environment variable. Gemini:

```
setx GEMINI_API_KEY "your-key"
```

Restart PyCharm fully afterwards — it reads environment variables at launch.
For Anthropic instead, set `ANTHROPIC_API_KEY` and change
`CLASSIFICATION_PROVIDER` in `pipeline_config.py`.

Everything else is configured in **`pipeline_config.py`**. Nothing outside that
file holds a path or a setting.

| Setting | Purpose |
|---|---|
| `SAVINGS_DIRECTORY`, `AMAZON_CARD_DIRECTORY`, `STANDARD_CARD_DIRECTORY` | Folders scanned for statements. Every matching file is loaded. |
| `WORKBOOK_PATH` | The Excel workbook written to |
| `CATEGORIES_PATH` | `config/categories.md` — the authoritative taxonomy |
| `MERCHANT_MAP_PATH` | `cache/merchant_map.json` — the merchant classification cache |
| `CLASSIFICATION_LIMIT` | `0` skips classification entirely, `None` classifies everything, an integer caps it |
| `CLASSIFICATION_BATCH_SIZE` | Merchants per API call. Lower this if responses get truncated. |
| `ABORT_ON_BALANCE_DISCREPANCY` | `True` stops the run on any balance mismatch |

---

## Workbook prerequisites

The writer refuses to run unless the workbook matches the expected layout.

- `Detailed_Transactions` columns A–K, with `Transaction_ID` in `K1`
- `Monthly_Summary` with `Total_Investment` in `D1`
- `Monthly_Summary!A2` and `Account_Summary!A2` holding the `SUMIFS` formulas
  that exclude `Transfers`

Without the transfer exclusion the summaries overstate expense badly — on one
test month, by 79%, almost all of it credit card bill payments counted alongside
the purchases they settle.

See `workbook-structure.md` for the full column mapping and both formulas.

---

## Running it

### Monthly update

```
.\.venv\Scripts\python.exe run_monthly_update.py
```

Runs the pipeline, prints a summary, and asks twice: once before appending
transactions, once before appending review queue rows. Answering no writes
nothing.

Rows already in the workbook are detected by `Transaction_ID` and skipped, so
re-running is safe.

### Review queue only

```
.\.venv\Scripts\python.exe write_review_queue.py
```

Writes the `Review_Queue` sheet without touching `Detailed_Transactions`.

### Refresh categories on existing rows

```
.\.venv\Scripts\python.exe refresh_categories.py
```

Matches existing workbook rows on `Transaction_ID` and rewrites only columns
G–J from the current cache. Used after resolving review queue entries, so
corrections reach rows that were already written.

### Pipeline only, no writes

```
.\.venv\Scripts\python.exe run_pipeline.py
```

Loads, categorizes, and reports. Writes the merchant cache but never the
workbook. Useful for checking a new statement parses before committing to a
write.

---

## The monthly cycle

1. Drop new statements into the three statement directories.
2. Run `run_monthly_update.py`. Confirm both prompts.
3. Open the workbook, go to `Review_Queue`, fill in `Resolved_Category` and
   `Resolved_Subcategory` on rows worth resolving. Both cells must be filled,
   and the pair must exist in `categories.md` exactly.
4. Save and close Excel.
5. Run `refresh_categories.py`. Your resolutions become permanent `manual`
   cache entries and are applied to rows already in the ledger.

Manual entries are never overwritten by the classifier. An invalid pair is
reported by name rather than written.

---

## How it works

| Stage | Module |
|---|---|
| Discover and load statement files | `statement_loader.py` |
| Parse savings statements | `savings_statement_reader.py` |
| Parse card statements | `credit_card_statement_reader.py` |
| Assign identifiers, deduplicate, reconcile transfers | `transaction_pipeline.py` |
| Structural categorization rules | `categorization_rules.py` |
| Merchant cache | `merchant_map_cache.py` |
| Taxonomy loading and validation | `category_taxonomy.py` |
| LLM classification | `merchant_classifier.py` |
| Rules then cache, per transaction | `transaction_categorizer.py` |
| Workbook read and write | `workbook_writer.py` |
| Review queue | `review_queue.py` |
| Orchestration | `run_pipeline.py` |

Categorization resolves in three steps, cheapest first: structural rules (card
payments, ATM withdrawals, EMI components, SIP debits), then the merchant cache,
and only genuinely unseen merchants reach the API.

---

## Things that will bite you

**Identifiers are assigned per file, before concatenation.** The dedup hash
includes a within-group sequence number. Assigning identifiers across a combined
list shifts those numbers and overlapping rows read as new transactions. Nothing
in the code prevents the wrong call — see `schema.md`.

**Balance continuity is the strongest correctness check.** It walks each savings
statement's opening balance forward and compares against the bank's own running
balance. A mismatch means an amount was misparsed and every downstream total
inherits the error.

**Some merchants are permanently unknowable.** ICICI truncates Paytm QR
identifiers, so hundreds of payments at different shops share one narration
string. No prompt fixes that; the information is absent from the source.

**Cash is out of scope.** ATM withdrawals are `Transfers > ATM Withdrawal`.
What the cash was spent on is invisible.

---

## Files not in the repository

`cache/merchant_map.json`, `logs/pipeline.log`, the statements themselves, and
the workbook are all gitignored. The cache is worth backing up separately —
rebuilding it means re-classifying every merchant.

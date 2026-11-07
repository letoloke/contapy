# ContaPy

A HomeBank-inspired, local-first personal finance dashboard built with **Python, PySide6 and SQLite**. The welcome screen, account ledger and transaction editor are from-scratch PySide6 interpretations of [HomeBank](https://www.gethomebank.org/) — fully interactive, not mockups.

This is totally vibe coding, using first DeepSeek-Harness and then (while on Omarchy) OpenCode. Im not quite sure what I'm doing honestly; I just love Homebank, but a few things I didn't like, so I kind of made this

![ContaPy welcome screen](screenshots/welcome.png)

*(Compact layout at 1500×870: [screenshots/welcome-compact.png](screenshots/welcome-compact.png))*

## HomeBank inspiration

The layout, terminology and dark chrome follow HomeBank: grouped accounts with **Reconciled / Cleared / Today / Future** columns, the total and time charts, the Scheduled / Future / Remind strip at the bottom, and a separate **account ledger** window with filters, running balances and status icons. Everything is implemented independently in Python/PySide6; this is not the HomeBank codebase and is not affiliated with the HomeBank project.

The account **Ledger** and the **Transaction editor** are implemented as separate windows, like HomeBank's own windows. Budget and Statistics reports are the next natural steps for a fuller HomeBank-style app. The current build uses its own SQLite store; opening HomeBank `.xhb` files or importing QIF/OFX/QFX is not implemented yet.

## Transaction editor

![ContaPy transaction editor](screenshots/transaction.png)

The editor follows HomeBank's transaction dialog: **Expense / Income / Transfer** tabs, date and signed amount with currency code, account, payment mode, number, payee, category, status icons, memo and tags. Payee, category, payment and tags are editable with type-to-search completion.

Keyboard-first behaviour:

- **Enter** saves from any field (including an open completion popup).
- **Tab / Shift+Tab** moves through the form; info buttons are skipped.
- **Alt+E / Alt+I / Alt+T** switch Expense / Income / Transfer.
- **Ctrl+0…4** set None / Flag / Cleared / Reconciled / Remind.
- **Escape** cancels.

Transfers create two linked transaction legs (one per account) and are deleted together.

## Importing bank CSVs

![CSV import preview](screenshots/import.png)

CSV import auto-detects HomeBank-style English and Spanish headers, ignores accents and punctuation, and previews the mapped rows before importing. Every field in the **Header mapping** grid is an editable dropdown — Date, Amount, Payee, Memo, Payment, Number, Category, Tags, Account, Status and the four flags. The supplied bank file maps like this:

| File column | ContaPy field |
|---|---|
| Fecha | Date |
| Importe | Amount |
| Beneficiario | Payee |
| Memo | Memo |
| Pago | Payment |
| Número | Number |
| Categoría | Category |
| Etiquetas | Tags |

Pick the target account in the dialog. When `Beneficiario` is blank, the **Use Memo as payee** option (on by default) makes the bank description searchable as the payee while keeping the memo. This exact file imports as 70 transactions totalling 35,038.47; a fixture test locks that behaviour in.

Mappings are remembered automatically. After an import, the current field mapping is saved under a signature of the file's headers (column order, case and accents are ignored). The next file with the same header set opens with **Saved mapping loaded for these columns** and the dropdowns already set. Changing any dropdown and importing updates the saved profile.

## Account ledger

![ContaPy account ledger](screenshots/ledger.png)

Double-click an account (or press `Ctrl+L`) to open its ledger. It follows HomeBank's account window: date/payee/type/status filters, a search box, newest activity first with a running balance per row, status icons for cleared/reconciled/remind/flag, reconciled–cleared–today–future balances, and Add / Inherit / Edit / Delete actions. Select rows to mark them cleared or reconciled, or to toggle remind and flag.

The ledger opens focused on the newest transaction:

- **↑ / ↓** move through transactions; **Home / End** jump to the newest/oldest.
- **Enter** opens the selected transaction in the editor.
- **Delete** deletes it (with confirmation).
- **Enter** in the search box jumps focus to the filtered results.
- **Tab / Shift+Tab** return to the filters when needed.

## What the welcome page includes

- **Account tree** — Bank, Cash, Credit card and Savings groups with collapsible rows, warning markers, and the four reference columns: **Reconciled, Cleared, Today, Future**. Group totals and the grand total update from the ledger. The list opens focused: **↑/↓** walk the accounts, **Home/End** jump, and **Enter** opens the selected account's ledger.
- **Spending donut** — top ten expense categories plus *Other*, drawn with `QPainter`. Hover a slice for the category, amount and share. Switch periods from the footer.
- **Spending & Revenue bars** — twelve months of income above zero and spending below, with the exact plotting style of the reference (green up, red down, 100k grid, year tag). Hover a month for income, spending and net.
- **Scheduled strip** — Scheduled lists upcoming bills; Future and Remind are filtered views of the ledger (posted future-dated transactions and reminder-flagged transactions), just like HomeBank. Scheduled rows have working **Skip**, **Edit & Post** and **Post** actions; ledger rows open the account ledger.
- **Reference chrome** — the File/Edit/View/Manage/Transactions/Reports/Tools/Help menu, emoji shortcut toolbar, account footer tools, filter flyout, and the “Your accounts” status row.

The demo figures are aligned to the reference: last 30 days **$167,248.99**, reconciled **$20,289.30**, today/future **−$97,263.62**.

## Features beyond the screenshot

- **Account ledger** — a HomeBank-style transaction window per account, with date/payee/type/status filters, a search box, running balance, reconciliation/remind/flag icons, account balance summary, and add/edit/inherit/delete actions.
- **Transaction editor** — Expense/Income/Transfer tabs, payment mode, number, tags, status icons, type-to-search combos, and Enter-to-save.
- **CSV import** — automatic English/Spanish header detection, editable field mapping, remembered header profiles, mapped-row preview, target-account selection and memo-to-payee fallback.
- Schedule one-off bills; post or skip them from the home strip.
- Mark posted transactions as cleared, reconciled, remind or flagged; these drive the home balance columns and Future/Remind lists.
- SQLite persistence (no server, no account, no telemetry).
- CSV import/export, chart PNG export, demo-data reset, keyboard shortcuts.
- Responsive chart legends and axis labels down to a 1400×760 window.

## Run it

Requires **Python 3.10+** and **PySide6 6.6+**.

```bash
cd contapy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

On Arch, `sudo pacman -S pyside6` is usually enough (no venv needed).

```bash
python3 main.py                 # normal launch
python3 main.py --db my.db      # use a specific database
CONTAPY_DB=/tmp/demo.db python3 main.py
```

The first launch seeds a demo dataset. Data lives at `~/.local/share/contapy/contapy.db` (honouring `XDG_DATA_HOME`). Use **Preferences → Reset demo data** to return to the seeded state.

> **Upgrading from Budget:** if the old `~/.local/share/budget/budget.db` exists, the first ContaPy launch copies it to the new location automatically. The original file is left untouched. `CONTAPY_DB` overrides the path; the older `BUDGET_DB` variable is still honoured.

### Screenshot mode

The welcome image above was rendered without a compositor:

```bash
python3 main.py --screenshot screenshots/welcome.png --size 1850x835
```

## Using it

| Action | How |
|---|---|
| New transaction | `Ctrl+N`, the **Add** button, or the toolbar page icon |
| Save the transaction window | `Enter` from any field |
| New account | `Ctrl+Shift+N` or **Manage → New Account…** |
| Open the account ledger | Double-click an account, press `Ctrl+L`, or right-click → **Open ledger** |
| Navigate accounts | `↑` / `↓`; **Home/End** for first/last |
| Open an account's ledger | `Enter` on the selected account |
| Edit an account | The pencil in the sidebar footer, or right-click → **Edit account…** |
| New scheduled bill | **Transactions → New Scheduled Transaction…** |
| Post / skip a bill | Select it in the Scheduled tab, then use the bottom buttons |
| Edit a ledger row | Select it in the strip and click **Open Ledger**, or double-click it |
| Reconcile / remind / flag | Select rows in the ledger, then use the icons in the bottom bar |
| Navigate ledger rows | `↑` / `↓`; **Home/End** for newest/oldest |
| Open a ledger transaction | `Enter` on the selected row |
| Delete a ledger transaction | `Delete` on the selected row |
| Close the account ledger | `Escape` (or `Ctrl+W`) |
| Filter the strip | The **All** account combo and the filter icon |
| Change chart period | The combo in each chart footer |
| Import / export | `Ctrl+I` / `Ctrl+E`; the import dialog auto-detects HomeBank/Spanish headers |
| Refresh | `F5` |
| Preferences | `Ctrl+,` |

In the account list: **↑/↓** move, **Home/End** jump, **Enter** opens the ledger. In the ledger: **↑/↓** move, **Home/End** jump, **Enter** opens the selected transaction, **Delete** removes it, and **Escape** closes the ledger. In the transaction window: **Enter** saves, **Tab** moves, **Alt+E/I/T** switches type and **Ctrl+0–4** sets status. **Escape** cancels. The home strip also supports **↑/↓** and **Enter** (edit scheduled / open future or remind rows). Keyboard shortcuts are also available under **Help → Keyboard Shortcuts**.

### CSV format

```csv
date,account,payee,category,memo,amount,cleared,reconciled,remind,flagged,payment,number,tags
2026-11-06,eCash,Coffee,alimentos,Morning coffee,-85.50,yes,no,no,no,Cash,,
2026-11-07,Banamex,Client payment,Ingresos,Invoice 104,12000.00,yes,yes,no,no,,1042,work
```

`date` and `amount` are required; missing accounts/categories are created during import. Dates may be `YYYY-MM-DD`, `MM/DD/YYYY` or `DD/MM/YYYY`. Status, payment, number and tags columns are optional for older CSVs. Imports also accept HomeBank-style headers (`Fecha`, `Importe`, `Beneficiario`, `Memo`, `Pago`, `Número`, `Categoría`, `Etiquetas`), and a file without an Account column is imported into the account selected in the import dialog. Header mappings can be edited in the dialog and are remembered per header set.

## How it works

```
main.py                     launcher
contapy/
  app.py                    QApplication, icon, screenshot mode
  main_window.py            chrome, menus, actions, refresh
  db.py                     SQLite schema, balances, reports, CSV
  seed.py                   deterministic reference-shaped demo data
  theme.py                  palette, Qt stylesheet, emoji rendering
  models.py                 small dataclasses
  widgets/
    accounts.py             custom-painted account tree and footer
    charts.py               donut, bars, card chrome
    scheduled.py            tabs, table and action bar
    ledger.py               HomeBank-style account ledger window
    dialogs.py              transaction/account/preferences dialogs
    toolbar.py              emoji toolbar
    icons.py                painter-drawn mini icons
tests/test_store.py         headless ledger tests
```

- **All charts are custom-painted** with `QPainter`; there is no matplotlib or QtCharts dependency.
- **Balances are derived from posted transactions**, never stored as display-only snapshots. *Reconciled* and *Cleared* use the transaction statuses; *Future* adds already-posted future-dated transactions. Unposted schedule rows live in the scheduled strip until you post them.
- **Charts are portfolio-wide**; selecting an account highlights it for editing / opening its ledger without filtering the reports, matching the reference’s state.
- The demo data uses a deterministic generator relative to “today”; a fresh seed lands on the reference totals, including the $167,248.99 rolling donut.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Fourteen tests cover the reference balances, the rolling donut total, posting schedules, running ledger balances, reconciled/cleared transitions, the 70-row HomeBank bank-CSV import, custom and remembered header mappings, CSV round-trips, remind flags and demo reset.

## Notes / limitations

- One currency; amounts display with `$`, and the transaction editor labels the configured code (`MXN` by default). No bank syncing.
- Schedules are one-off; there is no recurrence engine yet.
- Splits, payee matching and HomeBank's Budget/Statistics report windows are not implemented yet.
- Internal transfers are stored as two linked legs; CSV export writes those legs separately, and re-importing does not relink them.
- The UI is English while the seeded demo data is Spanish, mirroring the reference.
- Written and tested on Linux/Wayland with Python 3.14, PySide6 6.12 and Qt 6.12; it should run anywhere PySide6 does.
- HomeBank's own file format (`.xhb`) and QIF/OFX/QFX imports are not supported yet; data lives in SQLite.

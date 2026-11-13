# LetoBank

A HomeBank-inspired, local-first personal finance dashboard built with **Python, PySide6 and SQLite**. The welcome screen, account ledger and transaction editor are from-scratch PySide6 interpretations of [HomeBank](https://www.gethomebank.org/) — fully interactive, not mockups.

This is totally vibe coding, using first DeepSeek-Harness and then (while on Omarchy) OpenCode. Im not quite sure what I'm doing honestly; I just love Homebank, but a few things I didn't like, so I kind of made this

![LetoBank welcome screen](screenshots/welcome.png)

*(Compact layout at 1500×870: [screenshots/welcome-compact.png](screenshots/welcome-compact.png))*

## HomeBank inspiration

The layout, terminology and dark chrome follow HomeBank: grouped accounts with **Reconciled / Cleared / Today / Future** columns, the total and time charts, the Scheduled / Future / Remind strip and a compact **Budgets** panel at the bottom, and a separate **account ledger** window with filters, running balances and status icons. Everything is implemented independently in Python/PySide6; this is not the HomeBank codebase and is not affiliated with the HomeBank project.

The account **Ledger**, the **Transaction editor**, the **Reports** window and the full **Budgets** window are implemented as separate windows, like HomeBank's own windows; the dashboard also embeds a compact budgets panel next to the scheduled strip. The current build uses its own SQLite store; opening HomeBank `.xhb` files or importing QIF/OFX/QFX is not implemented yet.

## Transaction editor

![LetoBank transaction editor](screenshots/transaction.png)

The editor follows HomeBank's transaction dialog: **Expense / Income / Transfer** tabs, date and signed amount with currency code, account, payment mode, number, payee, category, status icons, memo and tags. Payee, category, payment and tags are editable with type-to-search completion. A transaction can also be split across multiple categories with the **Split…** row.

Keyboard-first behaviour:

- **Enter** saves from any field (including an open completion popup).
- **Tab / Shift+Tab** moves through the form; info buttons are skipped.
- **Alt+E / Alt+I / Alt+T** switch Expense / Income / Transfer.
- **Ctrl+0…5** set None / Flag / Cleared / Reconciled / Remind / Void.
- **Ctrl+R** marks the transaction being edited as reconciled.
- **Escape** cancels.

Transfers create two linked transaction legs (one per account) and are deleted together.

## Importing bank CSVs

![CSV import preview](screenshots/import.png)

CSV import auto-detects HomeBank-style English and Spanish headers, ignores accents and punctuation, and previews the mapped rows before importing. Every field in the **Header mapping** grid is an editable dropdown — Date, Amount, Payee, Memo, Payment, Number, Category, Tags, Account, Status and the status flags. The supplied bank file maps like this:

| File column | LetoBank field |
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

### Airbnb exports

**File → From Airbnb…** (also in the toolbar's account-actions menu and under **Tools**) converts an Airbnb reservation export and then opens the normal import preview. It drops `Payout` rows, converts `Fecha de inicio` to an ISO date, and builds the memo from the confirmation code, type, space and guest. The result matches the output of the original `airtransa.py` script.

### Booking payouts and Sabee reservations

**File → From Booking…** asks for two files: the Booking finance/payout CSV and the Sabee reservation CSV. It merges them on the Booking number / Sabee Channel ID, adds the Sabee room name to each memo, and unpivots the amount columns (`Amount`, `Commission`, `Payments Service Fee`, VAT and withholding, plus `Final amount`/`Commission amount`/`Payment fee` when present) into one row each. Dates come from `Checkout`/`Departure`; reservations without a matching Sabee room are labelled `Sin habitación`. The result matches the output of the original `tui_consolidator.py` script.

### Banamex statements

**File → From Banamex…** converts a saved Banamex HTML statement and opens the same import preview. It reads the statement's transactions table, converts `08 Nov` dates to ISO using the year from the statement header (rolling December into the previous year for January statements), and cleans up `Concepto de pago`/`Referencia` descriptions. The result matches the original `banahtml.py` script.

### Duplicate rows

Click any preview column header to sort the rows — **Amount** sorts numerically and **Date** chronologically; click again to reverse the order. Sorting is visual only, so the row checkboxes stay attached to their original transactions.

The preview checks every valid row against the transactions already in the target account and marks matches with **Duplicate** in the Status column. This includes **voided** transactions, so re-importing a bank row that already exists still flags it as a duplicate; tick the row manually if you deliberately want another copy. The check uses the **memo as the primary field**, together with the date and amount to avoid flagging recurring payments that share a description. Memo matching ignores case, accents and punctuation. Rows with no memo fall back to payee + date + amount.

Every row has an **Import** checkbox. Rows that are not duplicates start checked; duplicates start unchecked, so importing the same statement twice only adds the new rows. Tick a duplicate to import it anyway, or untick any other row to leave it out. The Import button is disabled when no rows are selected. The check is per account and only compares against transactions already in the database; identical rows inside one CSV are not removed from each other. The import summary reports both unchecked duplicates and unreadable rows.

**Apply automatic assignment rules** is checked by default, so every selected row runs through the rules from **Manage → Rules…** before it is stored. Untick it to import the bank's original payee, category, payment and tags untouched. Existing transactions are never changed by either choice.

## Account ledger

![LetoBank account ledger](screenshots/ledger.png)

Double-click an account (or press `Ctrl+L`) to open its ledger. It follows HomeBank's account window: date/payee/type/status filters, a search box, newest activity first with a running balance per row, columns for category, **tags** and memo (uncategorized rows show **Uncategorized** in red), status icons for cleared/reconciled/remind/flag/void, reconciled–cleared–today–future balances, and Add / Inherit / Edit / Delete actions. Select rows to mark them cleared or reconciled, or to toggle remind, flag and void. Select two or more rows and the ledger highlights the unselected transaction whose amount is closest to their total, and the action bar shows an amber **“Alt+V voids N highlighted rows · reconciles M selected rows”** note; press **Alt+V** to void the highlighted rows and mark the selected rows reconciled. Voided rows stay visible in the ledger but are excluded from balances, reports, charts, future/remind lists and unreconciled alerts. Press **Ctrl+Z** to undo the last ledger change; the **Edit** menu names the action that will be reverted, and up to 50 steps are kept. Click a column header to sort the ledger — **Amount** and **Balance** sort numerically, **Date** chronologically and text columns alphabetically; click again to reverse. Split parents keep their child rows together while sorting. The date filter offers **All date**, **This month**, **Last month**, **This year**, **Last year** and **Custom range…**, which asks for an inclusive start and end date.

Select two or more rows and press **Edit** (or **Enter**) to open **Edit N transactions**. Tick Payee, Category, Payment, Number, Tags or Memo to apply that value to the whole selection; Tags can replace the existing values or be appended with **Add to**. Unticked fields keep their current values, and dates, amounts and accounts are never changed. Transfer legs are skipped so both sides stay in sync.

The ledger opens focused on the newest transaction:

- **↑ / ↓** move through transactions; **Home / End** jump to the newest/oldest.
- **Enter** edits the selection: one transaction opens the normal editor, several open the bulk editor.
- **Delete** deletes it (with confirmation); **Ctrl+Z** restores it.
- **Ctrl+Z** undoes the last ledger change, including flag changes, Alt+V, bulk edits, add/edit/delete and CSV imports.
- **Enter** in the search box jumps focus to the filtered results.
- **Tab / Shift+Tab** return to the filters when needed.

## Split transactions

The transaction editor has a **Split…** row. It opens the split editor, where one bank transaction can be divided across two or more categories.

- Each allocation has its own category, memo, tags and amount.
- Percentage labels show how the bank amount is distributed.
- **Add another split** adds a line; **×** removes one; **Distribute remainder** assigns the unassigned difference to the last line.
- The dialog will not save until there are at least two category allocations and their total matches the transaction amount.
- **Remove split** in the transaction editor returns it to a normal single-category transaction.
- The parent transaction keeps the full bank amount and stays in the account ledger as one parent row with a **Split · N parts** badge. The individual allocations appear beneath it as child rows.
- Balances use the parent amount only. Reports, budgets, category totals, category transaction lists and the spending charts use the split allocations, so nothing is double-counted.
- Selecting a child row acts on its parent transaction. Split parents are edited or deleted one at a time; bulk edit skips them.
- **Ctrl+Z** restores split allocations after an edit or delete.

Scheduled transactions and transfers are not split in this version.

## Subcategories

**Manage → Categories…** now opens a category manager instead of a read-only
list. Expense and income categories are split across two tabs (with counts), so
each list stays short and focused. Add, edit and delete categories, and give any
of them subcategories — HomeBank style, two levels deep. Subcategories show
everywhere as **Parent : Child** (the transaction editor's category field, the
ledger, CSV export), inherit their parent's colour, and must share its type.

- Categories and their subcategories are listed **alphabetically** (case
  insensitive) in the manager, every category picker, the budgets window and
  the reports. Subcategories stay grouped under their parent.
- **New…** adds a category of the active tab's type; picking a parent makes it a
  subcategory. Selecting a row first pre-fills that row as the parent, so adding
  a subcategory is one click. Editing a category moves it to the matching tab if
  its type changes.
- Select a category and press **Enter** (or double-click it) to edit it.
- Categories are also created just by typing them. In the transaction editor,
  type a name that is not in the list and save; type **Parent : Child** (with
  or without spaces around the colon) to create the parent if needed and the
  subcategory in one step. The same text in a CSV import builds the hierarchy
  automatically. Matching is case-insensitive, so existing categories are
  reused rather than duplicated.
- Select a category and press **Delete** (or use the **Delete** button) to
  remove it. A warning asks for confirmation and states that the deletion
  cannot be undone; the safe **Cancel** button is the default.
- **Transactions…** shows every posted transaction filed under the selected
  category in a modal, newest first, with date, account, payee, category,
  status and amount. A parent also includes its subcategories' transactions by
  default (toggle **Include subcategories**), and the search box filters by
  payee, memo, account or tags. A summary line shows the count and net total,
  excluding voided rows.
- Deleting a subcategory moves its transactions to the parent; deleting a
  parent turns its subcategories into top-level categories and leaves its own
  transactions uncategorized.
- Reports list each **Parent : Child** as its own row in the table view, while
  the pie and bar charts and the dashboard donut fold subcategories into their
  parent's total.
- A budget on a category covers its subcategories' spending too; you can also
  budget a subcategory on its own.
- CSV import accepts `parent : child` category text and creates the hierarchy
  automatically; CSV export writes the same format back out.

## Automatic assignment rules

**Manage → Rules…** opens a list of assignment rules. Rules run automatically
when a transaction is **added or imported**, filling in fields for transactions
that match their condition. Existing transactions are not rewritten.

Each rule has two sections:

- **Condition** — search text plus checkboxes choosing whether to look in the
  **Memo**, the **Payee**, or both; **Case sensitive** and **Regular
  expression** options; and an optional **amount filter** with `=` exactly,
  `-` at most and `+` at least. The **AND** box requires both the text and the
  amount to match; unchecked, matching either one is enough. Expenses are
  negative, so “at most −100” finds expenses of 100 or more.
- **Assignments** — **Payee**, **Category**, **Payment**, **Tags** and
  **Notes**. Each has an **Overwrite** box. Checked, the rule replaces the
  existing value; unchecked, it only fills a field that is still empty. Blank
  assignments are skipped, so a rule can set just a category or just tags.

The manager lists each rule's condition and assignments, lets you **New…**,
**Edit…** and **Delete**, and unticking a rule disables it without deleting it.
Rules run from top to bottom, so a later overwrite rule wins. A Category typed
into the rule that does not exist yet is created when you save, including
`Parent : Child` subcategories.

### Importing HomeBank rules

HomeBank keeps its automatic assignments inside the wallet XML. Open
**Manage → Rules… → Import from HomeBank…** and choose a `.xhb` file. LetoBank
reads the `<asg>` rules together with the wallet's payee and category tables,
so references become names and missing categories are created, including
`Parent : Child` subcategories. HomeBank's memo/payee search field,
case-sensitive and regular-expression options, amount equality, payment modes,
tags and overwrite flags are mapped directly; a rule's **Notes** becomes a
Notes assignment. Prefilled rules, rules with no usable assignment and exact
duplicates are skipped, and the summary explains why. Transactions already in
the database are not changed.

## Reports

![LetoBank reports window](screenshots/reports.png)

**Reports → Reports Window…** (`Ctrl+R` in the main window; in a ledger `Ctrl+R` reconciles the selected rows) opens a live report over the current
database. The toolbar's **Spending report** button also opens this window. The
left **Display** panel controls the report:

- **Mode** — **Total** groups the whole date range; **Time** breaks it down by
  month.
- **View by** — Category, Payee or Account (hidden in Time mode).
- **Type** — Expense or Income. Uncategorised transactions appear in both
  reports, as they do in HomeBank.
- **Sort by amount** — largest first instead of the category order.
- **Filter** — free-text search over payee, memo, tags and category, plus an
  account filter.
- **Date range** — All dates, This month, Last month, This year, Last year or
  a custom From/To pair.

The header always shows the **Expense**, **Income** and **Total** for the
filtered rows. Switch between the three views from the toolbar or with
`Ctrl+1` / `Ctrl+2` / `Ctrl+3`:

- **Table** — one row per category/subcategory (`Parent : Child`), payee,
  account or month, with amounts and a totals row.
- **Pie chart** — donut with a legend showing the exact amount and share.
- **Bar chart** — horizontal amount bars in Total mode, or a monthly
  income/spending chart in Time mode.

Every change applies immediately, and open report windows refresh when the
ledger changes or `F5` is pressed.

## Budgets

**Reports → Budgets…** (`Ctrl+B`), or the toolbar's **Budgets** button, opens a
monthly budget window for expense categories. Each category gets a progress bar
comparing this month's spending with its budget, with green, amber and red
states as the month fills up, plus a **Remaining** or **Over by** amount.

The main screen also has a compact **Budgets** panel on the right half of the
bottom strip, beside Scheduled / Future / Remind. It shows the current month's
budgeted, spent and remaining totals with the same per-category rows, has its
own **← / →** month navigation, **This month** and **Set budgets…** actions, and
can be hidden from **View → Budgets Panel**.

- **Set budgets…** lists every expense category. Enter a monthly amount and
  save; enter **0** to remove a budget. Budgets repeat every month.
- **Month starts** in the toolbar chooses the day of the month each budget
  period starts counting (1–31). A start day of 15 makes the January budget run
  from 15 January to 14 February; the header shows the exact date span. Short
  months use their last day, so a start day of 31 becomes 28 February.
- **← / →** move to the previous or next month; **This month** jumps back.
  Past months use the transactions recorded in that month, so trends and
  remaining amounts update automatically.
- Each row shows a **six-month spending trend**. Click the mini chart to open a
  larger per-category trend dialog with the exact monthly amounts.
- The header summarises the total **Budgeted**, **Spent** and **Remaining** for
  the selected month. Voided transactions and income categories are excluded.
  A budget on a category also counts its subcategories' spending, and
  subcategories can carry their own budget.

## What the welcome page includes

- **Account tree** — Bank, Cash, Credit card and Savings groups with collapsible rows, alert markers for accounts with unreconciled transactions, and the four reference columns: **Reconciled, Cleared, Today, Future**. Group totals and the grand total update from the ledger. Account names stay readable when the sidebar narrows: balance columns drop away, least important first, instead of truncating the names. The list opens focused: **↑/↓** walk the accounts, **Home/End** jump, and **Enter** opens the selected account's ledger.
- **Spending donut** — top ten expense categories plus *Other*, drawn with `QPainter`. Switch the footer to **Income** for the top ten income categories, and change periods from the same footer. Hover a slice for the category, amount and share.
- **Spending & Revenue bars** — twelve months of income above zero and spending below, with the exact plotting style of the reference (green up, red down, 100k grid, year tag). Hover a month for income, spending and net.
- **Scheduled strip** — Scheduled lists upcoming bills; Future and Remind are filtered views of the ledger (posted future-dated transactions and reminder-flagged transactions), just like HomeBank. Scheduled rows have working **Skip**, **Edit & Post** and **Post** actions; ledger rows open the account ledger. The bottom area is split horizontally, with a compact **Budgets** panel on the right.
- **Reference chrome** — the File/Edit/View/Manage/Transactions/Reports/Tools/Help menu, icon shortcut toolbar, account footer tools, filter flyout, and the “Your accounts” status row.

The demo figures are aligned to the reference: last 30 days **$167,248.99**, reconciled **$20,289.30**, today/future **−$97,263.62**.

## Features beyond the screenshot

- **Account ledger** — a HomeBank-style transaction window per account, with date/payee/type/status filters (including a custom date range), a search box, running balance, reconciliation/remind/flag/void icons, account balance summary, and add/edit/inherit/delete actions.
- **Transaction editor** — Expense/Income/Transfer tabs, payment mode, number, tags, status icons, type-to-search combos, split allocations, and Enter-to-save.
- **Activity history** — a Markdown action log beside the database with **View Activity History** and **Save Activity History As…** in the File menu, flushed every five minutes.
- **Import menu** — `Ctrl+I` opens a source picker for CSV, Airbnb, Booking and Banamex imports.
- **CSV import** — automatic English/Spanish header detection, editable field mapping, remembered header profiles, mapped-row preview with sortable columns and per-row import checkboxes, optional automatic assignment rules, duplicate detection by memo, target-account selection and memo-to-payee fallback.
- **Airbnb import** — converts Airbnb reservation exports (dropping payout rows and rebuilding memos) before the standard import preview.
- **Booking import** — merges Booking payout and Sabee reservation exports, unpivots the amount columns and adds room names before the standard import preview.
- **Banamex import** — converts saved Banamex HTML statements (dates, memos and amounts) before the standard import preview.
- **Reports window** — HomeBank-style Display panel, Category/Payee/Account and monthly grouping, Expense/Income types, date presets and custom ranges, search and account filters, and table, pie and bar views.
- **Budgets window** — monthly per-category expense budgets with progress bars, remaining/over amounts, month navigation, a configurable day-of-month period start and six-month trend charts that zoom into a larger dialog; the dashboard embeds a compact version beside the scheduled strip.
- **Automatic assignment rules** — a rules manager with Condition (memo/payee search, case-sensitive and regex matching, optional amount filter with AND/OR) and Assignments (payee, category, payment, tags and notes, each with overwrite-or-fill-empty behavior); rules run on newly added and imported transactions.
- **Subcategories** — a category manager with separate Expense/Income tabs, add/edit/delete, per-category transaction lists with search and subcategory roll-up, two-level `Parent : Child` categories everywhere (editor, ledger, CSV import/export), and roll-ups in the donut, report charts and budgets.
- Schedule one-off bills; post or skip them from the home strip.
- Mark posted transactions as cleared, reconciled, remind, flagged or voided; these drive the home balance columns and Future/Remind lists. Voided transactions are kept for the audit trail but ignored by balances and reports.
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

### Switching databases

**File → Open Database…** (`Ctrl+O`) opens another SQLite database without
restarting. LetoBank remembers the choice in `~/.config/contapy/config.json`
(honouring `XDG_CONFIG_HOME`) and reopens that database on the next launch. The
window title shows the database filename so it is always clear which file is
active.

Startup precedence is: `--db`, then `CONTAPY_DB` / `BUDGET_DB`, then the
database remembered from the File menu (only if the file still exists), then
the default location. `--db` and environment overrides are one-off and do not
change what is remembered. To go back to the default database, open it from
the same menu or delete `~/.config/contapy/config.json`.

**File → Save Database As…** (`Ctrl+Alt+S`) writes a consistent snapshot to a
new location and continues working from that copy, so later edits go to the
new file. The new path is remembered for the next launch, and the original
database is left untouched as a safety copy.

### Activity history

LetoBank writes a Markdown record of user actions beside the active database:

```
~/.local/share/contapy/activity-history.md
```

- **File → View Activity History** opens the file in the system Markdown viewer.
- **File → Save Activity History As…** (`Ctrl+Shift+S`) writes a copy to the location you choose.
- Entries are timestamped and append across sessions.
- Buffered actions are written every five minutes while the app is open, and immediately when the history is viewed, saved or the window closes.
- Transaction entries include the payee, amount and memo when one is present.
- The history covers transactions, transfers, scheduled items, imports, exports, account changes, category and rule edits, budget changes, reconciliation/void/undo actions, theme changes and database switching.

Because Ctrl+Shift+S now saves the activity history, **Save Database As…** uses `Ctrl+Alt+S`.

### Daily backups

LetoBank keeps one automatic copy per day in a folder named `dailylbaka` beside
the active database:

```
~/.local/share/contapy/dailylbaka/contapy-2026-11-06.db
```

The backup is created the first time LetoBank runs on a new day, checked again
hourly while the app stays open, and when the app closes. Existing daily files
are never overwritten, so the folder grows by one database per day. Backups are
ordinary SQLite files: to restore one, use **File → Open Database…** to open the
dated file, then **File → Save Database As…** to write it back over your normal
database. Backups follow the database: after **Save Database As…**, the new
location gets its own `dailylbaka` folder.

> **Upgrading from Budget:** if the old `~/.local/share/budget/budget.db` exists, the first LetoBank launch copies it to the new location automatically. The original file is left untouched. `CONTAPY_DB` overrides the path; the older `BUDGET_DB` variable is still honoured.

### Theme

LetoBank defaults to **One Dark**. Open **Preferences** (`Ctrl+,`) and use the
**Theme** selector to switch to any theme installed under
`~/.config/omarchy/themes`, `~/.local/share/omarchy/themes` or
`/usr/share/omarchy/themes`. The choice is remembered in
`~/.config/contapy/config.json` and the window is rebuilt immediately with the
new palette — panels, menus, inputs, selection, status colours and the category
donut all follow it. Both dark and light themes work.

The selector also offers **Omarchy current theme**, which follows
`~/.local/state/omarchy/current/theme/colors.toml` (honouring
`XDG_STATE_HOME`), and **Graphite (built-in)**, the original LetoBank palette.
If the selected theme disappears, LetoBank falls back to the graphite palette;
One Dark itself is bundled so the default works without Omarchy installed.

Environment variables override the saved choice:

```bash
CONTAPY_THEME=builtin python3 main.py                    # ignore the saved theme
CONTAPY_THEME=one-dark python3 main.py                   # force a theme slug
CONTAPY_THEME_FILE=/path/to/colors.toml python3 main.py  # force a palette
```

### Date format and ledger status

**Preferences** also controls how dates are displayed and which transactions the
ledger shows by default.

- **Date format** offers eight styles and defaults to `yyyy/mmm/dd`, rendered
  like `2026/feb/14`. The choice applies immediately to the dashboard, ledgers,
  scheduled dates, reports, import previews and date pickers. Dates remain
  stored and compared as ISO strings, so the setting only changes presentation.
- **Ledger status** chooses the filter applied whenever an account ledger opens:
  **Any status**, **Unreconciled**, **Cleared**, **Reconciled**, **Remind**,
  **Flagged** or **Voided**. The default is **Any status**.

Both choices are remembered in `~/.config/contapy/config.json` alongside the
theme.

Toolbar and status icons come from the bundled Font Awesome Free 6.6 Solid web
font, with the original painted shapes as fallbacks. The font is licensed under
the SIL OFL 1.1; see `contapy/assets/FONT-AWESOME-LICENSE.txt`.

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
| Reconcile selected ledger rows | `Ctrl+R`, the reconcile icon in the bottom bar, or **Tools → Mark Reconciled** |
| Reconcile the transaction being edited | `Ctrl+R` in the transaction editor |
| Split a transaction | **Split…** in the transaction editor |
| Remind / flag / void | Select rows in the ledger, then use the icons in the bottom bar |
| Void the closest highlighted rows and reconcile the selection | `Alt+V` with two or more ledger rows selected; the action bar shows the hint while matches are highlighted |
| Undo the last ledger change | `Ctrl+Z`; the **Edit** menu shows the action that will be reverted |
| Open budgets | `Ctrl+B`, the toolbar **Budgets** button, or **Reports → Budgets…** |
| Show or hide the dashboard budgets panel | **View → Budgets Panel** |
| Set or clear a monthly budget | **Set budgets…** in the budgets window; enter `0` to remove one |
| Browse budget months | `←` / `→` in the budgets window, or **This month** |
| Change when a budget period starts | Choose a day in **Month starts** on the budgets toolbar |
| Add a category or subcategory | **Manage → Categories… → New…**, then pick a parent for a subcategory |
| Create a category while editing a transaction | Type a new name in the **Category** field and save; type `Parent : Child` to add a subcategory |
| Rename, retype or move a category | Double-click it in **Manage → Categories…** |
| Delete a category | Select it in **Manage → Categories…** and press `Delete`, then confirm the irreversible warning |
| Show a category's transactions | Select it in **Manage → Categories…** and press **Transactions…** |
| Create or edit assignment rules | **Manage → Rules…**, then **New…** or **Edit…** |
| Import HomeBank automatic assignments | **Manage → Rules… → Import from HomeBank…**, then choose a `.xhb` file |
| Disable a rule temporarily | Untick it in **Manage → Rules…** |
| Navigate ledger rows | `↑` / `↓`; **Home/End** for newest/oldest |
| Open a ledger transaction | `Enter` on the selected row |
| Delete a ledger transaction | `Delete` on the selected row |
| Close the account ledger | `Escape` (or `Ctrl+W`) |
| Filter the strip | The **All** account combo and the filter icon |
| Change chart period | The combo in each chart footer |
| Import / export | `Ctrl+I` opens the import menu (CSV, Airbnb, Booking, Banamex); `Ctrl+E` exports CSV |
| Import without automatic rules | Untick **Apply automatic assignment rules** in the import dialog |
| Open another database | **File → Open Database…** or `Ctrl+O` |
| Save a copy elsewhere | **File → Save Database As…** or `Ctrl+Alt+S` |
| View activity history | **File → View Activity History** |
| Save activity history as | **File → Save Activity History As…** or `Ctrl+Shift+S` |
| Refresh | `F5` |
| Preferences | `Ctrl+,` |
| Show the keyboard shortcut list | `Ctrl+K` anywhere in the app, or **Help → Keyboard Shortcuts** |

In the account list: **↑/↓** move, **Home/End** jump, **Enter** opens the ledger. In the ledger: **↑/↓** move, **Home/End** jump, **Enter** opens the selected transaction, **Delete** removes it, **Ctrl+R** reconciles the selection, **Ctrl+Z** undoes the last change, and **Escape** closes the ledger. In the transaction window: **Enter** saves, **Tab** moves, **Alt+E/I/T** switches type and **Ctrl+0–5** sets status. **Escape** cancels. The home strip also supports **↑/↓** and **Enter** (edit scheduled / open future or remind rows). **Ctrl+R** in the main window opens the report window, where **Ctrl+1/2/3** switch table, pie and bar views and **F5** refreshes.

Press **Ctrl+K** anywhere in LetoBank to open a searchable list of every shortcut, grouped by context (Global, Accounts list, Account ledger, Transaction window, Categories, Reports and Budgets). Type to filter by shortcut, context or action; **Esc** closes the list.

### CSV format

```csv
date,account,payee,category,memo,amount,cleared,reconciled,remind,flagged,voided,payment,number,tags
2026-11-06,eCash,Coffee,alimentos,Morning coffee,-85.50,yes,no,no,no,Cash,,
2026-11-07,Banamex,Client payment,Ingresos,Invoice 104,12000.00,yes,yes,no,no,,1042,work
```

`date` and `amount` are required; missing accounts/categories are created during import, and category text may be a `parent : child` label, which builds the subcategory automatically. Dates may be `YYYY-MM-DD`, `MM/DD/YYYY` or `DD/MM/YYYY`. Status, payment, number and tags columns are optional for older CSVs. Imports also accept HomeBank-style headers (`Fecha`, `Importe`, `Beneficiario`, `Memo`, `Pago`, `Número`, `Categoría`, `Etiquetas`), and a file without an Account column is imported into the account selected in the import dialog. Header mappings can be edited in the dialog and are remembered per header set.

## How it works

```
main.py                     launcher
contapy/
  app.py                    QApplication, icon, screenshot mode
  config.py                 remembers the last database outside the DB
  dates.py                  selectable date display formats
  main_window.py            chrome, menus, actions, refresh
  db.py                     SQLite schema, balances, reports, CSV
  seed.py                   deterministic reference-shaped demo data
  omarchy.py                reads Omarchy colors.toml, derives semantic tokens
  theme.py                  Qt tokens, stylesheet, palette, font selection
  fontawesome.py            bundled Font Awesome glyph loading and rendering
  models.py                 small dataclasses
  widgets/
    accounts.py             custom-painted account tree and footer
    charts.py               donut, bars, card chrome
    scheduled.py            tabs, table and action bar
    ledger.py               HomeBank-style account ledger window
    dialogs.py              transaction/account/preferences dialogs
    toolbar.py              Font Awesome shortcut toolbar
    icons.py                themed glyph icons with painted fallbacks
    reports.py              report window, table/pie/bar views
tests/test_store.py         headless ledger tests
tests/test_omarchy.py       palette parsing, dark/light tokens and fallbacks
```

- **All charts are custom-painted** with `QPainter`; there is no matplotlib or QtCharts dependency.
- **Balances are derived from posted transactions**, never stored as display-only snapshots. *Reconciled* and *Cleared* use the transaction statuses; *Future* adds already-posted future-dated transactions. Voided transactions are kept in the ledger but never contribute to balances or reports. Unposted schedule rows live in the scheduled strip until you post them.
- **Alert triangles are derived too**: an account shows one while it has posted, past-dated transactions that are not reconciled. Reconcile them in the ledger (or clear future entries when they arrive) to make the marker disappear.
- **Charts are portfolio-wide**; selecting an account highlights it for editing / opening its ledger without filtering the reports, matching the reference’s state.
- The demo data uses a deterministic generator relative to “today”; a fresh seed lands on the reference totals, including the $167,248.99 rolling donut.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Two hundred and ten tests cover the reference balances, the rolling donut total and income breakdown, selectable date formats and their default, the saved ledger status filter, bulk ledger editing, ledger undo, sortable ledger columns, Markdown activity history, Ctrl+R reconciliation in the ledger and transaction editor, split transactions (storage, editing, balanced allocation, ledger children, reports, budgets, category lists and undo), uncategorized category highlighting, responsive account-sidebar columns, closest-amount highlighting for voiding with its Alt+V hint, assignment rules (memo/payee matching, case sensitivity, regular expressions, amount operators and AND/OR, overwrite versus fill-empty, storage, add and import integration and the rules dialogs), subcategories (typed creation in the editor and imports, storage, reports, budgets, category transaction lists, Delete-key removal, Enter-to-edit and the Expense/Income manager tabs), monthly budgets with configurable period start days and six-month budget trends, the dashboard budgets panel beside the scheduled strip, posting schedules, running ledger balances, reconciled/cleared transitions, voided transactions, unreconciled-account alerts, the searchable Ctrl+K shortcut list and its window-level action, HomeBank automatic-assignment import (conditions, payees, categories, payments, tags, notes, overwrite flags, duplicates and invalid references), the 70-row HomeBank bank-CSV import, custom and remembered header mappings, the Ctrl+I import menu, sortable import previews, CSV round-trips, duplicate detection, report aggregation, remind flags, demo reset, the Booking/Sabee consolidation, and Omarchy palette parsing, theme discovery and fallbacks (dark, light, contrast).

## Notes / limitations

- One currency; amounts display with `$`, and the transaction editor labels the configured code (`MXN` by default). No bank syncing.
- Schedules are one-off; there is no recurrence engine yet.
- Splits, payee matching and HomeBank's Budget/Statistics report windows are not implemented yet.
- Internal transfers are stored as two linked legs; CSV export writes those legs separately, and re-importing does not relink them.
- The UI is English while the seeded demo data is Spanish, mirroring the reference.
- Written and tested on Linux/Wayland with Python 3.14, PySide6 6.12 and Qt 6.12; it should run anywhere PySide6 does.
- HomeBank's own file format (`.xhb`) and QIF/OFX/QFX imports are not supported yet; data lives in SQLite.

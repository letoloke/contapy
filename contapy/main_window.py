"""Main window: chrome, layout, actions and data refresh."""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .airbnb import transform as transform_airbnb
from .banamex import transform as transform_banamex
from .booking import transform as transform_booking
from .config import date_format_choice, remember_database, theme_choice
from .dates import set_date_format
from .db import DataStore
from .models import ScheduledItem
from .activity import ActivityLog, activity_log_path, transaction_detail
from .money import money
from .theme import C, font, select_theme
from .widgets.accounts import AccountsPanel
from .branding import APP_NAME
from .widgets.budgets import BudgetWindow, BudgetsPanel
from .widgets.charts import ChartCard, DonutChart, SpendingRevenueChart
from .widgets.import_dialog import CsvImportDialog
from .widgets.ledger import LedgerWindow
from .widgets.reports import ReportsWindow
from .widgets.rules import RulesDialog
from .widgets.dialogs import (
    AccountDialog,
    CategoriesDialog,
    ListDialog,
    PreferencesDialog,
    ShortcutsDialog,
    TransactionDialog,
    about_text,
)
from .widgets.scheduled import ScheduledPanel
from .widgets.toolbar import AppToolbar


class MainWindow(QMainWindow):
    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.activity = ActivityLog(activity_log_path(store.path))
        self.activity.record("Application opened", store.path.name)
        self._flush_activity()
        self.ledgers: dict[int, LedgerWindow] = {}
        self.reports_window: ReportsWindow | None = None
        self.budget_window: BudgetWindow | None = None
        self._initial_focus_done = False
        self._closing = False
        self._keep_store = False
        self._update_window_title()
        self.setMinimumSize(1400, 760)
        self.resize(1500, 870)
        self.setContentsMargins(5, 5, 5, 5)
        self.setStyleSheet(f"QMainWindow {{ background: {C.BORDER_SOFT}; }}")

        self._build_menus()
        self._build_ui()
        self._wire()
        self.refresh_all()

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)

        self._backup_timer = QTimer(self)
        self._backup_timer.setInterval(60 * 60 * 1000)
        self._backup_timer.timeout.connect(lambda: self._daily_backup(notify=True))
        self._backup_timer.start()
        self._daily_backup()

        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(5 * 60 * 1000)
        self._activity_timer.timeout.connect(self._flush_activity)
        self._activity_timer.start()

    # ------------------------------------------------------------------ chrome
    def _build_menus(self) -> None:
        bar = self.menuBar()
        bar.setNativeMenuBar(False)
        bar.setFont(font(14, 400))

        self.act_new = self._action("New Transaction…", self.new_transaction, "Ctrl+N")
        self.act_new_scheduled = self._action(
            "New Scheduled Transaction…", self.new_scheduled_transaction
        )
        self.act_new_account = self._action("New Account…", self.new_account, "Ctrl+Shift+N")
        self.act_import = self._action("Import CSV…", self.import_csv, "Ctrl+I")
        self.act_import_airbnb = self._action("From Airbnb…", self.import_airbnb)
        self.act_import_booking = self._action("From Booking…", self.import_booking)
        self.act_import_banamex = self._action("From Banamex…", self.import_banamex)
        self.act_export = self._action("Export CSV…", self.export_csv, "Ctrl+E")
        self.act_open_database = self._action(
            "Open Database…", self.open_database, "Ctrl+O"
        )
        self.act_save_database = self._action(
            "Save Database As…", self.save_database_as, "Ctrl+Alt+S"
        )
        self.act_view_activity = self._action(
            "View Activity History", self.view_activity_history
        )
        self.act_save_activity = self._action(
            "Save Activity History As…",
            self.save_activity_history_as,
            "Ctrl+Shift+S",
        )
        self.act_quit = self._action("Quit", self.close, "Ctrl+Q")

        file_menu = bar.addMenu("File")
        file_menu.addAction(self.act_open_database)
        file_menu.addAction(self.act_save_database)
        file_menu.addSeparator()
        file_menu.addAction(self.act_view_activity)
        file_menu.addAction(self.act_save_activity)
        file_menu.addSeparator()
        file_menu.addAction(self.act_new)
        file_menu.addAction(self.act_new_account)
        file_menu.addSeparator()
        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_import_airbnb)
        file_menu.addAction(self.act_import_booking)
        file_menu.addAction(self.act_import_banamex)
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        self.act_preferences = self._action("Preferences…", self.open_preferences, "Ctrl+,")
        edit_menu = bar.addMenu("Edit")
        edit_menu.addAction(self.act_preferences)

        self.act_toggle_accounts = QAction("Accounts Panel", self)
        self.act_toggle_accounts.setCheckable(True)
        self.act_toggle_accounts.setChecked(True)
        self.act_toggle_scheduled = QAction("Scheduled Transactions", self)
        self.act_toggle_scheduled.setCheckable(True)
        self.act_toggle_scheduled.setChecked(True)
        self.act_toggle_budgets = QAction("Budgets Panel", self)
        self.act_toggle_budgets.setCheckable(True)
        self.act_toggle_budgets.setChecked(True)
        self.act_refresh = self._action("Refresh Dashboard", self.refresh_all, "F5")
        view_menu = bar.addMenu("View")
        view_menu.addAction(self.act_toggle_accounts)
        view_menu.addAction(self.act_toggle_scheduled)
        view_menu.addAction(self.act_toggle_budgets)
        view_menu.addSeparator()
        view_menu.addAction(self.act_refresh)

        self.act_edit_account = self._action("Edit Account…", self.edit_selected_account)
        self.act_delete_account = self._action("Delete Account…", self.delete_selected_account)
        self.act_categories = self._action("Categories…", self.show_categories)
        self.act_payees = self._action("Payees…", self.show_payees)
        self.act_rules = self._action("Rules…", self.show_rules)
        manage_menu = bar.addMenu("Manage")
        manage_menu.addAction(self.act_new_account)
        manage_menu.addAction(self.act_edit_account)
        manage_menu.addAction(self.act_delete_account)
        manage_menu.addSeparator()
        manage_menu.addAction(self.act_categories)
        manage_menu.addAction(self.act_payees)
        manage_menu.addAction(self.act_rules)

        self.act_open_ledger = self._action(
            "Open Account Ledger", self.open_selected_ledger, "Ctrl+L"
        )
        self.act_post = self._action("Post Selected Schedule", self.post_selected_schedule)
        transactions_menu = bar.addMenu("Transactions")
        transactions_menu.addAction(self.act_new)
        transactions_menu.addAction(self.act_new_scheduled)
        transactions_menu.addSeparator()
        transactions_menu.addAction(self.act_open_ledger)
        transactions_menu.addAction(self.act_post)

        self.act_focus_spending = self._action("Spending by Category", self.focus_spending)
        self.act_focus_cashflow = self._action("Spending & Revenue", self.focus_cashflow)
        self.act_reports = self._action("Reports Window…", self.open_reports, "Ctrl+R")
        self.act_budgets = self._action("Budgets…", self.open_budgets, "Ctrl+B")
        reports_menu = bar.addMenu("Reports")
        reports_menu.addAction(self.act_reports)
        reports_menu.addAction(self.act_budgets)
        reports_menu.addSeparator()
        reports_menu.addAction(self.act_focus_spending)
        reports_menu.addAction(self.act_focus_cashflow)
        reports_menu.addSeparator()
        reports_menu.addAction(self.act_refresh)

        tools_menu = bar.addMenu("Tools")
        tools_menu.addAction(self.act_preferences)
        tools_menu.addAction(self._action("Open Data Folder", self.open_data_folder))
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_import)
        tools_menu.addAction(self.act_import_airbnb)
        tools_menu.addAction(self.act_import_booking)
        tools_menu.addAction(self.act_import_banamex)
        tools_menu.addAction(self.act_export)

        help_menu = bar.addMenu("Help")
        self.act_shortcuts = self._action(
            "Keyboard Shortcuts", self.show_shortcuts, "Ctrl+K"
        )
        self.act_shortcuts.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        help_menu.addAction(self.act_shortcuts)
        help_menu.addAction(self._action(f"About {APP_NAME}", self.show_about))

    def _action(self, text: str, slot, shortcut: str | None = None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: slot())
        self.addAction(action)
        return action

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"#central {{ background: {C.BG}; }}")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = AppToolbar()
        root.addWidget(self.toolbar)

        self.donut = DonutChart()
        self.donut_card = ChartCard(
            "Top 10 Spending / Category",
            money(0),
            "Total chart",
            ["Last 30 Days", "This Month", "Last Month", "Last 3 Months", "This Year"],
            "Last 30 Days",
            self.donut,
            modes=["Expenses", "Income"],
            current_mode="Expenses",
        )
        self.bars = SpendingRevenueChart()
        self.bar_card = ChartCard(
            "Spending & Revenue",
            "",
            "Time chart",
            ["Last 12 Months", "Last 6 Months", "This Year"],
            "Last 12 Months",
            self.bars,
        )

        self.accounts_panel = AccountsPanel()
        self.accounts_panel.setMinimumHeight(412)
        self.scheduled_panel = ScheduledPanel()
        self.budgets_panel = BudgetsPanel(self.store)

        self.charts_split = QSplitter(Qt.Orientation.Horizontal)
        self.charts_split.setHandleWidth(5)
        self.charts_split.setChildrenCollapsible(False)
        self.charts_split.setStyleSheet(f"QSplitter {{ background: {C.BG}; }} QSplitter::handle {{ background: {C.BG}; }}")
        self.charts_split.addWidget(self.donut_card)
        self.charts_split.addWidget(self.bar_card)
        self.charts_split.setStretchFactor(0, 1)
        self.charts_split.setStretchFactor(1, 1)

        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.setHandleWidth(5)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.setStyleSheet(f"QSplitter {{ background: {C.BG}; }} QSplitter::handle {{ background: {C.BG}; }}")
        self.hsplit.addWidget(self.accounts_panel)
        self.hsplit.addWidget(self.charts_split)
        self.hsplit.setStretchFactor(0, 0)
        self.hsplit.setStretchFactor(1, 1)

        self.bottom_split = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_split.setHandleWidth(5)
        self.bottom_split.setChildrenCollapsible(False)
        self.bottom_split.setStyleSheet(f"QSplitter {{ background: {C.BG}; }} QSplitter::handle {{ background: {C.BG}; }}")
        self.bottom_split.addWidget(self.scheduled_panel)
        self.bottom_split.addWidget(self.budgets_panel)
        self.bottom_split.setStretchFactor(0, 3)
        self.bottom_split.setStretchFactor(1, 2)

        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setHandleWidth(5)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.setStyleSheet(f"QSplitter {{ background: {C.BG}; }} QSplitter::handle {{ background: {C.BG}; }}")
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self.bottom_split)
        self.vsplit.setStretchFactor(0, 54)
        self.vsplit.setStretchFactor(1, 46)

        root.addWidget(self.vsplit, 1)
        self.setCentralWidget(central)

        self.hsplit.setSizes([615, 1225])
        self.charts_split.setSizes([610, 610])
        self.vsplit.setSizes([412, 349])
        self.bottom_split.setSizes([1080, 720])

        self.toast = QLabel(self)
        self.toast.setObjectName("toast")
        self.toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast.setFont(font(13, 400))
        self.toast.setStyleSheet(
            f"QLabel#toast {{ background:{C.TOOLTIP_BG}; color:{C.TOOLTIP_TEXT};"
            f" border:1px solid {C.TOOLTIP_BORDER};"
            "border-radius:6px; padding:8px 16px; }"
        )
        self.toast.hide()

    def _wire(self) -> None:
        self.toolbar.newTransaction.connect(self.new_transaction)
        self.toolbar.newAccount.connect(self.new_account)
        self.toolbar.importRequested.connect(self.import_csv)
        self.toolbar.airbnbImportRequested.connect(self.import_airbnb)
        self.toolbar.bookingImportRequested.connect(self.import_booking)
        self.toolbar.banamexImportRequested.connect(self.import_banamex)
        self.toolbar.exportRequested.connect(self.export_csv)
        self.toolbar.manageAccounts.connect(self.focus_accounts)
        self.toolbar.payeesRequested.connect(self.show_payees)
        self.toolbar.categoriesRequested.connect(self.show_categories)
        self.toolbar.preferencesRequested.connect(self.open_preferences)
        self.toolbar.aboutRequested.connect(self.show_about)
        self.toolbar.helpRequested.connect(self.show_shortcuts)
        self.toolbar.refreshRequested.connect(self.refresh_all)
        self.toolbar.spendingFocus.connect(self.focus_spending)
        self.toolbar.cashflowFocus.connect(self.focus_cashflow)
        self.toolbar.reportsRequested.connect(self.open_reports)
        self.toolbar.budgetsRequested.connect(self.open_budgets)

        self.accounts_panel.accountSelected.connect(lambda _id: self._update_actions())
        self.accounts_panel.openRequested.connect(self.open_ledger)
        self.accounts_panel.addRequested.connect(self.new_account)
        self.accounts_panel.importRequested.connect(self.import_csv)
        self.accounts_panel.settingsRequested.connect(self.open_preferences)
        self.accounts_panel.editRequested.connect(self.edit_account)
        self.accounts_panel.deleteRequested.connect(self.delete_account)
        self.accounts_panel.reorderRequested.connect(self._reorder_account)
        self.accounts_panel.addTransactionRequested.connect(self._new_transaction_for_account)

        self.scheduled_panel.postRequested.connect(self.post_scheduled)
        self.scheduled_panel.skipRequested.connect(self.skip_scheduled)
        self.scheduled_panel.editPostRequested.connect(self.edit_and_post)
        self.scheduled_panel.openLedgerRequested.connect(self.open_ledger)
        self.scheduled_panel.settingsRequested.connect(self.open_preferences)
        self.scheduled_panel.selectionChanged.connect(lambda _id: self._update_actions())
        self.budgets_panel.changed.connect(self.refresh_all)
        self.budgets_panel.changed.connect(
            lambda: self._record_activity("Updated budgets")
        )

        self.donut_card.footer.periodChanged.connect(self._refresh_donut)
        self.donut_card.footer.modeChanged.connect(self._refresh_donut)
        self.donut_card.footer.refreshRequested.connect(self.refresh_all)
        self.bar_card.footer.periodChanged.connect(self._refresh_bars)
        self.bar_card.footer.refreshRequested.connect(self.refresh_all)

        self.act_toggle_accounts.toggled.connect(self.accounts_panel.setVisible)
        self.act_toggle_scheduled.toggled.connect(self.scheduled_panel.setVisible)
        self.act_toggle_budgets.toggled.connect(self.budgets_panel.setVisible)

    # ------------------------------------------------------------------- data
    def refresh_all(self) -> None:
        accounts = self.store.accounts()
        balances = self.store.balances()
        self.accounts_panel.set_data(accounts, balances)
        self._refresh_donut()
        self._refresh_bars()
        future_rows, remind_rows = self.store.strip_transactions()
        future_items = [self._strip_item(row, "future") for row in future_rows]
        remind_items = [self._strip_item(row, "remind") for row in remind_rows]
        self.scheduled_panel.set_data(
            self.store.scheduled_items(), accounts, future_items, remind_items
        )
        self.budgets_panel.reload()
        for ledger in list(self.ledgers.values()):
            try:
                ledger.reload()
            except RuntimeError:
                continue
        if self.reports_window is not None:
            try:
                self.reports_window.reload()
            except RuntimeError:
                self.reports_window = None
        if self.budget_window is not None:
            try:
                self.budget_window.reload()
            except RuntimeError:
                self.budget_window = None
        self._update_actions()

    @staticmethod
    def _strip_item(row, status: str) -> ScheduledItem:
        return ScheduledItem(
            id=row.id,
            account_id=row.account_id,
            account_name=row.account_name,
            next_date=row.date,
            payee=row.payee,
            category_id=row.category_id,
            category_name=row.category_name,
            category_color=row.category_color,
            amount=row.amount,
            memo=row.memo,
            status=status,
            kind=row.category_kind,
            source="ledger",
        )

    def open_selected_ledger(self) -> None:
        if self.accounts_panel.selected_id is not None:
            self.open_ledger(self.accounts_panel.selected_id)

    def open_reports(self) -> None:
        if self.reports_window is not None and self.reports_window.isVisible():
            self.reports_window.show()
            self.reports_window.raise_()
            self.reports_window.activateWindow()
            return
        self._record_activity("Opened reports window")
        window = ReportsWindow(self.store, self)
        self.reports_window = window
        window.destroyed.connect(lambda _obj=None: setattr(self, "reports_window", None))
        window.show()
        window.raise_()
        window.activateWindow()

    def open_budgets(self) -> None:
        if self.budget_window is not None and self.budget_window.isVisible():
            self.budget_window.show()
            self.budget_window.raise_()
            self.budget_window.activateWindow()
            return
        self._record_activity("Opened budgets window")
        window = BudgetWindow(self.store, self)
        self.budget_window = window
        window.destroyed.connect(lambda _obj=None: setattr(self, "budget_window", None))
        window.changed.connect(self.refresh_all)
        window.changed.connect(lambda: self._record_activity("Updated budgets"))
        window.show()
        window.raise_()
        window.activateWindow()

    def open_ledger(self, account_id: int) -> None:
        existing = self.ledgers.get(account_id)
        if existing is not None and existing.isVisible():
            existing.show()
            existing.raise_()
            existing.activateWindow()
            existing.focus_table()
            return
        if self.store.account(account_id) is None:
            return
        account = self.store.account(account_id)
        self._record_activity(
            "Opened account ledger", account.name if account is not None else ""
        )
        ledger = LedgerWindow(self.store, account_id, self)
        self.ledgers[account_id] = ledger
        ledger.changed.connect(self.refresh_all)
        ledger.activity.connect(self._record_activity)
        ledger.destroyed.connect(
            lambda _obj=None, aid=account_id: self._ledger_closed(aid)
        )
        ledger.show()
        ledger.raise_()
        ledger.activateWindow()

    def _donut_range(self, period: str) -> tuple[date, date]:
        today = date.today()
        if period == "This Month":
            return today.replace(day=1), today
        if period == "Last Month":
            first = today.replace(day=1)
            end = first - timedelta(days=1)
            return end.replace(day=1), end
        if period == "Last 3 Months":
            year, month = today.year, today.month - 2
            while month <= 0:
                month += 12
                year -= 1
            return date(year, month, 1), today
        if period == "This Year":
            return date(today.year, 1, 1), today
        return today - timedelta(days=29), today

    def _refresh_donut(self, _period: str | None = None) -> None:
        period = self.donut_card.period()
        income = self.donut_card.mode() == "Income"
        kind = "income" if income else "expense"
        start, end = self._donut_range(period)
        slices, total = self.store.category_slices(start, end, kind)
        self.donut.set_data(slices, total)
        self.donut.empty_text = (
            "No income in this period" if income else "No spending in this period"
        )
        self.donut_card.set_title(
            "Top 10 Income / Category" if income else "Top 10 Spending / Category"
        )
        self.donut_card.set_subtitle(money(total) if income else money(-total))

    def _refresh_bars(self, _period: str | None = None) -> None:
        period = self.bar_card.period()
        months = {"Last 12 Months": 12, "Last 6 Months": 6, "This Year": date.today().month}.get(
            period, 12
        )
        self.bars.set_data(self.store.monthly_cashflow(months))

    # ---------------------------------------------------------------- actions
    def new_transaction(self) -> None:
        self._open_transaction()

    def new_scheduled_transaction(self) -> None:
        self._open_transaction(scheduled=True)

    def _new_transaction_for_account(self, account_id: int) -> None:
        self._open_transaction(account_id=account_id)

    def _open_transaction(
        self,
        account_id: int | None = None,
        scheduled: bool = False,
    ) -> None:
        accounts = self.store.accounts()
        if not accounts:
            QMessageBox.information(
                self, "No accounts yet", "Create an account before adding a transaction."
            )
            return
        dialog = TransactionDialog(
            self.store,
            accounts,
            self.store.categories(),
            scheduled=scheduled,
            parent=self,
        )
        if account_id is not None:
            index = dialog.account_combo.findData(account_id)
            if index >= 0:
                dialog.account_combo.setCurrentIndex(index)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.draft()
        if draft is None:
            return
        if scheduled:
            self.store.add_scheduled(draft)
            self._record_activity(
                "Scheduled transaction",
                f"{transaction_detail(draft.payee, draft.amount, draft.memo)} · {draft.date}",
            )
            self.show_toast(f"Scheduled {draft.payee} for {draft.date}")
            self.refresh_all()
            self.scheduled_panel.show_tab("Scheduled")
        else:
            if draft.transfer_account_id is not None:
                self.store.add_transfer(draft, draft.transfer_account_id)
                destination = self.store.account(draft.transfer_account_id)
                detail = transaction_detail(draft.payee, draft.amount, draft.memo)
                if destination is not None:
                    detail += f" → {destination.name}"
                self._record_activity("New transfer", detail)
                self.show_toast("Added transfer")
            else:
                self.store.add_transaction(draft)
                self._record_activity(
                    "New transaction",
                    transaction_detail(draft.payee, draft.amount, draft.memo),
                )
                self.show_toast(f"Added {draft.payee} · {money(draft.amount)}")
            self.refresh_all()
            when = date.fromisoformat(draft.date)
            if draft.remind:
                self.scheduled_panel.show_tab("Remind")
            elif when > date.today():
                self.scheduled_panel.show_tab("Future")
            else:
                self.scheduled_panel.show_tab("Scheduled")

    def new_account(self) -> None:
        dialog = AccountDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, kind, opening = dialog.values()
        self.store.add_account(name, kind, opening)
        self._record_activity(
            "New account", f"{name} · {kind} · opening {money(opening)}"
        )
        self.refresh_all()
        self.show_toast(f"Added account {name}")

    def edit_selected_account(self) -> None:
        if self.accounts_panel.selected_id is not None:
            self.edit_account(self.accounts_panel.selected_id)

    def edit_account(self, account_id: int) -> None:
        account = self.store.account(account_id)
        if account is None:
            return
        dialog = AccountDialog(account, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, kind, opening = dialog.values()
        self.store.update_account(account_id, name, kind, opening)
        self._record_activity("Edited account", name)
        self.refresh_all()
        self.show_toast(f"Saved {name}")

    def delete_selected_account(self) -> None:
        if self.accounts_panel.selected_id is not None:
            self.delete_account(self.accounts_panel.selected_id)

    def delete_account(self, account_id: int) -> None:
        account = self.store.account(account_id)
        if account is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete account?",
            f"Delete “{account.name}” and all of its transactions and schedules?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_account(account_id)
        self._record_activity("Deleted account", account.name)
        self.refresh_all()
        self.show_toast(f"Deleted {account.name}")

    def _reorder_account(self, account_id: int, direction: int) -> None:
        account = self.store.account(account_id)
        self.store.move_account(account_id, direction)
        if account is not None:
            self._record_activity(
                "Moved account",
                f"{account.name} {'up' if direction < 0 else 'down'}",
            )
        self.refresh_all()

    def post_selected_schedule(self) -> None:
        if (
            self.scheduled_panel.selected_id is not None
            and self.scheduled_panel.selected_source == "scheduled"
        ):
            self.post_scheduled(self.scheduled_panel.selected_id)

    def post_scheduled(self, item_id: int) -> None:
        item = self.store.scheduled_item(item_id)
        if item is None:
            return
        self.store.post_scheduled(item_id)
        self._record_activity(
            "Posted scheduled transaction",
            transaction_detail(item.payee, item.amount, item.memo),
        )
        self.refresh_all()
        self.show_toast(f"Posted {item.payee} · {money(item.amount)}")

    def skip_scheduled(self, item_id: int) -> None:
        item = self.store.scheduled_item(item_id)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Skip this transaction?",
            f"Remove “{item.payee}” from the schedule without posting it?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.skip_scheduled(item_id)
        self._record_activity(
            "Skipped scheduled transaction",
            transaction_detail(item.payee, item.amount, item.memo),
        )
        self.refresh_all()
        self.show_toast(f"Skipped {item.payee}")

    def edit_and_post(self, item_id: int) -> None:
        item = self.store.scheduled_item(item_id)
        if item is None:
            return
        accounts = self.store.accounts()
        draft = TransactionDialogDraft.from_item(item)
        dialog = TransactionDialog(
            self.store,
            accounts,
            self.store.categories(),
            draft=draft,
            scheduled=False,
            title="Edit & Post",
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_draft = dialog.draft()
        if new_draft is None:
            return
        self.store.add_transaction(new_draft)
        self.store.skip_scheduled(item_id)
        self._record_activity(
            "Edited and posted scheduled transaction",
            transaction_detail(
                new_draft.payee, new_draft.amount, new_draft.memo
            ),
        )
        self.refresh_all()
        self.show_toast(f"Posted {new_draft.payee} · {money(new_draft.amount)}")

    def focus_accounts(self) -> None:
        if not self.accounts_panel.isVisible():
            self.act_toggle_accounts.setChecked(True)
            self.accounts_panel.setVisible(True)
        self.accounts_panel.focus_list()
        self.accounts_panel.flash()

    def _ledger_closed(self, account_id: int) -> None:
        if self._closing or account_id not in self.ledgers:
            return
        self.ledgers.pop(account_id, None)
        if not self.isVisible() or not self.accounts_panel.isVisible():
            return
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self.accounts_panel.focus_list)

    def focus_spending(self) -> None:
        self.donut_card.flash()
        self.donut_card.footer.combo.setFocus()

    def focus_cashflow(self) -> None:
        self.bar_card.flash()
        self.bar_card.footer.combo.setFocus()

    # ------------------------------------------------------------------ tools
    def open_preferences(self) -> None:
        dialog = PreferencesDialog(self.store, self)
        dialog.exec()
        if dialog.was_reset:
            self._record_activity("Restored demo data")
            self.refresh_all()
            self.show_toast("Demo data restored")
        if dialog.changed_date_format:
            self._record_activity("Changed date format", date_format_choice())
            set_date_format(date_format_choice())
            self.refresh_all()
            if self.reports_window is not None:
                self.reports_window.reload()
        if dialog.changed_theme:
            self._record_activity("Changed theme", theme_choice())
            self._rebuild_for_theme()

    def _rebuild_for_theme(self) -> None:
        """Apply the saved theme by rebuilding the window with fresh styles."""
        from PySide6.QtWidgets import QApplication

        select_theme(theme_choice())
        geometry = self.geometry()
        maximized = self.isMaximized()
        self._keep_store = True
        replacement = MainWindow(self.store)
        replacement.setGeometry(geometry)
        app = QApplication.instance()
        if app is not None:
            app._contapy_main_window = replacement  # type: ignore[attr-defined]
        replacement.show()
        if maximized:
            replacement.showMaximized()
        replacement.raise_()
        replacement.activateWindow()
        self.close()

    def show_categories(self) -> None:
        dialog = CategoriesDialog(self.store, self)
        dialog.exec()
        if dialog.changed:
            self._record_activity("Updated categories")
            self.refresh_all()

    def show_rules(self) -> None:
        dialog = RulesDialog(self.store, self)
        dialog.exec()
        if dialog.changed:
            self._record_activity("Updated assignment rules")
            self.refresh_all()

    def show_payees(self) -> None:
        payees = self.store.payees()
        rows = [(payee, "") for payee in payees]
        ListDialog(
            "Payees",
            f"{len(payees)} payees across posted and scheduled transactions.",
            rows,
            self,
        ).exec()

    def open_data_folder(self) -> None:
        self._record_activity("Opened data folder")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.path.parent)))

    # --------------------------------------------------------------- activity
    def _record_activity(self, action: str, detail: str = "") -> None:
        self.activity.record(action, detail)

    def _flush_activity(self, notify: bool = False) -> None:
        try:
            self.activity.flush()
        except OSError as exc:
            print(
                f"{APP_NAME}: activity history could not be written: {exc}",
                file=sys.stderr,
            )
            if notify:
                QMessageBox.warning(
                    self,
                    "Could not save activity history",
                    f"{APP_NAME} could not write:\n{self.activity.path}\n\n{exc}",
                )

    def view_activity_history(self) -> None:
        self._record_activity("Viewed activity history")
        self._flush_activity(notify=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.activity.path)))

    def save_activity_history_as(self) -> None:
        self._flush_activity(notify=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save activity history",
            str(self.activity.path),
            "Markdown files (*.md);;All files (*)",
        )
        if not path:
            return
        try:
            target = self.activity.save_as(path)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Could not save activity history",
                f"{APP_NAME} could not save:\n{path}\n\n{exc}",
            )
            return
        self._record_activity("Saved activity history", target.name)
        self._flush_activity(notify=True)
        self.show_toast(f"Saved activity history to {target.name}")

    # --------------------------------------------------------------- databases
    def open_database(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open database",
            str(self.store.path.parent),
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if path:
            self.load_database(path)

    def save_database_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save database as",
            str(self.store.path),
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not path:
            return
        target = Path(path).expanduser()
        if not target.suffix:
            target = target.with_name(target.name + ".db")
        if target.resolve() == self.store.path.resolve():
            self.show_toast("That database is already open")
            return
        try:
            self.store.backup_to(target)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            QMessageBox.warning(
                self,
                "Could not save database",
                f"{APP_NAME} could not save:\n{target}\n\n{exc}",
            )
            return
        # Continue on the copy so future edits land in the new location. The
        # original file is left untouched as a safety copy.
        if self.load_database(target):
            self._record_activity("Saved database as", target.name)

    def load_database(self, path: str | Path) -> bool:
        """Switch to the database at ``path`` and remember it for next launch."""
        target = Path(path).expanduser()
        if target.resolve() == self.store.path.resolve():
            self.show_toast("That database is already open")
            return False
        try:
            store = DataStore(target)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            QMessageBox.warning(
                self,
                "Could not open database",
                f"{APP_NAME} could not open:\n{target}\n\n{exc}",
            )
            return False

        # Close ledgers and reports tied to the old store before swapping.
        self._closing = True
        try:
            if self.reports_window is not None:
                try:
                    self.reports_window.close()
                except RuntimeError:
                    pass
                self.reports_window = None
            if self.budget_window is not None:
                try:
                    self.budget_window.close()
                except RuntimeError:
                    pass
                self.budget_window = None
            for ledger in list(self.ledgers.values()):
                try:
                    ledger.close()
                except RuntimeError:
                    pass
            self.ledgers.clear()
        finally:
            self._closing = False
        old_store = self.store
        self._record_activity("Closed database", old_store.path.name)
        self._flush_activity()
        self.store = store
        old_store.close()
        self.activity = ActivityLog(activity_log_path(store.path))
        self.activity.record("Opened database", target.name)
        self._flush_activity()

        try:
            remember_database(target)
        except OSError:
            # The switch still works even if the config folder is read-only.
            pass
        self._update_window_title()
        self.refresh_all()
        self.show_toast(f"Opened {target.name}")
        self._daily_backup()
        return True

    def _update_window_title(self) -> None:
        self.setWindowTitle(f"{APP_NAME} — {self.store.path.name}")

    def _daily_backup(self, notify: bool = False) -> None:
        try:
            created = self.store.ensure_daily_backup()
        except Exception as exc:  # pragma: no cover - filesystem problems
            print(f"{APP_NAME}: daily backup failed: {exc}", file=sys.stderr)
            if notify:
                self.show_toast("Daily backup failed")
            return
        if created is not None and notify:
            self.show_toast(f"Daily backup: {created.name}")

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import transactions", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        self._import_csv_path(Path(path))

    def import_airbnb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Airbnb",
            "",
            "Airbnb exports (*.csv);;All files (*)",
        )
        if not path:
            return
        source = Path(path)
        with tempfile.TemporaryDirectory(prefix="contapy-airbnb-") as folder:
            target = Path(folder) / f"{source.stem}_airbnb.csv"
            try:
                written, excluded = transform_airbnb(source, target)
            except Exception as exc:  # pragma: no cover - surfaced to the user
                QMessageBox.warning(self, "Airbnb import failed", str(exc))
                return
            note = f"{excluded} payout(s) excluded" if excluded else ""
            self._import_csv_path(target, note=note)

    def import_booking(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Booking — payouts",
            "",
            "Booking exports (*.csv);;All files (*)",
        )
        if not path:
            return
        booking_source = Path(path)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Booking — Sabee reservations",
            "",
            "Sabee exports (*.csv);;All files (*)",
        )
        if not path:
            return
        sabee_source = Path(path)
        with tempfile.TemporaryDirectory(prefix="contapy-booking-") as folder:
            target = Path(folder) / f"{booking_source.stem}_booking.csv"
            try:
                written, rooms_missing = transform_booking(
                    booking_source, sabee_source, target
                )
            except Exception as exc:  # pragma: no cover - surfaced to the user
                QMessageBox.warning(self, "Booking import failed", str(exc))
                return
            parts = [f"{written} amount row(s)"]
            if rooms_missing:
                parts.append(f"{rooms_missing} reservation(s) without a room")
            self._import_csv_path(target, note=" · ".join(parts))

    def import_banamex(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Banamex",
            "",
            "Banamex statements (*.html *.htm);;All files (*)",
        )
        if not path:
            return
        source = Path(path)
        with tempfile.TemporaryDirectory(prefix="contapy-banamex-") as folder:
            target = Path(folder) / f"{source.stem}_banamex.csv"
            try:
                _written, skipped, year = transform_banamex(source, target)
            except Exception as exc:  # pragma: no cover - surfaced to the user
                QMessageBox.warning(self, "Banamex import failed", str(exc))
                return
            parts = [f"{year} statement"]
            if skipped:
                parts.append(f"{skipped} unreadable row(s) ignored")
            self._import_csv_path(target, note=" · ".join(parts))

    def _import_csv_path(self, path: Path, note: str = "") -> None:
        try:
            dialog = CsvImportDialog(
                self.store,
                self.store.accounts(),
                path,
                self.accounts_panel.selected_id,
                self,
            )
        except Exception as exc:  # pragma: no cover - surfaced to the user
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            added, skipped, duplicates = self.store.import_csv(
                path,
                account_id=dialog.account_id(),
                memo_as_payee=dialog.memo_as_payee(),
                mapping=dialog.current_mapping(),
                skip_rows=dialog.skip_row_indexes(),
                apply_rules=dialog.apply_rules(),
            )
        except Exception as exc:  # pragma: no cover - surfaced to the user
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.refresh_all()
        detail = f"{added} imported"
        if duplicates:
            detail += f", {duplicates} duplicate(s) skipped"
        if skipped:
            detail += f", {skipped} unreadable"
        if note:
            detail += f", {note}"
        self._record_activity(
            "Imported transactions", f"{detail} · {Path(path).name}"
        )
        self.show_toast(f"Import: {detail}")
        if skipped or duplicates:
            QMessageBox.information(
                self,
                "Import finished",
                f"Imported {added} transactions."
                + (f"\nSkipped {duplicates} duplicate(s)." if duplicates else "")
                + (
                    f"\nSkipped {skipped} row(s) that could not be parsed."
                    if skipped
                    else ""
                ),
            )

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export transactions", "contapy-export.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        count = self.store.export_csv(path)
        self._record_activity(
            "Exported transactions", f"{count} · {Path(path).name}"
        )
        self.show_toast(f"Exported {count} transactions")

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(about_text())
        box.exec()

    # ------------------------------------------------------------------ state
    def _update_actions(self) -> None:
        has_account = self.accounts_panel.selected_id is not None
        has_schedule = (
            self.scheduled_panel.selected_id is not None
            and self.scheduled_panel.selected_source == "scheduled"
        )
        for action in (self.act_edit_account, self.act_delete_account):
            action.setEnabled(has_account)
        self.act_open_ledger.setEnabled(has_account)
        self.act_post.setEnabled(has_schedule)

    def show_toast(self, text: str) -> None:
        self.toast.setText(text)
        self.toast.adjustSize()
        self._position_toast()
        self.toast.show()
        self.toast.raise_()
        self._toast_timer.start(2600)

    def _hide_toast(self) -> None:
        self.toast.hide()

    def _position_toast(self) -> None:
        if not hasattr(self, "toast"):
            return
        x = max(12, (self.width() - self.toast.width()) // 2)
        y = max(12, self.height() - self.toast.height() - 66)
        self.toast.move(x, y)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._initial_focus_done:
            self._initial_focus_done = True
            QTimer.singleShot(0, self.accounts_panel.focus_list)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._position_toast()

    def closeEvent(self, event):  # noqa: N802
        self._closing = True
        self._record_activity("Application closed")
        self._flush_activity()
        self._daily_backup()
        if self.reports_window is not None:
            try:
                self.reports_window.close()
            except RuntimeError:
                pass
            self.reports_window = None
        if self.budget_window is not None:
            try:
                self.budget_window.close()
            except RuntimeError:
                pass
            self.budget_window = None
        for ledger in list(self.ledgers.values()):
            try:
                ledger.close()
            except RuntimeError:
                pass
        self.ledgers.clear()
        if not self._keep_store:
            self.store.close()
        super().closeEvent(event)


class TransactionDialogDraft:
    """Adapter that turns a scheduled row into a dialog draft."""

    @staticmethod
    def from_item(item: ScheduledItem):
        from .models import TransactionDraft

        return TransactionDraft(
            date=item.next_date,
            account_id=item.account_id,
            payee=item.payee,
            category_id=item.category_id,
            amount=item.amount,
            memo=item.memo,
            cleared=True,
            scheduled=False,
        )

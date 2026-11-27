"""Tests for the LAN sync endpoint used by the Android companion app."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from contapy.config import (
    DEFAULT_SYNC_PORT,
    remember_sync_port,
    remember_sync_token,
    sync_port,
    sync_token,
)
from contapy.db import DataStore
from contapy.lansync import SyncServer
from contapy.models import TransactionDraft

TOKEN = "test-token-0123456789"


def txn(**overrides) -> dict:
    item = {
        "uuid": "phone-0001",
        "date": "2026-11-20",
        "account": "Wallet",
        "payee": "Coffee shop",
        "category": "Food : Coffee",
        "amount": -85.5,
        "memo": "Morning coffee",
        "tags": "coffee",
        "status": "cleared",
    }
    item.update(overrides)
    return item


class SyncStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "contapy.db"
        self.store = DataStore(self.path, seed=False)
        self.store.add_account("Wallet", "Cash", 0.0)
        self.store.add_account("Bank", "Bank", 0.0)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def count(self) -> int:
        return int(
            self.store.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        )

    def test_insert_then_retry_is_idempotent(self) -> None:
        first = self.store.ingest_sync_transactions([txn()])
        self.assertEqual(first[0]["status"], "inserted")
        self.assertEqual(self.count(), 1)

        again = self.store.ingest_sync_transactions([txn()])
        self.assertEqual(again[0]["status"], "duplicate")
        self.assertEqual(again[0]["id"], first[0]["id"])
        self.assertEqual(self.count(), 1)

    def test_inserted_row_keeps_phone_uuid_and_fields(self) -> None:
        result = self.store.ingest_sync_transactions([txn()])[0]
        row = self.store.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (result["id"],)
        ).fetchone()
        self.assertEqual(row["uuid"], "phone-0001")
        self.assertAlmostEqual(row["amount"], -85.5)
        self.assertEqual(row["payee"], "Coffee shop")
        self.assertEqual(row["tags"], "coffee")
        self.assertEqual(row["cleared"], 1)
        self.assertEqual(
            self.store.transaction_uuid(result["id"]), "phone-0001"
        )

    def test_account_lookup_ignores_case(self) -> None:
        result = self.store.ingest_sync_transactions([txn(account="wallet")])[0]
        self.assertEqual(result["status"], "inserted")

    def test_bad_rows_report_errors_without_blocking_others(self) -> None:
        results = self.store.ingest_sync_transactions(
            [
                txn(uuid="ok-1"),
                txn(uuid="bad-date", date="20/11/2026"),
                txn(uuid="bad-account", account="Nope"),
                txn(uuid="bad-amount", amount=0),
                txn(uuid="bad-status", status="closed"),
                {"date": "2026-11-20", "account": "Wallet", "amount": -1},
                "not-a-dict",
                txn(uuid="ok-2"),
            ]
        )
        statuses = [r["status"] for r in results]
        self.assertEqual(
            statuses,
            [
                "inserted",
                "error",
                "error",
                "error",
                "error",
                "error",
                "error",
                "inserted",
            ],
        )
        self.assertEqual(self.count(), 2)
        self.assertIn("date", results[1]["error"])
        self.assertIn("unknown account", results[2]["error"])

    def test_unknown_category_is_created(self) -> None:
        result = self.store.ingest_sync_transactions(
            [txn(category="Food : Bakery")]
        )[0]
        self.assertEqual(result["status"], "inserted")
        names = {c.name for c in self.store.categories()}
        self.assertIn("Bakery", names)

    def test_status_maps_to_flags(self) -> None:
        result = self.store.ingest_sync_transactions(
            [txn(uuid="remind-1", status="remind")]
        )[0]
        row = self.store.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (result["id"],)
        ).fetchone()
        self.assertEqual(row["remind"], 1)
        self.assertEqual(row["reconciled"], 0)

    def test_sync_meta_lists_reference_data(self) -> None:
        meta = self.store.sync_meta()
        self.assertEqual({a["name"] for a in meta["accounts"]}, {"Wallet", "Bank"})
        self.assertIn("cleared", meta["statuses"])
        self.assertTrue(all("name" in c for c in meta["categories"]))

    def test_legacy_rows_get_a_uuid_on_open(self) -> None:
        self.store.add_transaction(
            TransactionDraft(
                date="2026-11-19",
                account_id=1,
                payee="Old row",
                category_id=None,
                amount=-10,
            )
        )
        self.store.conn.execute("DROP INDEX idx_tx_uuid")
        self.store.conn.execute("ALTER TABLE transactions DROP COLUMN uuid")
        self.store.conn.commit()
        self.store.close()

        self.store = DataStore(self.path, seed=False)
        missing = self.store.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE uuid IS NULL OR uuid = ''"
        ).fetchone()[0]
        self.assertEqual(missing, 0)
        ids = [
            row[0]
            for row in self.store.conn.execute("SELECT uuid FROM transactions")
        ]
        self.assertEqual(len(ids), len(set(ids)))


class SyncConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"XDG_CONFIG_HOME": str(Path(self.tmp.name) / "config")}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_token_is_generated_once_and_persisted(self) -> None:
        first = sync_token(self.env)
        self.assertGreaterEqual(len(first), 16)
        self.assertEqual(sync_token(self.env), first)

    def test_token_can_be_replaced(self) -> None:
        sync_token(self.env)
        remember_sync_token("picked-by-the-user-token", self.env)
        self.assertEqual(sync_token(self.env), "picked-by-the-user-token")

    def test_port_defaults_and_round_trips(self) -> None:
        self.assertEqual(sync_port(self.env), DEFAULT_SYNC_PORT)
        remember_sync_port(9100, self.env)
        self.assertEqual(sync_port(self.env), 9100)
        remember_sync_port(70000, self.env)
        self.assertEqual(sync_port(self.env), DEFAULT_SYNC_PORT)


class SyncServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "contapy.db"
        store = DataStore(self.path, seed=False)
        store.add_account("Wallet", "Cash", 0.0)
        store.close()
        self.ingested: list[int] = []
        self.done = threading.Event()
        self.server = SyncServer(
            self.path,
            TOKEN,
            port=0,
            host="127.0.0.1",
            on_ingest=lambda count: (self.ingested.append(count), self.done.set()),
        )
        self.assertIsNotNone(self.server.start())
        self.base = f"http://127.0.0.1:{self.server.port_in_use}"

    def tearDown(self) -> None:
        self.server.stop()
        self.tmp.cleanup()

    def request(self, path: str, payload=None, token: str | None = TOKEN):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method="GET" if data is None else "POST",
            headers={"Content-Type": "application/json"},
        )
        if token:
            request.add_header("X-Sync-Token", token)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_requests_without_token_are_rejected(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/ping", token=None)
        self.assertEqual(caught.exception.code, 401)

    def test_ping_and_meta(self) -> None:
        status, body = self.request("/api/ping")
        self.assertEqual(status, 200)
        self.assertEqual(body["app"], "LetoBank")

        status, body = self.request("/api/meta")
        self.assertEqual(status, 200)
        self.assertEqual([a["name"] for a in body["accounts"]], ["Wallet"])

    def test_post_and_retry(self) -> None:
        status, body = self.request(
            "/api/transactions", {"transactions": [txn()]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["inserted"], 1)
        self.assertEqual(body["errors"], 0)
        self.assertTrue(self.done.wait(timeout=2))
        self.assertEqual(self.ingested, [1])

        status, body = self.request(
            "/api/transactions", {"transactions": [txn()]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["inserted"], 0)
        self.assertEqual(body["duplicate"], 1)

    def test_bare_array_payload_is_accepted(self) -> None:
        status, body = self.request("/api/transactions", [txn(uuid="bare-1")])
        self.assertEqual(status, 200)
        self.assertEqual(body["inserted"], 1)

    def test_bad_payloads(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/transactions", {"nope": []})
        self.assertEqual(caught.exception.code, 400)

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/transactions", {"transactions": "nope"})
        self.assertEqual(caught.exception.code, 400)

    def test_unknown_paths_are_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/whatever")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.domain import ConflictError, PermissionDenied, ValidationError
from src.repository import Repository
from src.service import Service
from src.rules import STATES, TRANSITION_ROLES

PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2999-01-01T00:00:00+00:00"


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = Service(self.repo)
        self.item = self.service.create_item(
            {"title": "notice item", "description": "notice gating", "severity": "warning",
             "quantity": 5, "threshold": 10, "external_ref": "NT-ITEM"},
            "creator", "sensor_operator")
        self.item = self.service.transition(
            self.item["id"], "warning", self.item["version"], "reviewer", "sensor_operator")

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def _notice(self, measure, no, **extra):
        payload = {"notice_no": no, "issuer": "市交通委", "measure": measure,
                   "effective_from": PAST}
        payload.update(extra)
        return self.service.create_notice(payload, "officer", "traffic_authority")

    def _restricted(self):
        return self.service.transition(
            self.item["id"], "restricted", self.item["version"], "reviewer", "bridge_engineer")

    def test_duplicate_notice_no_rejected(self):
        self._notice("restricted", "NT-1")
        with self.assertRaises(ConflictError):
            self._notice("restricted", "NT-1")
        notices = self.service.list_notices("viewer")
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["issuer"], "市交通委")
        self.assertEqual(self.service.list_notices("viewer", "closed"), [])

    def test_notice_role_and_validation(self):
        with self.assertRaises(PermissionDenied):
            self.service.create_notice(
                {"notice_no": "NT-X", "issuer": "市交通委", "measure": "restricted",
                 "effective_from": PAST}, "officer", "sensor_operator")
        with self.assertRaises(ValidationError):
            self._notice("restricted", "NT-X", effective_from="not-a-time")
        with self.assertRaises(ValidationError):
            self._notice("restricted", "NT-X", effective_to=PAST)
        with self.assertRaises(ValidationError):
            self._notice("lift", "NT-X")

    def test_missing_notice_blocks_and_preserves_state(self):
        with self.assertRaises(ConflictError) as ctx:
            self._restricted()
        self.assertIn("缺少", str(ctx.exception))
        item = self.service.get_item(self.item["id"], "viewer")
        self.assertEqual(item["status"], "warning")
        self.assertEqual(item["version"], self.item["version"])

    def test_expired_pending_and_lifted_notice_block(self):
        self._notice("restricted", "NT-EXP", effective_to="2020-06-01T00:00:00+00:00")
        with self.assertRaises(ConflictError) as ctx:
            self._restricted()
        self.assertIn("截止", str(ctx.exception))
        self._notice("restricted", "NT-PEND", effective_from=FUTURE)
        with self.assertRaises(ConflictError):
            self._restricted()
        self._notice("restricted", "NT-LIFT", lifted_at="2021-01-01T00:00:00+00:00")
        with self.assertRaises(ConflictError):
            self._restricted()
        self.assertEqual(self.service.get_item(self.item["id"], "viewer")["status"], "warning")

    def test_effective_notice_allows_restricted_and_closed(self):
        self._notice("restricted", "NT-R")
        current = self._restricted()
        self.assertEqual(current["status"], "restricted")
        with self.assertRaises(ConflictError):
            self.service.transition(current["id"], "closed", current["version"],
                                    "reviewer", "traffic_authority")
        self._notice("closed", "NT-C")
        current = self.service.transition(current["id"], "closed", current["version"],
                                          "reviewer", "traffic_authority")
        self.assertEqual(current["status"], "closed")

    def test_restore_requires_closed_records_and_restore_notice(self):
        self._notice("restricted", "NT-R")
        self._notice("closed", "NT-C")
        self.service.add_record(self.item["id"], {"kind": "risk", "detail": "裂缝",
                                                  "status": "open", "external_ref": "RISK-1"},
                                "recorder", "bridge_engineer")
        current = self._restricted()
        current = self.service.transition(current["id"], "closed", current["version"],
                                          "reviewer", "traffic_authority")
        with self.assertRaises(ConflictError):
            self.service.transition(current["id"], "restored", current["version"],
                                    "reviewer", "bridge_engineer")
        self._notice("restored", "NT-RE")
        with self.assertRaises(ConflictError) as ctx:
            self.service.transition(current["id"], "restored", current["version"],
                                    "reviewer", "bridge_engineer")
        self.assertIn("未关闭", str(ctx.exception))
        self.repo.conn.execute("UPDATE records SET status='closed' WHERE item_id=?",
                               (self.item["id"],))
        self.repo.conn.commit()
        current = self.service.transition(current["id"], "restored", current["version"],
                                          "reviewer", "bridge_engineer")
        self.assertEqual(current["status"], STATES[-1])

    def test_old_database_auto_migrates(self):
        self.repo.close()
        old = sqlite3.connect(self.db)
        old.executescript("""
            DROP TABLE IF EXISTS notices;
            CREATE TABLE IF NOT EXISTS legacy_marker(id INTEGER PRIMARY KEY, note TEXT);
            INSERT INTO legacy_marker(note) VALUES('old');
            PRAGMA user_version=0;
        """)
        old.close()
        self.repo = Repository(self.db)
        self.service = Service(self.repo)
        notice = self._notice("restricted", "NT-MIG")
        self.assertEqual(notice["notice_no"], "NT-MIG")
        row = self.repo.conn.execute("SELECT note FROM legacy_marker").fetchone()
        self.assertEqual(row["note"], "old")


if __name__ == "__main__":
    unittest.main()

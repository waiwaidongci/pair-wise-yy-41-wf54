import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.domain import ConflictError, NotFoundError, PermissionDenied, ValidationError
from src.repository import Repository
from src.rules import STATES, TRANSITION_ROLES
from src.service import Service

PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
OLD_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 0,
    threshold REAL NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK(status IN ('normal','warning','restricted','closed','restored')),
    version INTEGER NOT NULL DEFAULT 1,
    external_ref TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    external_ref TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(item_id, external_ref)
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    detail TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""


def notice_payload(no, measure, start=PAST, end=FUTURE):
    return {"notice_no": no, "issuer": "交通管理局", "measure": measure,
            "effective_from": start, "effective_to": end}


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(str(Path(self.tmp.name) / "test.db"))
        self.service = Service(self.repo)
        self.item = self.service.create_item(
            {"title": "notice item", "description": "notice driven transitions",
             "severity": "warning", "quantity": 8, "threshold": 4,
             "external_ref": "NT-ITEM-1"}, "creator", "sensor_operator")
        self.service.transition(self.item["id"], STATES[1], self.item["version"],
                                "reviewer", TRANSITION_ROLES[STATES[1]][0])

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def _notice(self, no, measure, start=PAST, end=FUTURE):
        return self.service.create_notice(notice_payload(no, measure, start, end),
                                          "clerk", "traffic_authority")

    def _current(self):
        return self.service.get_item(self.item["id"], "viewer")

    def _to_restricted(self):
        current = self._current()
        return self.service.transition(current["id"], "restricted", current["version"],
                                       "reviewer", TRANSITION_ROLES["restricted"][0])

    def test_duplicate_notice_no_rejected(self):
        self._notice("NT-1", "restriction")
        with self.assertRaises(ConflictError):
            self._notice("NT-1", "closure")

    def test_missing_notice_conflicts_and_state_kept(self):
        with self.assertRaises(ConflictError) as ctx:
            self._to_restricted()
        self.assertIn("缺少", str(ctx.exception))
        self.assertEqual(self._current()["status"], "warning")

    def test_future_and_expired_notice_conflict(self):
        self._notice("NT-2", "restriction", start=FUTURE, end="2099-02-01T00:00:00+00:00")
        with self.assertRaises(ConflictError) as ctx:
            self._to_restricted()
        self.assertIn("尚未生效", str(ctx.exception))
        self.assertEqual(self._current()["status"], "warning")
        self.service.lift_notice(1, "clerk", "traffic_authority")
        self._notice("NT-3", "restriction", start=PAST, end="2020-02-01T00:00:00+00:00")
        with self.assertRaises(ConflictError) as ctx:
            self._to_restricted()
        self.assertIn("已过期", str(ctx.exception))
        self.assertEqual(self._current()["status"], "warning")

    def test_lifted_notice_conflicts(self):
        notice = self._notice("NT-4", "restriction")
        self.service.lift_notice(notice["id"], "clerk", "traffic_authority")
        with self.assertRaises(ConflictError) as ctx:
            self._to_restricted()
        self.assertIn("已解除", str(ctx.exception))
        self.assertEqual(self._current()["status"], "warning")

    def test_restore_requires_closed_records_and_recovery_notice(self):
        self._notice("NT-5", "restriction")
        current = self._to_restricted()
        self._notice("NT-6", "closure")
        current = self.service.transition(current["id"], "closed", current["version"],
                                          "reviewer", TRANSITION_ROLES["closed"][0])
        self.assertEqual(current["status"], "closed")
        with self.assertRaises(ConflictError) as ctx:
            self.service.transition(current["id"], "restored", current["version"],
                                    "reviewer", TRANSITION_ROLES["restored"][0])
        self.assertIn("恢复", str(ctx.exception))
        self.service.add_record(self.item["id"],
                                {"kind": "risk", "detail": "open risk", "status": "open",
                                 "external_ref": "NT-RISK-1"}, "recorder", "sensor_operator")
        self._notice("NT-7", "recovery")
        with self.assertRaises(ConflictError) as ctx:
            self.service.transition(current["id"], "restored", current["version"],
                                    "reviewer", TRANSITION_ROLES["restored"][0])
        self.assertIn("仍有未关闭事项", str(ctx.exception))
        self.assertEqual(self._current()["status"], "closed")

    def test_full_flow_with_notices(self):
        self._notice("NT-8", "restriction")
        self._notice("NT-9", "closure")
        self._notice("NT-10", "recovery")
        current = self._to_restricted()
        for target in ("closed", "restored"):
            current = self.service.transition(current["id"], target, current["version"],
                                              "reviewer", TRANSITION_ROLES[target][0])
        self.assertEqual(current["status"], "restored")
        events = [e for e in self.service.audit("viewer", self.item["id"])
                  if e["action"] == "transition"]
        self.assertEqual(events[-1]["detail"]["notice_no"], "NT-10")

    def test_notice_validation_and_permission(self):
        with self.assertRaises(PermissionDenied):
            self.service.create_notice(notice_payload("NT-11", "closure"),
                                       "clerk", "viewer")
        with self.assertRaises(ValidationError):
            self._notice("NT-12", "not-a-measure")
        with self.assertRaises(ValidationError):
            self._notice("NT-13", "closure", start=FUTURE, end=PAST)
        with self.assertRaises(ValidationError):
            self._notice("NT-14", "closure", start="not-a-time")

    def test_lift_notice_guards(self):
        notice = self._notice("NT-15", "closure")
        lifted = self.service.lift_notice(notice["id"], "clerk", "traffic_authority")
        self.assertIsNotNone(lifted["lifted_at"])
        self.assertFalse(lifted["effective"])
        with self.assertRaises(ConflictError):
            self.service.lift_notice(notice["id"], "clerk", "traffic_authority")
        with self.assertRaises(NotFoundError):
            self.service.lift_notice(9999, "clerk", "traffic_authority")

    def test_list_notices_filter_and_effective_flag(self):
        self._notice("NT-16", "restriction")
        self._notice("NT-17", "closure", start=PAST, end="2020-02-01T00:00:00+00:00")
        notices = self.service.list_notices("viewer")
        self.assertEqual(len(notices), 2)
        restriction = self.service.list_notices("viewer", "restriction")
        self.assertEqual(len(restriction), 1)
        self.assertTrue(restriction[0]["effective"])
        closure = self.service.list_notices("viewer", "closure")
        self.assertFalse(closure[0]["effective"])
        with self.assertRaises(ValidationError):
            self.service.list_notices("viewer", "not-a-measure")

    def test_old_database_auto_upgrades(self):
        db_path = Path(self.tmp.name) / "old.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(OLD_SCHEMA)
        conn.close()
        repo = Repository(str(db_path))
        try:
            version = repo.conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertGreaterEqual(version, 2)
            notice = repo.create_notice("OLD-1", "交通管理局", "restriction",
                                        PAST, FUTURE, "clerk")
            self.assertEqual(notice["notice_no"], "OLD-1")
        finally:
            repo.close()


if __name__ == "__main__":
    unittest.main()

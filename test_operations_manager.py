import sqlite3
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from operations_manager import build_operations_summary


class OperationsManagerTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY, reference TEXT, name TEXT, preferred_date TEXT,
                preferred_time TEXT, status TEXT, payment_status TEXT, cleaner_id INTEGER,
                balance_amount INTEGER, created_at TEXT, archived_at TEXT, is_test INTEGER
            );
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at TEXT);
            CREATE TABLE cleaners (
                id INTEGER PRIMARY KEY, name TEXT, email TEXT, active INTEGER, password_hash TEXT,
                availability TEXT, services TEXT, postcode TEXT, travel_radius REAL,
                identity_verified INTEGER, right_to_work_verified INTEGER, created_at TEXT
            );
            CREATE TABLE cleaner_applicants (
                id INTEGER PRIMARY KEY, name TEXT, status TEXT, ai_recommendation TEXT,
                ai_score INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY, booking_id INTEGER, payment_type TEXT, amount INTEGER,
                status TEXT, provider_payment_id TEXT, created_at TEXT
            );
            CREATE TABLE automation_jobs (
                id INTEGER PRIMARY KEY, booking_id INTEGER, step TEXT, status TEXT, attempts INTEGER,
                max_attempts INTEGER, last_error TEXT, updated_at TEXT
            );
            CREATE TABLE automation_alerts (
                id INTEGER PRIMARY KEY, automation_key TEXT, title TEXT, detail TEXT,
                level TEXT, created_at TEXT, resolved_at TEXT
            );
            CREATE TABLE automation_logs (
                id INTEGER PRIMARY KEY, automation_key TEXT, event TEXT, detail TEXT,
                level TEXT, created_at TEXT
            );
            CREATE TABLE email_log (
                id INTEGER PRIMARY KEY, booking_id INTEGER, recipient TEXT, subject TEXT,
                status TEXT, error TEXT, created_at TEXT
            );
            CREATE TABLE booking_timeline (
                id INTEGER PRIMARY KEY, booking_id INTEGER, event TEXT, detail TEXT,
                level TEXT, created_at TEXT
            );
            CREATE TABLE cleaner_applicant_timeline (
                id INTEGER PRIMARY KEY, applicant_id INTEGER, event TEXT, detail TEXT,
                level TEXT, created_at TEXT
            );
            """
        )
        now = "2026-07-23T09:00:00+00:00"
        self.conn.execute(
            """INSERT INTO bookings VALUES
               (1,'SPK-TEST-1','Test Customer','2026-07-23','Morning','Deposit Paid',
                'Deposit Paid',NULL,7500,?,NULL,0)""",
            (now,),
        )
        self.conn.execute(
            """INSERT INTO bookings VALUES
               (2,'SPK-TEST-2','Completed Customer','2026-07-22','Morning','Completed',
                'Balance Due',1,4200,?,NULL,0)""",
            (now,),
        )
        self.conn.execute(
            "INSERT INTO customers VALUES (1,'Test Customer','test@example.com',?)",
            (now,),
        )
        self.conn.execute(
            """INSERT INTO cleaners VALUES
               (1,'Test Cleaner','cleaner@example.com',1,'hash','["Thursday"]','["Regular clean"]',
                'CB1 1AA',10,1,1,?)""",
            (now,),
        )
        self.conn.execute(
            "INSERT INTO cleaner_applicants VALUES (1,'Strong Applicant','New','Excellent',90,?,?)",
            (now, now),
        )
        self.conn.execute(
            "INSERT INTO payments VALUES (1,1,'deposit',2500,'Paid','pi_test',?)",
            (now,),
        )
        self.conn.execute(
            """INSERT INTO automation_jobs VALUES
               (1,1,'send_confirmations','Failed',4,4,'Provider unavailable',?)""",
            (now,),
        )
        self.conn.execute(
            "INSERT INTO automation_logs VALUES (1,'booking_autopilot','Booking checked','Read completed','Info',?)",
            (now,),
        )
        self.conn.execute(
            """INSERT INTO email_log VALUES
               (1,1,'test@example.com','Booking confirmation','Failed','Provider unavailable',?)""",
            (now,),
        )
        self.conn.execute(
            "INSERT INTO booking_timeline VALUES (1,1,'Booking created','Test booking','Info',?)",
            (now,),
        )
        self.conn.execute(
            "INSERT INTO cleaner_applicant_timeline VALUES (1,1,'Application received','Website','Info',?)",
            (now,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_builds_read_only_health_and_issue_groups(self):
        before = self.conn.total_changes
        dashboard = {
            "cards": {
                "revenue_today": 2500,
                "today_bookings": 1,
                "waiting_assignment": 1,
                "outstanding_balances": 11700,
            }
        }
        result = build_operations_summary(
            lambda: self.conn,
            dashboard,
            now=datetime(2026, 7, 23, 10, 0, tzinfo=ZoneInfo("Europe/London")),
        )

        self.assertTrue(result["read_only"])
        self.assertEqual(result["summary"]["today_revenue"], 2500)
        self.assertEqual(result["summary"]["bookings_today"], 1)
        self.assertEqual(result["summary"]["available_cleaners"], 1)
        self.assertEqual(result["summary"]["jobs_awaiting_assignment"], 1)
        self.assertEqual(result["business_health"]["status"], "Critical")
        self.assertTrue(result["groups"]["critical"])
        self.assertTrue(result["groups"]["needs_attention"])
        self.assertTrue(result["groups"]["suggested_actions"])
        self.assertTrue(result["groups"]["recent_activity"])
        self.assertEqual(self.conn.total_changes, before)


if __name__ == "__main__":
    unittest.main()

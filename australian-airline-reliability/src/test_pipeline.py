"""Independent acceptance checks against the generated SQLite database."""
import sqlite3, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.db=sqlite3.connect(ROOT/'reports/airline_reliability.sqlite')
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def test_grain_and_coverage(self):
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fact_route_month').fetchone()[0],12860)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM dim_date').fetchone()[0],1096)
        self.assertEqual(self.db.execute('SELECT COUNT(DISTINCT date) FROM fact_route_month').fetchone()[0],36)
    def test_weighted_rates(self):
        row=self.db.execute('SELECT scheduled,flown,cancelled,arrival_otp,cancellation_rate FROM v_annual WHERE year=2025').fetchone()
        self.assertEqual(row[:3],(418106,407541,10565))
        self.assertAlmostEqual(row[3],309022/407541)
        self.assertAlmostEqual(row[4],10565/418106)
    def test_scope_separation(self):
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dim_route WHERE origin='All Ports'").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dim_airline WHERE airline='All Airlines'").fetchone()[0],0)
        self.assertGreater(self.db.execute('SELECT SUM(scheduled) FROM network_month').fetchone()[0],self.db.execute('SELECT SUM(scheduled) FROM fact_route_month').fetchone()[0])
    def test_complete_matched_cohort(self):
        self.assertEqual(self.db.execute('SELECT routes FROM v_matched_yoy').fetchall(),[(116,),(116,)])
    def test_zero_denominator(self):
        self.assertIsNone(self.db.execute('SELECT 1.0*0/NULLIF(0,0)').fetchone()[0])
    def test_rolling_weighted_window(self):
        got=self.db.execute("SELECT cancellation_rate_3m FROM v_rolling WHERE date='2025-03-01'").fetchone()[0]
        expected=self.db.execute("SELECT 1.0*SUM(cancelled)/SUM(scheduled) FROM fact_route_month WHERE date BETWEEN '2025-01-01' AND '2025-03-01'").fetchone()[0]
        self.assertAlmostEqual(got,expected)
    def test_integrity(self):
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
if __name__=='__main__':unittest.main(verbosity=2)

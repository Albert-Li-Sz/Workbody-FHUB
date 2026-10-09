"""Schema 2 -> 3 migration and interrupted DDL leave legacy data recoverable."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wb_database import Database


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory();self.addCleanup(self.work.cleanup)
        self.path=os.path.join(self.work.name,'workbody.sqlite3')
        connection=sqlite3.connect(self.path)
        connection.executescript('''CREATE TABLE usage_records (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,at REAL NOT NULL,
            account TEXT,realm TEXT,model TEXT,api_key TEXT,outcome TEXT,billing_mode TEXT,
            total_tokens INTEGER NOT NULL DEFAULT 0,credit REAL,payload TEXT NOT NULL);
            CREATE TABLE usage_hourly (dimensions TEXT PRIMARY KEY,hour INTEGER NOT NULL,
            realm TEXT,account TEXT,model TEXT,api_key TEXT,requests INTEGER NOT NULL,
            client_aborted INTEGER NOT NULL,errors INTEGER NOT NULL,prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,reasoning_tokens INTEGER NOT NULL,cached_tokens INTEGER NOT NULL,total_tokens INTEGER NOT NULL);
            CREATE TRIGGER usage_hourly_insert AFTER INSERT ON usage_records BEGIN SELECT 1; END;
            PRAGMA user_version=2;''')
        row={'at':1791360000,'account':'account','realm':'cn','model':'model','key':'key',
            'total_tokens':123,'prompt_tokens':100,'completion_tokens':23,'outcome':'completed'}
        connection.execute('INSERT INTO usage_records(id,at,account,realm,model,api_key,outcome,billing_mode,total_tokens,credit,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('legacy',row['at'],'account','cn','model','key','completed','free',123,None,json.dumps(row)))
        connection.execute('INSERT INTO usage_hourly VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('legacy-dimensions',row['at'],'cn','account','model','key',1,0,0,100,23,0,0,123))
        connection.commit();connection.close()

    def test_migration_rebuilds_platform_scoped_rollups(self):
        db=Database(self.path,self.work.name,self.work.name);self.addCleanup(db.close_thread)
        self.assertEqual(db.connection().execute('PRAGMA user_version').fetchone()[0],3)
        self.assertEqual(db.usage_totals(upstream='workbuddy')[0]['total_tokens'],123)
        self.assertEqual(db.usage_totals(upstream='opencode_zen')[0]['total_tokens'],0)
        db.append_usage({'at':1791360001,'account':'zen','upstream':'opencode_zen','model':'model','key':'key',
            'realm':'','total_tokens':20,'prompt_tokens':10,'completion_tokens':10,'outcome':'completed'})
        self.assertEqual(db.usage_totals(upstream='opencode_zen')[0]['total_tokens'],20)
        self.assertEqual(db.usage_totals(upstream='workbuddy')[0]['total_tokens'],123)

    def test_failed_migration_rolls_back_column_rollups_and_version(self):
        opened=[]
        def interrupt(database, connection, version):
            opened.append(connection)
            raise RuntimeError('migration interrupted')
        with mock.patch.object(Database,'_configure_rollups',interrupt):
            with self.assertRaises(RuntimeError):Database(self.path,self.work.name,self.work.name)
        with self.assertRaises(sqlite3.ProgrammingError):opened[0].execute('SELECT 1')
        connection=sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],2)
        self.assertNotIn('upstream',[v[1] for v in connection.execute('PRAGMA table_info(usage_records)')])
        self.assertEqual(connection.execute('SELECT total_tokens FROM usage_hourly').fetchone()[0],123)
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM usage_records').fetchone()[0],1)


if __name__=='__main__':unittest.main()

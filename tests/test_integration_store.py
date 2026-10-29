"""Regression checks for merging existing console and companion databases."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from companion_persona import CompanionExperience
from server import DemoEngine
from task_store import initialize_tasks


class SharedStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'integration.db'
        self.engine = DemoEngine(self.path)
        self.experience = CompanionExperience(self.engine)
        self.learning = self.experience.learning

    def tearDown(self):
        self.temporary.cleanup()

    def test_existing_learning_tasks_migrate_once_without_id_collision_or_resurrection(self):
        original = self.learning.create_task('a', {'title': '现有任务'})
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM integration_migrations WHERE name='shared-tasks-v1'")
            db.execute("""INSERT INTO companion_learning_tasks
                (id,device_id,title,subject,priority,status,created_at,updated_at,remind_at,reminder_acked_at)
                VALUES (?,'a','旧学习计划','数学','high','pending','2026-01-01','2026-01-01',
                        '2026-01-01T08:00:00+00:00','2026-01-01T08:01:00+00:00')""", (original['id'],))
        initialize_tasks(self.path)
        tasks = self.engine.list_tasks('a')
        self.assertEqual(len(tasks), 2)
        migrated = next(t for t in tasks if t['title'] == '旧学习计划')
        self.assertNotEqual(migrated['id'], original['id'])
        self.assertEqual(migrated['status'], 'confirmed')
        self.assertEqual(migrated['reminder_state'], 'dismissed')
        self.assertEqual(self.learning.inspect('b')['tasks'], [])
        initialize_tasks(self.path)
        self.assertEqual(len(self.engine.list_tasks('a')), 2)
        self.learning.delete_task('a', migrated['id'])
        initialize_tasks(self.path)
        self.assertEqual(len(self.engine.list_tasks('a')), 1)

    def test_completion_acknowledgment_and_reopening_are_shared(self):
        task = self.learning.create_task('a', {'title': '复习', 'remind_at': '2026-01-01T08:00:00+00:00'})
        self.assertEqual(self.engine.list_tasks('a')[0]['reminder_state'], 'due')
        self.assertTrue(self.learning.acknowledge('a', task['id']))
        self.engine.update_task_status('a', task['id'], 'completed')
        self.assertTrue(self.learning.inspect('a')['tasks'][0]['completed_at'])
        self.engine.update_task_status('a', task['id'], 'confirmed')
        self.assertEqual(self.learning.inspect('a')['reminders'], [])
        self.assertEqual(self.engine.list_tasks('a')[0]['reminder_state'], 'dismissed')

    def test_new_task_does_not_prune_existing_learning_task(self):
        old = self.learning.create_task('a', {'title': '不能丢失的学习计划'})
        for i in range(105):
            conversation = self.engine.record_interaction('a', 'assistant', '明天18:30参加讲座', '请参加讲座')
            self.engine.create_task_from_interaction('a', conversation, '明天18:30参加讲座', '请参加讲座')
        # Query storage, since the console intentionally displays a bounded page.
        self.learning.update_task('a', old['id'], {'status': 'completed'})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 106)

    def test_reset_clears_integrated_state_only_for_selected_device(self):
        for identity in ('a', 'b'):
            self.learning.create_task(identity, {'title': '复习'})
            self.experience._remember(identity, '我喜欢数学')
            self.learning.create_record(identity, '数学', 20)
        self.engine.reset_device('a')
        self.assertEqual(self.learning.inspect('a')['tasks'], [])
        self.assertEqual(self.learning.inspect('a')['records'], [])
        self.assertEqual(self.experience.inspect('a')['memories'], [])
        self.assertEqual(len(self.learning.inspect('b')['tasks']), 1)
        self.assertEqual(len(self.experience.inspect('b')['memories']), 1)


if __name__ == '__main__':
    unittest.main()

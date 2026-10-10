import warnings

from django.db import migrations
from django.db.utils import OperationalError

TRIGGERS = {
    'workshop_auditlog_block_update': 'UPDATE',
    'workshop_auditlog_block_delete': 'DELETE',
}


def create_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    try:
        for name, event in TRIGGERS.items():
            schema_editor.execute(f'DROP TRIGGER IF EXISTS {name}')
            schema_editor.execute(
                f'CREATE TRIGGER {name} BEFORE {event} ON workshop_auditlog '
                "FOR EACH ROW SIGNAL SQLSTATE '45000' "
                "SET MESSAGE_TEXT = 'Audit log entries are immutable.'"
            )
    except OperationalError as exc:
        # 1419: binary logging requires SUPER/SET_USER_ID to create triggers.
        if exc.args and exc.args[0] == 1419:
            warnings.warn(
                'Audit log triggers were NOT created (error 1419); a DBA must create them. '
                'See the migration source for the SQL.',
                RuntimeWarning,
            )
            return
        raise


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    for name in TRIGGERS:
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {name}')


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('workshop', '0020_protect_audit_references'),
    ]

    operations = [
        migrations.RunPython(create_triggers, drop_triggers),
    ]

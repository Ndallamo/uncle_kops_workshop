from django.db import migrations


def install_database_audit_triggers(apps, schema_editor):
    from workshop.audit_triggers import ensure_database_audit_triggers

    ensure_database_audit_triggers(schema_editor.connection)


def remove_database_audit_triggers(apps, schema_editor):
    from workshop.audit_triggers import drop_database_audit_triggers

    drop_database_audit_triggers(schema_editor.connection)


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('workshop', '0022_merge_20261009_1908'),
    ]

    operations = [
        migrations.RunPython(install_database_audit_triggers, remove_database_audit_triggers),
    ]

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from workshop.audit_triggers import verify_database_audit_triggers


class Command(BaseCommand):
    help = 'Verify database-level audit triggers cover every MySQL base table.'

    def handle(self, *args, **options):
        connection = connections['default']
        if connection.vendor != 'mysql':
            raise CommandError('Database-wide audit triggers are supported only on MySQL.')
        missing = verify_database_audit_triggers(connection)
        if missing:
            raise CommandError('Missing or invalid audit triggers: ' + ', '.join(missing))
        self.stdout.write(self.style.SUCCESS('Database audit triggers cover all base tables.'))

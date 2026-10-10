"""MySQL triggers for immutable audit storage and database-level row change capture."""
import hashlib

from django.core.exceptions import ImproperlyConfigured


AUDIT_TABLE = 'workshop_auditlog'
IMMUTABILITY_TRIGGERS = {
    'workshop_auditlog_block_update': 'UPDATE',
    'workshop_auditlog_block_delete': 'DELETE',
}
EVENTS = ('INSERT', 'UPDATE', 'DELETE')


def immutability_sql(name):
    event = IMMUTABILITY_TRIGGERS[name]
    return (
        f'CREATE TRIGGER `{name}` BEFORE {event} ON `{AUDIT_TABLE}` '
        "FOR EACH ROW SIGNAL SQLSTATE '45000' "
        "SET MESSAGE_TEXT = 'Audit log entries are immutable.'"
    )


def _audit_trigger_name(table, event):
    digest = hashlib.sha1(table.encode('utf-8')).hexdigest()[:12]
    suffix = {'INSERT': 'ins', 'UPDATE': 'upd', 'DELETE': 'del'}[event]
    return f'workshop_rowaudit_{digest}_{suffix}'


def _database_tables(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT table_name FROM information_schema.tables '
            'WHERE table_schema = DATABASE() AND table_type = %s',
            ['BASE TABLE'],
        )
        tables = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            'SELECT table_name, column_name FROM information_schema.key_column_usage '
            'WHERE table_schema = DATABASE() AND constraint_name = %s '
            'ORDER BY table_name, ordinal_position',
            ['PRIMARY'],
        )
        primary_keys = {}
        for table, column in cursor.fetchall():
            primary_keys.setdefault(table, []).append(column)
        cursor.execute(
            'SELECT table_name FROM information_schema.columns '
            'WHERE table_schema = DATABASE() AND column_name = %s AND data_type IN '
            "('tinyint', 'smallint', 'mediumint', 'int', 'integer', 'bigint', 'decimal', 'numeric')",
            ['id'],
        )
        numeric_id_tables = {row[0] for row in cursor.fetchall()}
    # The audit table cannot audit its own inserts without recursive trigger writes.
    return [
        (table, primary_keys.get(table, []), table in numeric_id_tables)
        for table in tables if table != AUDIT_TABLE
    ]


def _create_row_trigger(connection, table, primary_keys, numeric_id, event):
    quote = connection.ops.quote_name
    trigger = _audit_trigger_name(table, event)
    image = 'OLD' if event == 'DELETE' else 'NEW'
    object_id = f'{image}.{quote("id")}' if numeric_id and 'id' in primary_keys else 'NULL'
    pk_pairs = ', '.join(
        "'{}', {}.{}".format(column.replace("'", "''"), image, quote(column))
        for column in primary_keys
    )
    primary_key_json = f'JSON_OBJECT({pk_pairs})' if pk_pairs else 'JSON_OBJECT()'
    table_literal = table.replace("'", "''")
    action = f'mysql_{event.lower()}'
    sql = (
        f'CREATE TRIGGER {quote(trigger)} AFTER {event} ON {quote(table)} '
        'FOR EACH ROW INSERT INTO ' + quote(AUDIT_TABLE) + ' '
        '(actor_id, action, object_type, object_id, details, created_at) VALUES '
        f"(NULL, '{action}', '{table_literal}', {object_id}, "
        f"JSON_OBJECT('source', 'mysql_trigger', 'database_user', USER(), "
        f"'connection_id', CONNECTION_ID(), 'primary_key', {primary_key_json}), "
        'UTC_TIMESTAMP(6))'
    )
    with connection.cursor() as cursor:
        cursor.execute(f'DROP TRIGGER IF EXISTS {quote(trigger)}')
        cursor.execute(sql)


def ensure_database_audit_triggers(connection):
    """Install row change triggers on every base table except the audit sink."""
    if connection.vendor != 'mysql':
        return
    try:
        tables = _database_tables(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT trigger_name, event_object_table, event_manipulation, action_timing, action_statement '
                'FROM information_schema.triggers WHERE trigger_schema = DATABASE()'
            )
            found = {row[0]: row[1:] for row in cursor.fetchall()}
        for table, primary_keys, numeric_id in tables:
            for event in EVENTS:
                name = _audit_trigger_name(table, event)
                row = found.get(name)
                if not row or row[:3] != (table, event, 'AFTER') or AUDIT_TABLE.upper() not in row[3].upper():
                    _create_row_trigger(connection, table, primary_keys, numeric_id, event)
        for name in IMMUTABILITY_TRIGGERS:
            event = IMMUTABILITY_TRIGGERS[name]
            row = found.get(name)
            if not row or row[:3] != (AUDIT_TABLE, event, 'BEFORE') or 'SIGNAL' not in row[3].upper():
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP TRIGGER IF EXISTS `{name}`')
                    cursor.execute(immutability_sql(name))
    except Exception as exc:
        if getattr(exc, 'args', ()) and exc.args[0] == 1419:
            raise ImproperlyConfigured(
                'MySQL refused to create audit triggers because binary logging is enabled. '
                'A database administrator must temporarily set '
                'log_bin_trust_function_creators=1 (or grant the required administrative privilege), '
                'then rerun manage.py migrate.'
            ) from exc
        raise ImproperlyConfigured(
            'Could not install database audit triggers on every MySQL table. '
            'Grant the migration account permission to create and drop triggers, then run migrate again.'
        ) from exc


def drop_database_audit_triggers(connection):
    if connection.vendor != 'mysql':
        return
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for table, _primary_keys, _numeric_id in _database_tables(connection):
            for event in EVENTS:
                cursor.execute(f'DROP TRIGGER IF EXISTS {quote(_audit_trigger_name(table, event))}')
        for name in IMMUTABILITY_TRIGGERS:
            cursor.execute(f'DROP TRIGGER IF EXISTS {quote(name)}')


def verify_database_audit_triggers(connection):
    if connection.vendor != 'mysql':
        return []
    expected = []
    for table, primary_keys, _numeric_id in _database_tables(connection):
        for event in EVENTS:
            expected.append((_audit_trigger_name(table, event), table, event, primary_keys))
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT trigger_name, event_object_table, event_manipulation, action_timing, action_statement '
            'FROM information_schema.triggers WHERE trigger_schema = DATABASE()'
        )
        found = {row[0]: row[1:] for row in cursor.fetchall()}
    missing = []
    for name, table, event, _primary_keys in expected:
        row = found.get(name)
        if not row or row[:3] != (table, event, 'AFTER') or AUDIT_TABLE.upper() not in row[3].upper():
            missing.append(name)
    for name, event in IMMUTABILITY_TRIGGERS.items():
        row = found.get(name)
        if not row or row[:3] != (AUDIT_TABLE, event, 'BEFORE') or 'SIGNAL' not in row[3].upper():
            missing.append(name)
    return missing

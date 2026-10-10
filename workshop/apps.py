from django.apps import AppConfig
from django.db import connections
from django.db.models.signals import post_migrate


def ensure_audit_triggers(sender, using, **kwargs):
    from .audit_triggers import ensure_database_audit_triggers

    ensure_database_audit_triggers(connections[using])

class WorkshopConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'workshop'
    verbose_name = "Uncle Kop's Workshop"

    def ready(self):
        post_migrate.connect(
            ensure_audit_triggers,
            sender=self,
            dispatch_uid='workshop.ensure_database_audit_triggers',
        )

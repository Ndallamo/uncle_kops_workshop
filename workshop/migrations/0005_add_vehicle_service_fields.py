from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workshop', '0004_passwordresettoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='service_plan',
            field=models.CharField(max_length=200, blank=True),
        ),
        migrations.AddField(
            model_name='vehicle',
            name='recent_service_history',
            field=models.TextField(blank=True),
        ),
    ]

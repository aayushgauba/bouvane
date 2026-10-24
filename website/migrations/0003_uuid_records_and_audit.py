import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_uuids(apps, schema_editor):
    for model_name in ['Enquiry', 'BetaSignup']:
        Model = apps.get_model('website', model_name)
        for record in Model.objects.using(schema_editor.connection.alias).all().iterator():
            record.uuid = uuid.uuid4()
            record.save(using=schema_editor.connection.alias, update_fields=['uuid'])


class Migration(migrations.Migration):
    dependencies = [('website', '0002_betasignup'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='enquiry', name='uuid', field=models.UUIDField(null=True, editable=False)),
        migrations.AddField(model_name='betasignup', name='uuid', field=models.UUIDField(null=True, editable=False)),
        migrations.RunPython(assign_uuids, migrations.RunPython.noop),
        migrations.RemoveField(model_name='enquiry', name='id'),
        migrations.AlterField(model_name='enquiry', name='uuid', field=models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False, serialize=False)),
        migrations.RenameField(model_name='enquiry', old_name='uuid', new_name='id'),
        migrations.RemoveField(model_name='betasignup', name='id'),
        migrations.AlterField(model_name='betasignup', name='uuid', field=models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False, serialize=False)),
        migrations.RenameField(model_name='betasignup', old_name='uuid', new_name='id'),
        migrations.CreateModel(
            name='PortalAuditEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False, serialize=False)),
                ('record_type', models.CharField(max_length=20)),
                ('record_id', models.UUIDField()),
                ('action', models.CharField(max_length=40)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import migrations
from django.utils import timezone


def aware(value):
    if value is not None and timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_default_timezone())
    return value


def import_legacy_users(apps, schema_editor):
    connection = schema_editor.connection
    tables = connection.introspection.table_names()
    if 'auth_user' not in tables:
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT id, email, password, first_name, last_name, is_staff, is_superuser, is_active, date_joined, last_login FROM auth_user')
        rows = cursor.fetchall()
    User = apps.get_model('accounts', 'User')
    seen = set()
    for row in rows:
        email = row[1].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise RuntimeError('Every legacy auth_user account must have a valid email before UUID migration. Fix missing email addresses in the original database and retry.') from exc
        if email in seen or User.objects.using(connection.alias).filter(email__iexact=email).exists():
            raise RuntimeError('Legacy user emails must be unique (case-insensitively). Resolve duplicate emails in the original database before retrying.')
        seen.add(email)
    for old_id, email, password, first_name, last_name, staff, superuser, active, joined, last_login in rows:
        # Raw SQLite cursor values may be naive datetimes even with USE_TZ.
        user = User.objects.using(connection.alias).create(
            email=email.strip().lower(), password=password, first_name=first_name,
            last_name=last_name, is_staff=staff, is_superuser=superuser,
            is_active=active, date_joined=aware(joined), last_login=aware(last_login),
        )
        # Retain roles without trusting any old email as already verified.
        for legacy_table, field, relation in [
            ('auth_user_groups', 'group_id', User.groups),
            ('auth_user_user_permissions', 'permission_id', User.user_permissions),
        ]:
            if legacy_table in tables:
                with connection.cursor() as cursor:
                    cursor.execute(f'SELECT {field} FROM {legacy_table} WHERE user_id = %s', [old_id])
                    values = cursor.fetchall()
                for (value,) in values:
                    relation.through.objects.using(connection.alias).create(user_id=user.pk, **{field: value})
    # Old sessions cannot be carried across a change in user primary keys.
    if 'django_session' in tables:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM django_session')


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]
    run_before = [('account', '0001_initial')]
    operations = [migrations.RunPython(import_legacy_users, migrations.RunPython.noop)]

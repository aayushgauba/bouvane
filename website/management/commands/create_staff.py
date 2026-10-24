import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from allauth.account.models import EmailAddress


class Command(BaseCommand):
    help = 'Create a staff account. Email verification and MFA enrollment remain required.'

    def add_arguments(self, parser):
        parser.add_argument('email')

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        User = get_user_model()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError('Enter a valid email address.') from exc
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError('An account with this email already exists.')
        password = getpass.getpass('Password: ')
        if password != getpass.getpass('Confirm password: '):
            raise CommandError('Passwords do not match.')
        try:
            validate_password(password, User(email=email))
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages)) from exc
        with transaction.atomic():
            user = User.objects.create_user(email=email, password=password, is_staff=True)
            EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
        self.stdout.write(self.style.SUCCESS('Staff account created. Sign in at /accounts/login/ to verify the email and enroll MFA.'))

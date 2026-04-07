"""
Management command to create the first administrator account.

Usage:
    python manage.py create_admin
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from coverage_tracker.models import UserProfile


class Command(BaseCommand):
    help = 'Create an administrator account for the PhysicianCoverage app'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin')
        parser.add_argument('--password', type=str, default=None)
        parser.add_argument('--email',    type=str, default='')
        parser.add_argument('--first',    type=str, default='Admin')
        parser.add_argument('--last',     type=str, default='User')

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists.'))
            user = User.objects.get(username=username)
        else:
            if not password:
                import getpass
                password = getpass.getpass(f'Password for "{username}": ')

            user = User.objects.create_user(
                username=username,
                password=password,
                email=options['email'],
                first_name=options['first'],
                last_name=options['last'],
                is_staff=True,
                is_superuser=True,
            )
            self.stdout.write(self.style.SUCCESS(f'Created user "{username}"'))

        profile, created = UserProfile.objects.get_or_create(user=user)
        profile.role = 'admin'
        profile.save()
        self.stdout.write(self.style.SUCCESS(
            f'✓ Administrator account ready.\n'
            f'  Username : {username}\n'
            f'  Login at : http://localhost:8000/login/\n'
        ))

"""
Creates a login account for every active physician that doesn't have one yet.

Usage:
    python manage.py create_physician_users
    python manage.py create_physician_users --default-password MyPass123
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from coverage_tracker.models import Physician, UserProfile
import secrets
import string


def _random_password(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


class Command(BaseCommand):
    help = 'Auto-create login accounts for all physicians that do not yet have one'

    def add_arguments(self, parser):
        parser.add_argument(
            '--default-password', type=str, default=None,
            help='Use this password for all new accounts (otherwise random passwords are generated)'
        )

    def handle(self, *args, **options):
        default_pw = options.get('default_password')
        physicians = Physician.objects.filter(is_active=True)
        created_count = 0
        skipped_count = 0

        self.stdout.write('\nPhysician Login Setup\n' + '─' * 40)

        for p in physicians:
            # Skip if already linked to a user
            if hasattr(p, 'userprofile'):
                self.stdout.write(f'  SKIP  {p} — already has account "{p.userprofile.user.username}"')
                skipped_count += 1
                continue

            # Build a username: first initial + last name, lowercase
            base_username = (p.first_name[:1] + p.last_name).lower().replace(' ', '')
            username = base_username
            suffix = 1
            while User.objects.filter(username=username).exists():
                username = f'{base_username}{suffix}'
                suffix += 1

            pw = default_pw or _random_password()
            user = User.objects.create_user(
                username=username,
                password=pw,
                email=p.email,
                first_name=p.first_name,
                last_name=p.last_name,
            )
            UserProfile.objects.create(user=user, role='physician', physician=p)

            self.stdout.write(
                self.style.SUCCESS(f'  CREATED  {p}')
                + f'  username={username}  password={pw if not default_pw else "(shared)"}'
            )
            created_count += 1

        self.stdout.write('─' * 40)
        self.stdout.write(self.style.SUCCESS(
            f'\n✓ Done. Created {created_count} account(s), skipped {skipped_count}.\n'
            f'  Physicians can log in at: http://localhost:8000/login/\n'
        ))
        if default_pw:
            self.stdout.write(self.style.WARNING(
                f'  All new accounts use password: {default_pw}\n'
                f'  Ask physicians to change their password after first login.\n'
            ))

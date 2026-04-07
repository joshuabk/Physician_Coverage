from .models import UserProfile


def user_profile(request):
    """Ensures request.user always has a .profile, even for superusers with no profile row."""
    if request.user.is_authenticated:
        try:
            _ = request.user.profile
        except Exception:
            UserProfile.objects.get_or_create(
                user=request.user,
                defaults={'role': 'admin' if request.user.is_superuser else 'physician'}
            )
    return {}

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages



NURSING_ALLOWED_URLS = {'clinic_list'}



def _ensure_profile(request):
    """Return the user's profile, creating one if it's somehow missing."""
    profile = getattr(request.user, 'profile', None)
    if profile is None:
        from .models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return profile


def _nursing_gate(request):
    """If a nursing login is requesting a page outside its allowlist, return a
    redirect response to the clinics page. Otherwise return None.

    Centralizing this here means every authenticated view — whichever of the
    decorators below guards it — enforces the nursing restriction identically.
    """
    profile = getattr(request.user, 'profile', None)
    if not (profile and profile.is_nursing):
        return None
    url_name = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
    if url_name in NURSING_ALLOWED_URLS:
        return None
    messages.error(request, 'Nursing accounts can only access the Clinics page.')
    return redirect('clinic_list')



def login_required_custom(view_func):
    """Redirect to login if not authenticated."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={request.path}')
        # Ensure profile exists
        _ensure_profile(request)
        gated = _nursing_gate(request)
        if gated is not None:
            return gated
        return view_func(request, *args, **kwargs)
    return wrapper

def clinic_access_required(view_func):
    """Allow admins and nursing logins.

    The clinics page is the one page a nursing login may view, so it can't use
    admin_required. Physicians (and any other non-admin) are sent to their own
    landing page.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={request.path}')
        profile = _ensure_profile(request)
        if not (profile.is_admin or profile.is_nursing):
            messages.error(request, 'You do not have permission to access that page.')
            return redirect('time_off_list')
        return view_func(request, *args, **kwargs)
    return wrapper



def admin_required(view_func):
    """Allow only admin users."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={request.path}')
        try:
            if not request.user.profile.is_admin:
                messages.error(request, 'You do not have permission to access that page.')
                return redirect('time_off_list')
        except Exception:
            from .models import UserProfile
            UserProfile.objects.get_or_create(user=request.user)
            messages.error(request, 'You do not have permission to access that page.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

def can_approve_required(view_func):
    """Allow admin OR physician administrator users (anyone who can approve time off)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={request.path}')
        try:
            if not request.user.profile.can_approve_time_off:
                messages.error(request, 'You do not have permission to access that page.')
                return redirect('time_off_list')
        except Exception:
            from .models import UserProfile
            UserProfile.objects.get_or_create(user=request.user)
            messages.error(request, 'You do not have permission to access that page.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

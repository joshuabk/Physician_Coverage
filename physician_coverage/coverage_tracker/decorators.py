from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def login_required_custom(view_func):
    """Redirect to login if not authenticated."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={request.path}')
        # Ensure profile exists
        try:
            _ = request.user.profile
        except Exception:
            from .models import UserProfile
            UserProfile.objects.get_or_create(user=request.user)
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

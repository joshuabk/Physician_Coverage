from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Physician, Clinic, TimeOffRequest, CoverageAssignment,
    PhysicianAvailability, CoverageRequest, UserProfile
)


# ── Inline UserProfile inside User admin ──────────────────────────────────────
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Role & Physician Link'
    fields = ('role', 'physician')


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'get_role', 'get_linked_physician', 'is_active')

    def get_role(self, obj):
        try:
            return obj.profile.get_role_display()
        except Exception:
            return '—'
    get_role.short_description = 'Role'

    def get_linked_physician(self, obj):
        try:
            p = obj.profile.physician
            return str(p) if p else '—'
        except Exception:
            return '—'
    get_linked_physician.short_description = 'Physician'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ── UserProfile standalone ────────────────────────────────────────────────────
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'physician']
    list_filter = ['role']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    raw_id_fields = ['physician']


# ── Physician ─────────────────────────────────────────────────────────────────
@admin.register(Physician)
class PhysicianAdmin(admin.ModelAdmin):
    list_display = ['last_name', 'first_name', 'email', 'physician_type', 'is_active']
    list_filter = ['physician_type', 'is_active']
    search_fields = ['first_name', 'last_name', 'email']
    ordering = ['physician_type', 'last_name']


# ── Clinic ────────────────────────────────────────────────────────────────────
@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'is_active']
    filter_horizontal = ['regular_physicians']


# ── TimeOffRequest ────────────────────────────────────────────────────────────
@admin.register(TimeOffRequest)
class TimeOffRequestAdmin(admin.ModelAdmin):
    list_display = ['physician', 'start_date', 'end_date', 'request_type', 'status', 'duration_days']
    list_filter = ['status', 'request_type', 'physician']
    date_hierarchy = 'start_date'
    ordering = ['-start_date']

    def duration_days(self, obj):
        return f"{obj.duration_days} day(s)"


# ── CoverageAssignment ────────────────────────────────────────────────────────
@admin.register(CoverageAssignment)
class CoverageAssignmentAdmin(admin.ModelAdmin):
    list_display = ['date', 'clinic', 'covering_physician', 'covered_physician', 'effective_daily_rate']
    list_filter = ['clinic', 'covering_physician']
    date_hierarchy = 'date'

    def effective_daily_rate(self, obj):
        return f"${obj.effective_daily_rate}"
    effective_daily_rate.short_description = 'Rate'


# ── PhysicianAvailability ─────────────────────────────────────────────────────
@admin.register(PhysicianAvailability)
class PhysicianAvailabilityAdmin(admin.ModelAdmin):
    list_display = ['physician', 'date', 'is_available']
    list_filter = ['is_available', 'physician']
    date_hierarchy = 'date'


# ── CoverageRequest ───────────────────────────────────────────────────────────
@admin.register(CoverageRequest)
class CoverageRequestAdmin(admin.ModelAdmin):
    list_display = ['physician', 'requested_date', 'status', 'created_at']
    list_filter = ['status', 'physician']
    ordering = ['-requested_date']

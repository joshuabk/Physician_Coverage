from django.contrib import admin
from .models import Physician, Clinic, TimeOffRequest, CoverageAssignment, PhysicianAvailability


@admin.register(Physician)
class PhysicianAdmin(admin.ModelAdmin):
    list_display = ['last_name', 'first_name', 'physician_type',  'email', 'daily_rate', 'agency', 'is_active']
    list_filter = ['physician_type', 'is_active', ]
    search_fields = ['first_name', 'last_name', 'email', 'agency']
    fieldsets = (
        ('Basic Info', {'fields': ('first_name', 'last_name', 'email','physician_type', 'is_active')}),
        ('Regular Physician', {'fields': ('total_vacation_days',), 'classes': ('collapse',)}),
        ('Locum Physician', {'fields': ('daily_rate', 'agency'), 'classes': ('collapse',)}),
    )


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ['name', 'location',  'is_active']
    list_filter = ['is_active']
    filter_horizontal = ['regular_physicians']
    search_fields = ['name', 'location']


@admin.register(TimeOffRequest)
class TimeOffRequestAdmin(admin.ModelAdmin):
    list_display = ['physician', 'start_date', 'end_date', 'request_type', 'status', 'duration_days']
    list_filter = ['status', 'request_type', 'physician']
    search_fields = ['physician__first_name', 'physician__last_name']
    date_hierarchy = 'start_date'

    def duration_days(self, obj):
        return f"{obj.duration_days} day(s)"


@admin.register(CoverageAssignment)
class CoverageAssignmentAdmin(admin.ModelAdmin):
    list_display = ['date', 'clinic', 'covering_physician', 'covered_physician', 'effective_daily_rate']
    list_filter = ['clinic', 'covering_physician']
    date_hierarchy = 'date'

    def effective_daily_rate(self, obj):
        return f"${obj.effective_daily_rate}"
    effective_daily_rate.short_description = 'Rate'


@admin.register(PhysicianAvailability)
class PhysicianAvailabilityAdmin(admin.ModelAdmin):
    list_display = ['physician', 'date', 'is_available']
    list_filter = ['is_available', 'physician']
    date_hierarchy = 'date'

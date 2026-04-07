from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard, name='dashboard'),

    # Physicians
    path('physicians/', views.physician_list, name='physician_list'),
    path('physicians/add/', views.add_physician, name='add_physician'),
    path('physicians/<int:pk>/', views.physician_detail, name='physician_detail'),
    path('physicians/<int:pk>/edit/', views.edit_physician, name='edit_physician'),
    path('physicians/psa/coverage-requests/', views.psa_coverage_request_view, name='psa_coverage_request'),
    path('physicians/psa/coverage-requests/add/', views.add_coverage_request, name='add_coverage_request'),
    path('physicians/psa/coverage-requests/<int:pk>/delete/', views.delete_coverage_request, name='delete_coverage_request'),

    # Time Off
    path('time-off/', views.time_off_list, name='time_off_list'),
    path('time-off/add/', views.add_time_off, name='add_time_off'),
    path('time-off/approved-coverage/', views.approved_time_off_coverage, name='approved_time_off_coverage'),
    path('time-off/<int:pk>/edit/', views.edit_time_off, name='edit_time_off'),
    path('time-off/<int:pk>/approve/', views.approve_time_off, name='approve_time_off'),
    path('time-off/<int:pk>/deny/', views.deny_time_off, name='deny_time_off'),
    path('time-off/<int:pk>/cancel/', views.cancel_time_off, name='cancel_time_off'),
    path('time-off/<int:pk>/assign-locum/', views.assign_locum_to_time_off, name='assign_locum_to_time_off'),
    path('coverage-day/<int:assignment_pk>/delete/', views.delete_time_off_coverage_day, name='delete_time_off_coverage_day'),

    # Clinics & Coverage
    path('clinics/', views.clinic_list, name='clinic_list'),
    path('clinics/add/', views.add_clinic, name='add_clinic'),
    path('clinics/<int:pk>/edit/', views.edit_clinic, name='edit_clinic'),
    path('coverage/add/', views.add_coverage, name='add_coverage'),
    path('coverage/<int:pk>/delete/', views.delete_coverage, name='delete_coverage'),
    path('locum-costs/', views.locum_costs, name='locum_costs'),

    # Availability
    path('availability/', views.availability_view, name='availability'),
    path('availability/mark/', views.mark_availability, name='mark_availability'),
    path('availability/update/', views.update_availability, name='update_availability'),

    # User Management (admin only)
    path('users/', views.user_management, name='user_management'),
    path('users/add/', views.add_user, name='add_user'),
    path('users/<int:pk>/edit/', views.edit_user, name='edit_user'),
    path('users/<int:pk>/delete/', views.delete_user, name='delete_user'),

    # Account
    path('account/password/', views.change_password, name='change_password'),
]

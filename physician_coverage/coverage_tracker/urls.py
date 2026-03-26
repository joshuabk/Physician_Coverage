from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('physicians/', views.physician_list, name='physician_list'),
    path('physicians/add/', views.add_physician, name='add_physician'),
    path('physicians/<int:pk>/', views.physician_detail, name='physician_detail'),
    path('physicians/<int:pk>/edit/', views.edit_physician, name='edit_physician'),
    path('time-off/approved-coverage/', views.approved_time_off_coverage, name='approved_time_off_coverage'),
    path('time-off/<int:pk>/assign-locum/', views.assign_locum_to_time_off, name='assign_locum_to_time_off'),
    path('coverage-day/<int:assignment_pk>/delete/', views.delete_time_off_coverage_day, name='delete_time_off_coverage_day'),
    path('time-off/', views.time_off_list, name='time_off_list'),
    path('time-off/add/', views.add_time_off, name='add_time_off'),
    path('time-off/<int:pk>/edit/', views.edit_time_off, name='edit_time_off'),
    path('time-off/<int:pk>/approve/', views.approve_time_off, name='approve_time_off'),
    path('time-off/<int:pk>/deny/', views.deny_time_off, name='deny_time_off'),
    path('time-off/<int:pk>/cancel/', views.cancel_time_off, name='cancel_time_off'),
    path('clinics/', views.clinic_list, name='clinic_list'),
    path('clinics/add/', views.add_clinic, name='add_clinic'),
    path('clinics/<int:pk>/edit/', views.edit_clinic, name='edit_clinic'),
    path('coverage/add/', views.add_coverage, name='add_coverage'),
    path('coverage/<int:pk>/delete/', views.delete_coverage, name='delete_coverage'),
    path('locum-costs/', views.locum_costs, name='locum_costs'),
    path('availability/', views.availability_view, name='availability'),
    path('availability/mark/', views.mark_availability, name='mark_availability'),
]

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import datetime
import calendar

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm

from .models import Physician, Clinic, TimeOffRequest, CoverageAssignment, PhysicianAvailability, CoverageRequest, UserProfile
from .forms import (
    TimeOffRequestForm, CoverageAssignmentForm,
    PhysicianAvailabilityForm, PhysicianForm, ClinicForm
)
from .decorators import login_required_custom, admin_required, can_approve_required


#admin pass:northside1  user: superuser

#physician  pass: doctor1,  user: doc

#physician  pass: psa_doctor1,  user: psa_doc

#physician_admin   pass: nroc_doc1,  user: nroc_admin

#physician_admin   pass: psa_doc1,  user: psa_admin



def get_holidays(year):
    holidays = []
    
    # Fixed holidays
    holidays.append(date(year, 1, 1))   # New Year's Day
    holidays.append(date(year, 7, 4))   # Independence Day
    holidays.append(date(year, 12, 25)) # Christmas Day
    may_cal = calendar.monthcalendar(year, 5)
    last_monday_may = [week[0] for week in may_cal if week[0] != 0][-1]
    holidays.append(date(year, 5, last_monday_may))
    
    # Labor Day: First Monday in September
    sep_cal = calendar.monthcalendar(year, 9)
    first_monday_sep = next(week[0] for week in sep_cal if week[0] != 0)
    holidays.append(date(year, 9, first_monday_sep))
    
    # Thanksgiving: 4th Thursday in November
    nov_cal = calendar.monthcalendar(year, 11)
    thursdays = [week[3] for week in nov_cal if week[3] != 0]  # Thursday index = 3
    fourth_thursday = thursdays[3]
    holidays.append(date(year, 11, fourth_thursday))
    
    return sorted(holidays)

HOLIDAYS = {
    (1, 1),   # New Year's Day
    (5, 25),  # Memorial Day
    (7, 4),   # Independence Day
    (9, 7),   # Labor Day
    (11, 26), # Thanksgiving
    (12, 25), # Christmas
}
def check_holiday(day):
    is_holiday = (day.month, day.day) in HOLIDAYS
    return is_holiday

def get_extra_workdays(year):
    """Weekend days that should be treated as workdays (schedulable)."""
    extra = set()
    # Sunday before Thanksgiving
    nov_cal = calendar.monthcalendar(year, 11)
    thursdays = [week[3] for week in nov_cal if week[3] != 0]
    fourth_thursday = thursdays[3]
    thanksgiving = date(year, 11, fourth_thursday)
    sunday_before = thanksgiving - timedelta(days=4)  # Thu - 4 = Sun
    extra.add(sunday_before)
    return extra

def is_workday(d, holidays=None, extra_workdays=None):
    """Return True if d is a schedulable workday (Mon-Fri, or an extra workday, minus holidays)."""
    if holidays and d in holidays:
        return False
    if extra_workdays and d in extra_workdays:
        return True
    return d.weekday() < 5




@admin_required
def dashboard(request):
    today = date.today()
    year = int(request.GET.get('year', today.year))

    regular_physicians = Physician.objects.filter(is_active=True, physician_type='regular')
    locum_physicians = Physician.objects.filter(is_active=True, physician_type='locum')

    todays_coverage = CoverageAssignment.objects.filter(
        date=today, no_coverage_needed=False                              # ← added filter
    ).select_related('clinic', 'covering_physician', 'covered_physician')
    requests = TimeOffRequest.objects.filter(status='cancelled')
    print(f" requests {requests}")
    #for req in list(requests):
        #req.delete()

    out_today = TimeOffRequest.objects.filter(
        status='approved', start_date__lte=today, end_date__gte=today
    ).select_related('physician')

    upcoming = TimeOffRequest.objects.filter(
        status='approved', start_date__gte=today,
        start_date__lte=today + timedelta(days=30)
    ).select_related('physician').order_by('start_date')[:10]

    pending = TimeOffRequest.objects.filter(status='pending').select_related('physician').order_by('start_date')

    # Vacation summaries for regular physicians only
    physician_summaries = []
    for p in regular_physicians:
        physician_summaries.append({
            'physician': p,
            'days_taken': p.days_taken(year),
            'days_pending': p.days_pending(year),
            'days_remaining': p.days_remaining(year),
            'total': p.total_vacation_days,
        })

    # Locum cost summary for the year
    locum_summaries = []
    total_locum_cost = Decimal('0.00')
    total_locum_hours = 0
    for p in locum_physicians:
        hours = p.total_coverage_hours(year)
        cost = p.total_coverage_cost(year)
        total_locum_cost += cost
        total_locum_hours += hours
        locum_summaries.append({
            'physician': p,
            'hours': hours,
            'cost': cost,
        })

    is_admin = getattr(getattr(request.user, 'profile', None), 'is_admin', False)

    context = {
        'year': year,
        'today': today,
        'regular_physicians': regular_physicians,
        'locum_physicians': locum_physicians,
        'todays_coverage': todays_coverage,
        'out_today': out_today,
        'upcoming': upcoming,
        'pending': pending,
        'physician_summaries': physician_summaries,
        'locum_summaries': locum_summaries if is_admin else [],
        'total_locum_cost': total_locum_cost if is_admin else None,
        'total_locum_hours': total_locum_hours if is_admin else None,
        'is_admin': is_admin,
    }
    return render(request, 'coverage_tracker/dashboard.html', context)


@admin_required
def physician_list(request):
    physician_type = request.GET.get('type', 'regular')
    sub_tab = request.GET.get('sub', 'list')  # 'list' or 'coverage_days' for PSA
    year = int(request.GET.get('year', date.today().year))
    physicians = Physician.objects.filter(is_active=True, physician_type=physician_type)

    summaries = []
    for p in physicians:
        if p.is_regular:
            summaries.append({
                'physician': p,
                'days_taken': p.days_taken(year),
                'days_pending': p.days_pending(year),
                'days_remaining': p.days_remaining(year),
                'total': p.total_vacation_days,
                'clinics': p.assigned_clinics.filter(is_active=True),
            })
        elif p.is_psa:
            summaries.append({
                'physician': p,
                'days_taken': p.days_taken(year),
                'days_pending': p.days_pending(year),
                'days_remaining': p.days_remaining(year),
                'total': p.total_vacation_days,
                'clinics': p.assigned_clinics.filter(is_active=True),
                'requested_days': p.requested_coverage_days(year),
            })
        else:
            summaries.append({
                'physician': p,
                'days': p.total_coverage_days(year),
                'hours': p.total_coverage_hours(year),
                'cost': p.total_coverage_cost(year),
                'clinics': [],
            })

    # For PSA coverage_days sub-tab, gather per-physician coverage request data
    psa_coverage_data = []
    if physician_type == 'psa' and sub_tab == 'coverage_days':
        for s in summaries:
            requests = CoverageRequest.objects.filter(
                physician=s['physician'], requested_date__year=year
            ).order_by('requested_date')
            psa_coverage_data.append({
                'physician': s['physician'],
                'requests': requests,
                'total': requests.count(),
            })

    is_admin = getattr(getattr(request.user, 'profile', None), 'is_admin', False)

    # Physicians cannot view the locum tab at all
    if physician_type == 'locum' and not is_admin:
        from django.http import HttpResponseForbidden
        messages.error(request, 'You do not have permission to view locum physician details.')
        return redirect('physician_list')

    return render(request, 'coverage_tracker/physician_list.html', {
        'summaries': summaries,
        'year': year,
        'physician_type': physician_type,
        'sub_tab': sub_tab,
        'psa_coverage_data': psa_coverage_data,
        'is_admin': is_admin,
    })


@admin_required
def physician_detail(request, pk):
    physician = get_object_or_404(Physician, pk=pk)
    year = int(request.GET.get('year', date.today().year))
    time_off_requests = TimeOffRequest.objects.filter(physician=physician).order_by('-start_date')
    coverage = CoverageAssignment.objects.filter(
        covering_physician=physician
    ).order_by('-date').select_related('clinic', 'covered_physician')
    availability = PhysicianAvailability.objects.filter(
        physician=physician, date__gte=date.today()
    ).order_by('date')[:30]

    # Cost breakdown for locums
    coverage_this_year = CoverageAssignment.objects.filter(
        covering_physician=physician, date__year=year
    ).select_related('clinic')
    
    is_regular_like = physician.is_regular or physician.is_psa


    context = {
        'physician': physician,
        'year': year,
        'days_taken': physician.days_taken(year) if is_regular_like else None,
        'days_remaining': physician.days_remaining(year) if is_regular_like else None,
        'days_pending': physician.days_pending(year) if is_regular_like else None,
        'coverage_hours': physician.total_coverage_hours(year) if physician.is_locum else None,
        
        'coverage_cost': physician.total_coverage_cost(year) if physician.is_locum else None,
        'assigned_clinics': physician.assigned_clinics.all() if is_regular_like else [],
        'time_off_requests': time_off_requests,
        'coverage': coverage[:20],
        'coverage_this_year': coverage_this_year,
        'availability': availability,
    }
    return render(request, 'coverage_tracker/physician_detail.html', context)


@admin_required
def add_physician(request):
    if request.method == 'POST':
        form = PhysicianForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Physician added successfully.')
            return redirect('physician_list')
    else:
        ptype = request.GET.get('type', 'regular')
        form = PhysicianForm(initial={'physician_type': ptype})
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Add Physician', 'back_url': 'physician_list'
    })


@admin_required
def edit_physician(request, pk):
    physician = get_object_or_404(Physician, pk=pk)
    if request.method == 'POST':
        form = PhysicianForm(request.POST, instance=physician)
        if form.is_valid():
            form.save()
            messages.success(request, 'Physician updated.')
            return redirect('physician_detail', pk=pk)
    else:
        form = PhysicianForm(instance=physician)
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': f'Edit {physician}', 'back_url': 'physician_list'
    })

@admin_required
def delete_physician(request, pk):
    """
    Delete a physician. If the physician has historical records (time-off
    requests or coverage assignments), we soft-delete by setting is_active=False
    to preserve history. Only physicians with no records are hard-deleted.
    """
    physician = get_object_or_404(Physician, pk=pk)

    if request.method != 'POST':
        # Don't support GET-based deletion — redirect back
        return redirect('physician_detail', pk=pk)

    has_time_off = TimeOffRequest.objects.filter(physician=physician).exists()
    has_coverage = (
        CoverageAssignment.objects.filter(covering_physician=physician).exists()
        or CoverageAssignment.objects.filter(covered_physician=physician).exists()
    )

    name = str(physician)

    if has_time_off or has_coverage:
        # Soft delete — preserve history
        physician.is_active = False
        physician.save()
        messages.success(
            request,
            f'{name} has historical records and was deactivated (hidden from lists). '
            f'Use "Force delete" in the admin to permanently remove.'
        )
    else:
        physician.delete()
        messages.success(request, f'{name} was deleted.')

    return redirect('physician_list')

@login_required_custom
def time_off_list(request):
    profile = getattr(request.user, 'profile', None)
    is_admin = bool(profile and profile.is_admin)
    is_physician_admin = bool(profile and profile.is_physician_admin)
    can_approve = bool(profile and profile.can_approve_time_off)
    status = request.GET.get('status', '')
    physician_id = request.GET.get('physician', '')
    qs = TimeOffRequest.objects.select_related('physician').order_by('-start_date')

    # Full admins see everything (with optional filters); physician admins and
    # physicians see all pending + approved requests across the team.
    viewer_scope = profile.scope if profile else 'nroc'
    # 'nroc' here maps to the DB value 'regular' on Physician.physician_type.
    SCOPE_TO_TYPE = {'nroc': ['regular'], 'psa': ['psa'], 'all': ['regular', 'psa']}

    if is_admin:
        if status:
            qs = qs.filter(status=status)
        if physician_id:
            qs = qs.filter(physician_id=physician_id)
    else:
        qs = qs.filter(status__in=['pending', 'approved'])
        allowed_types = SCOPE_TO_TYPE.get(viewer_scope, [])
        if allowed_types:
            qs = qs.filter(physician__physician_type__in=allowed_types)
        else:
            qs = qs.none()

    physicians = Physician.objects.filter(is_active=True, physician_type__in=['regular', 'psa'])

    # Resolve the logged-in user's physician record (used to mark their own requests)
    viewer_physician = profile.physician if profile else None

    # Attach coverage info to each approved request
    enriched_requests = []
    for req in qs:
        coverage = None
        coverage_status = None
        if req.status == 'approved':
            assignments = CoverageAssignment.objects.filter(
                covered_physician=req.physician,
                date__gte=req.start_date,
                date__lte=req.end_date,
            ).select_related('covering_physician', 'clinic').order_by('date')
            covered_dates = set(a.date for a in assignments)
            all_dates_count = req.duration_days
            if assignments.exists():
                if len(covered_dates) >= all_dates_count:
                    coverage_status = 'full'
                else:
                    coverage_status = 'partial'
            else:
                coverage_status = 'none'
            # Get unique locums
            locum_names = list({a.covering_physician for a in assignments if a.covering_physician_id})
            coverage = locum_names
        enriched_requests.append({
            'req': req,
            'coverage': coverage,
            'coverage_status': coverage_status,
            'is_own': viewer_physician is not None and req.physician_id == viewer_physician.pk,
        })

    return render(request, 'coverage_tracker/time_off_list.html', {
        'enriched_requests': enriched_requests,
        'physicians': physicians,
        'status_filter': status,
        'physician_filter': physician_id,
        'is_admin': is_admin,
        'is_physician_admin': is_physician_admin,
        'can_approve': can_approve,
    })


@login_required_custom
def add_time_off(request):
    profile = getattr(request.user, 'profile', None)
    is_admin = bool(profile and profile.is_admin)
    viewer_scope = profile.scope if profile else 'nroc'

    # Which physician types may this login submit for?
    SCOPE_TO_TYPE = {'nroc': ['regular'], 'psa': ['psa'], 'all': ['regular', 'psa']}
    allowed_types = SCOPE_TO_TYPE.get(viewer_scope, ['regular', 'psa']) if not is_admin else ['regular', 'psa']

    def restrict_queryset(form):
        form.fields['physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type__in=allowed_types,
        ).order_by('last_name', 'first_name')

    if request.method == 'POST':
        form = TimeOffRequestForm(request.POST)
        # Status is always pending for new requests — remove from form
        form.fields.pop('status', None)
        restrict_queryset(form)
        if form.is_valid():
            req = form.save(commit=False)
            # Never let a non-admin submit for a physician outside their scope
            if not is_admin and req.physician.physician_type not in allowed_types:
                messages.error(request, 'You can only submit time off for physicians in your group.')
                return redirect('time_off_list')
            req.status = 'pending'
            req.save()
            messages.success(request, 'Time off request submitted.')
            return redirect('time_off_list')
    else:
        physician_id = request.GET.get('physician')
        initial = {'physician': physician_id} if physician_id and is_admin else {}
        form = TimeOffRequestForm(initial=initial)

    # Status is always pending for new requests — hide on render
    form.fields.pop('status', None)
    restrict_queryset(form)

    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Request Time Off', 'back_url': 'time_off_list',
    })


def _remove_coverage_for_request(req):
    """Delete all CoverageAssignments linked to this time-off request's physician and date range."""
    deleted_qs = CoverageAssignment.objects.filter(
        covered_physician=req.physician,
        date__gte=req.start_date,
        date__lte=req.end_date,
    )
    count = deleted_qs.count()
    deleted_qs.delete()
    return count


@login_required_custom
def edit_time_off(request, pk):
    req = get_object_or_404(TimeOffRequest, pk=pk)
    old_status = req.status
    if request.method == 'POST':
        form = TimeOffRequestForm(request.POST, instance=req)
        if form.is_valid():
            updated = form.save()
            # If status changed TO cancelled, remove all coverage assignments
            if updated.status == 'cancelled' and old_status != 'cancelled':
                removed = _remove_coverage_for_request(updated)
                if removed:
                    messages.warning(
                        request,
                        f'Request cancelled. {removed} locum coverage assignment{"s" if removed != 1 else ""} removed.'
                    )
                else:
                    messages.success(request, 'Request cancelled.')
            else:
                messages.success(request, 'Request updated.')
            return redirect('time_off_list')
    else:
        form = TimeOffRequestForm(instance=req)
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Edit Time Off Request', 'back_url': 'time_off_list'
    })


@login_required_custom
def cancel_time_off(request, pk):
    """One-click cancellation: removes coverage assignments and sets status to cancelled."""
    req = get_object_or_404(TimeOffRequest, pk=pk)
    if req.status == 'cancelled':
        messages.info(request, 'Request is already cancelled.')
        return redirect('time_off_list')

    removed = _remove_coverage_for_request(req)
    req.status = 'cancelled'
    p_name = req.physician
    req.delete()

    if removed:
        messages.warning(
            request,
            f'Time off for {p_name} cancelled. '
            f'{removed} locum coverage assignment{"s" if removed != 1 else ""} removed.'
        )
    else:
        messages.success(request, f'Time off for {req.physician} cancelled.')
    return redirect('time_off_list')


@can_approve_required
def approve_time_off(request, pk):
    req = get_object_or_404(TimeOffRequest, pk=pk)
    req.status = 'approved'
    req.save()
    messages.success(request, f'Approved time off for {req.physician}.')
    return redirect('time_off_list')


@can_approve_required
def deny_time_off(request, pk):
    req = get_object_or_404(TimeOffRequest, pk=pk)
    req.status = 'denied'
    req.save()
    messages.warning(request, f'Denied time off for {req.physician}.')
    return redirect('time_off_list')


@admin_required
def clinic_list(request):
    selected_date = request.GET.get('date', str(date.today()))
    try:
        view_date = datetime.datetime.strptime(selected_date, '%Y-%m-%d').date()
    except ValueError:
        view_date = date.today()

    clinics = Clinic.objects.filter(is_active=True).prefetch_related('regular_physicians')
    out_ids = TimeOffRequest.objects.filter(
        status='approved', start_date__lte=view_date, end_date__gte=view_date
    ).values_list('physician_id', flat=True)

    clinic_data = []
    for clinic in clinics:
        assignments = CoverageAssignment.objects.filter(
            clinic=clinic, date=view_date, no_coverage_needed=False       # ← added
        ).select_related('covering_physician', 'covered_physician')
        no_cov_physician_ids = set(                                       # ← NEW
        CoverageAssignment.objects.filter(
            date=view_date, no_coverage_needed=True
        ).values_list('covered_physician_id', flat=True)
        )
        regular_out = [
        p for p in clinic.regular_physicians.all()
        if p.id in out_ids and p.id not in no_cov_physician_ids       # ← updated
        ]
        clinic_data.append({
            'clinic': clinic,
            'assignments': assignments,
            'regular_out': regular_out,
        })

    available_locums = Physician.objects.filter(
        is_active=True, physician_type='locum'
    ).exclude(
        coverage_assignments__date=view_date
    )

    return render(request, 'coverage_tracker/clinic_list.html', {
        'clinic_data': clinic_data,
        'view_date': view_date,
        'available_locums': available_locums,
    })


@admin_required
def add_clinic(request):
    if request.method == 'POST':
        form = ClinicForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Clinic added.')
            return redirect('clinic_list')
    else:
        form = ClinicForm()
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Add Clinic', 'back_url': 'clinic_list'
    })


@admin_required
def edit_clinic(request, pk):
    clinic = get_object_or_404(Clinic, pk=pk)
    if request.method == 'POST':
        form = ClinicForm(request.POST, instance=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, 'Clinic updated.')
            return redirect('clinic_list')
    else:
        form = ClinicForm(instance=clinic)
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': f'Edit {clinic}', 'back_url': 'clinic_list'
    })


@admin_required
def add_coverage(request):
    if request.method == 'POST':
        form = CoverageAssignmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Coverage assignment added.')
            return redirect('clinic_list')
    else:
        date_str = request.GET.get('date', str(date.today()))
        form = CoverageAssignmentForm(initial={'date': date_str})
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Assign Locum Coverage', 'back_url': 'clinic_list'
    })


@admin_required
def delete_coverage(request, pk):
    assignment = get_object_or_404(CoverageAssignment, pk=pk)
    date_str = str(assignment.date)
    assignment.delete()
    messages.success(request, 'Coverage assignment removed.')
    return redirect(f'/clinics/?date={date_str}')


@admin_required
def locum_costs(request):
    year = int(request.GET.get('year', date.today().year))
    month = request.GET.get('month', '')

    assignments = CoverageAssignment.objects.filter(
        date__year=year, no_coverage_needed=False
    ).select_related('covering_physician', 'clinic', 'covered_physician')

    if month:
        assignments = assignments.filter(date__month=int(month))

    assignments = assignments.order_by('date', 'clinic')
    #for a in list(assignments):
        #print(a)
        #a.delete()

    # Per-locum rollup
    locums = Physician.objects.filter(is_active=True, physician_type='locum')
    locum_data = []
    grand_total = Decimal('0.00')
    grand_hours = Decimal('0.00')

    for p in locums:
        yr_assignments = [a for a in assignments if a.covering_physician_id == p.id]
        hours = sum((a.hours for a in yr_assignments), Decimal('0.00'))
        cost = sum(a.cost for a in yr_assignments)
        grand_total += cost
        grand_hours += hours
        
        locum_data.append({
            'physician': p,
            'hours': hours,
            'cost': cost,
            'standard_rate': p.hourly_rate,
        })

    # Monthly breakdown
    monthly_totals = {}
    for a in CoverageAssignment.objects.filter(date__year=year).select_related('covering_physician'):
        if a.no_coverage_needed or a.covering_physician is None:          # ← guard
            continue
        m = a.date.month
        if m not in monthly_totals:
            monthly_totals[m] = {'hours': 0, 'cost': Decimal('0.00')}
        monthly_totals[m]['hours'] += a.hours
        monthly_totals[m]['cost'] += a.cost

    months = []
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    for i in range(1, 13):
        d = monthly_totals.get(i, {'hours': Decimal('0.00'), 'cost': Decimal('0.00')})
        months.append({'num': i, 'name': month_names[i-1], **d})
    #num_assigned = 0
    num_assigned = sum(1 for s in locum_data if s['hours'] > 0)
    #print([1 for s in locum_data if s['days'] > 0])
    if grand_hours > 0:
        avg_hourly_rate = (grand_total / grand_hours).quantize(Decimal('0.01'))
    else:
        avg_hourly_rate = Decimal('0.00')
    


    context = {
        'year': year,
        'month_filter': month,
        'assignments': assignments,
        'locum_data': locum_data,
        'months': months,
        'grand_total': grand_total,
        'grand_hours': grand_hours,
        'avg_hourly_rate': avg_hourly_rate,
        'assigned_count': num_assigned,
        'years': [2023, 2024, 2025, 2026, 2027],
    }
    return render(request, 'coverage_tracker/locum_costs.html', context)


@admin_required
def availability_view(request):
    selected_date = request.GET.get('date', str(date.today()))
    try:
        view_date = datetime.datetime.strptime(selected_date, '%Y-%m-%d').date()
    except ValueError:
        view_date = date.today()

    week_start = view_date - timedelta(days=view_date.weekday())
    all_days = [week_start + timedelta(days=i) for i in range(21)]

    holidays = set(get_holidays(week_start.year))
    if all_days[-1].year != week_start.year:
        holidays |= set(get_holidays(all_days[-1].year))

    extra = get_extra_workdays(week_start.year)
    if all_days[-1].year != week_start.year:
        extra |= get_extra_workdays(all_days[-1].year)
   

    calendar_days = [d for d in all_days if is_workday(d, holidays, extra) or (d in holidays and d.weekday() < 5)]


    # All active physicians (not just locums)
    all_physicians = Physician.objects.filter(is_active=True, physician_type = 'locum').order_by('last_name', 'first_name')

    time_off = TimeOffRequest.objects.filter(
        status='approved',
        start_date__lte=calendar_days[-1],
        end_date__gte=calendar_days[0]
    )

    off_set = set()
    for req in time_off:
        d = req.start_date
        while d <= req.end_date:
            off_set.add((req.physician_id, d))
            d += timedelta(days=1)

    assigned_set = set()
    for a in CoverageAssignment.objects.filter(
        date__gte=calendar_days[0], date__lte=calendar_days[-1]
    ):
        assigned_set.add((a.covering_physician_id, a.date))

    # Load manual availability overrides for all physicians
    avail_map = {}
    for av in PhysicianAvailability.objects.filter(
        date__gte=calendar_days[0], date__lte=calendar_days[-1]
    ):
        avail_map[(av.physician_id, av.date)] = 'available' if av.is_available else 'unavailable'

    grid = []
    for p in all_physicians:
        row = []
        for d in calendar_days:
            if d in holidays:
                row.append('holiday')
            elif (p.id, d) in assigned_set:
                row.append('assigned')
            elif (p.id, d) in off_set:
                row.append('unavailable')
            elif (p.id, d) in avail_map:
                row.append(avail_map[(p.id, d)])
            else:
                row.append('available')
        grid.append({'physician': p, 'days': row})

    return render(request, 'coverage_tracker/availability.html', {
        'grid': grid,
        'calendar_days': calendar_days,
        'view_date': view_date,
        'today': date.today(),
        'holiday_set': holidays,
    })


@admin_required
def update_availability(request):
    """AJAX endpoint: set a physician's availability for a specific date."""
    import json
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            physician_id = data.get('physician_id')
            date_str = data.get('date')
            status = data.get('status')  # 'available', 'assigned', 'unavailable'

            physician = Physician.objects.get(pk=physician_id, is_active=True)
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()

            if status == 'assigned':
                # Cannot assign via this endpoint; return error
                from django.http import JsonResponse
                return JsonResponse({'error': 'Use the coverage assignment form to assign coverage.'}, status=400)

            if status not in ('available', 'unavailable'):
                return JsonResponse({'error': 'Invalid status.'}, status=400)


            removed = CoverageAssignment.objects.filter(
                covering_physician=physician,
                date=target_date,
                ).delete()[0]

            is_available = (status == 'available')
            PhysicianAvailability.objects.update_or_create(
                    physician=physician,
                    date=target_date,
                    defaults={'is_available': is_available}
                )
            from django.http import JsonResponse

            return JsonResponse({
            'ok': True,
            'status': status,
            'assignments_removed': removed,
        })
        except Exception as e:
            
            return JsonResponse({'error': str(e)}, status=400)
    
        except Physician.DoesNotExist:
            return JsonResponse({'error': 'Physician not found.'}, status=404)


@admin_required
def approved_time_off_coverage(request):
    """
    Shows all approved time-off requests with per-day locum coverage.
    """
    today = date.today()
    year = int(request.GET.get('year', today.year))

    approved_requests = TimeOffRequest.objects.filter(
        status='approved',
        start_date__year=year,
    ).select_related('physician').order_by('start_date')

    enriched = []
    for req in approved_requests:
        existing_coverage = {
            a.date: a
            for a in CoverageAssignment.objects.filter(
                covered_physician=req.physician,
                date__gte=req.start_date,
                date__lte=req.end_date,
            ).select_related('covering_physician', 'clinic')
        }

        all_dates = []
        d = req.start_date
        year = req.start_date.year
        holidays = get_holidays(year)
        while d <= req.end_date:
            extra = get_extra_workdays(year)
            if is_workday(d, set(holidays), extra):
                all_dates.append(d)
            d += timedelta(days=1)

        day_coverage = []
        uncovered_dates = []
        for day in all_dates:
            assignment = existing_coverage.get(day)
            day_coverage.append({'date': day, 'assignment': assignment})
            if not assignment:
                uncovered_dates.append(day)

        has_full_coverage = len(uncovered_dates) == 0
        has_partial_coverage = bool(existing_coverage) and not has_full_coverage

        enriched.append({
            'request': req,
            'day_coverage': day_coverage,
            'coverage': list(existing_coverage.values()),
            'uncovered_dates': uncovered_dates,
            'has_full_coverage': has_full_coverage,
            'has_partial_coverage': has_partial_coverage,
            'duration': req.duration_days,
        })

    years = list(range(today.year - 1, today.year + 3))

    return render(request, 'coverage_tracker/approved_time_off_coverage.html', {
        'enriched': enriched,
        'year': year,
        'years': years,
        'today': today,
    })


def _build_day_locum_data(all_locums, day, current_covered_physician=None):
    """Helper: for a given date, return each locum with conflict info.

    A "conflict" means the locum is already covering someone ELSE on this day.
    The locum who's already assigned to `current_covered_physician` is NOT a
    conflict — they are the currently-selected assignment and must stay in
    the dropdown so the template can mark them as selected.
    """
    result = []
    for locum in all_locums:
        # Find any assignments for this locum on this day
        conflicting_qs = CoverageAssignment.objects.filter(
            covering_physician=locum, date=day
        ).exclude(covered_physician=None)

        # Ignore the assignment that covers the physician we're editing right now
        if current_covered_physician is not None:
            conflicting_qs = conflicting_qs.exclude(covered_physician=current_covered_physician)

        conflict = conflicting_qs.exists()

        # Always include the locum — show the conflict tag if they're
        # genuinely double-booked on some OTHER physician's coverage.
        result.append({
            'physician': locum,
            'has_conflict': conflict,
        })
    return result


@admin_required
def assign_locum_to_time_off(request, pk):
    """
    Per-day locum assignment for a time-off request.
    Shows each uncovered day with its own locum + clinic selector.
    """
    req = get_object_or_404(TimeOffRequest, pk=pk, status='approved')

    # Build full date list
    all_dates = []
    d = req.start_date
    year = req.start_date.year
    holidays = get_holidays(year)
    while d <= req.end_date:
        if d.weekday() < 5 and not d in holidays:
            all_dates.append(d)
        d += timedelta(days=1)

    # Existing assignments keyed by date
    existing_assignments = {
        a.date: a
        for a in CoverageAssignment.objects.filter(
            covered_physician=req.physician,
            date__gte=req.start_date,
            date__lte=req.end_date,
        ).select_related('covering_physician', 'clinic')
    }

    if request.method == 'POST':
        clinics = {c.pk: c for c in Clinic.objects.filter(is_active=True)}
        locums = {p.pk: p for p in Physician.objects.filter(is_active=True, physician_type='locum')}
        saved = 0
        errors = []

        for day in all_dates:
            date_key = day.strftime('%Y-%m-%d')
            mode = request.POST.get(f'mode_{date_key}', 'locum')    
            locum_id = request.POST.get(f'locum_{date_key}')
            clinic_id = request.POST.get(f'clinic_{date_key}')
            clear = request.POST.get(f'clear_{date_key}')
            hours_raw = request.POST.get(f'hours_{date_key}', '').strip()
            no_cov_reason = request.POST.get(                              # ← NEW
                f'no_coverage_reason_{date_key}', ''
            ).strip()

            existing = existing_assignments.get(day)

            if clear:
                if existing:
                    existing.delete()
                continue


            if mode == 'none':
                if not no_cov_reason:
                    errors.append(
                        f'{day.strftime("%b %d")}: A reason is required when marking '
                        f'a day as "no coverage needed".'
                    )
                    continue
                if not clinic_id:
                    errors.append(
                        f'{day.strftime("%b %d")}: A clinic must still be assigned '
                        f'to the day off, even when no coverage is needed.'
                    )
                    continue
                try:
                    clinic_id_int = int(clinic_id)
                except (ValueError, TypeError):
                    continue
                clinic = clinics.get(clinic_id_int)
                if not clinic:
                    continue

                if existing:
                    existing.no_coverage_needed = True
                    existing.no_coverage_reason = no_cov_reason
                    existing.covering_physician = None
                    existing.clinic = clinic
                    existing.hours = None
                    existing.hourly_rate_override = None
                    existing.save()
                else:
                    CoverageAssignment.objects.create(
                        clinic=clinic,
                        covering_physician=None,
                        covered_physician=req.physician,
                        date=day,
                        hours=None,
                        no_coverage_needed=True,
                        no_coverage_reason=no_cov_reason,
                        notes=f'No coverage needed for time off: {req.start_date} – {req.end_date}',
                    )
                saved += 1
                continue

            



            if locum_id and not clinic_id:
                errors.append(f'{day.strftime("%b %d")}: A locum is selected but no clinic is assigned.')
                continue
            if clinic_id and not locum_id:
                errors.append(f'{day.strftime("%b %d")}: A clinic is selected but no locum is assigned.')
                continue
            if not locum_id and not clinic_id:
                continue  # Both blank — intentionally skipped

            
            try:
                locum_id = int(locum_id)
                clinic_id = int(clinic_id)
            except (ValueError, TypeError):
                continue

            try:
                hours_value = Decimal(hours_raw) if hours_raw else Decimal('8.00')
                if hours_value < 0:
                    hours_value = Decimal('8.00')
            except (InvalidOperation, TypeError):
                hours_value = Decimal('8.00')


            locum = locums.get(locum_id)
            clinic = clinics.get(clinic_id)
            if not locum or not clinic:
                continue

            if existing:
                # Update existing assignment
                existing.covering_physician = locum
                existing.clinic = clinic
                existing.hours = hours_value
                existing.no_coverage_needed = False                     # ← NEW
                existing.no_coverage_reason = '' 
                existing.save()
                saved += 1
            else:
                CoverageAssignment.objects.create(
                    clinic=clinic,
                    covering_physician=locum,
                    covered_physician=req.physician,
                    date=day,
                    hours=hours_value,
                    notes=f'Assigned for time off: {req.start_date} – {req.end_date}',
                )
                saved += 1
        if errors:
            for err in errors:
                messages.error(request, err)
            # ... rebuild day_rows ...
            return redirect('assign_locum_to_time_off', pk=req.pk)


        messages.success(request, f'Coverage updated: {saved} day(s) saved for {req.physician}.')
        return redirect('approved_time_off_coverage')

    # GET — build per-day rows
    all_locums = Physician.objects.filter(is_active=True, physician_type='locum')
    clinics = Clinic.objects.filter(is_active=True)
    physician_clinics = list(req.physician.assigned_clinics.filter(is_active=True))
    default_clinic = physician_clinics[0] if physician_clinics else None



    

    day_rows = []
    for day in all_dates:
        existing = existing_assignments.get(day)
        locum_options = _build_day_locum_data(all_locums, day,current_covered_physician=req.physician)
        day_rows.append({
            'date': day,
            'existing': existing,
            'locum_options': locum_options,
            'is_covered': existing is not None,
        })

    return render(request, 'coverage_tracker/assign_locum.html', {
        'req': req,
        'day_rows': day_rows,
        'clinics': clinics,
        'physician_clinics': physician_clinics,
        'default_clinic': default_clinic,
        'all_dates': all_dates,
    })


@admin_required
def edit_coverage_for_time_off(request, pk):
    """
    Edit existing per-day coverage for an approved time-off request.
    Same form as assign but pre-populated with existing assignments.
    """
    # Reuse the same view — just redirect to assign page
    return redirect('assign_locum_to_time_off', pk=pk)


@admin_required
def delete_time_off_coverage_day(request, assignment_pk):
    """Delete a single day's coverage assignment, redirect back to coverage page."""
    assignment = get_object_or_404(CoverageAssignment, pk=assignment_pk)
    covered = assignment.covered_physician
    assignment.delete()
    if covered:
        messages.success(request, f'Coverage removed for {covered} on {assignment.date}.')
    else:
        messages.success(request, 'Coverage assignment removed.')
    return redirect('approved_time_off_coverage')


@admin_required
def mark_availability(request):
    if request.method == 'POST':
        form = PhysicianAvailabilityForm(request.POST)
        if form.is_valid():
            PhysicianAvailability.objects.update_or_create(
                physician=form.cleaned_data['physician'],
                date=form.cleaned_data['date'],
                defaults={
                    'is_available': form.cleaned_data['is_available'],
                    'notes': form.cleaned_data.get('notes', '')
                }
            )
            messages.success(request, 'Availability updated.')
            return redirect('availability')
    else:
        form = PhysicianAvailabilityForm()
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Mark Locum Availability', 'back_url': 'availability'
    })


@login_required_custom
def psa_coverage_request_view(request):
    year = int(request.GET.get('year', date.today().year))
    physicians = Physician.objects.filter(is_active=True, physician_type='psa').order_by('last_name', 'first_name')
    data = []
    for p in physicians:
        # Days where a locum actually covered this PSA physician
        assignments = CoverageAssignment.objects.filter(
            covered_physician=p, date__year=year, no_coverage_needed=False,
        ).select_related('covering_physician', 'clinic').order_by('date')



        total_hours = sum((a.hours for a in assignments), Decimal('0.00'))
        total_cost = sum((a.cost for a in assignments), Decimal('0.00'))

        data.append({
            'physician': p,
            'assignments': assignments,
            'total': len(assignments),
            'total_hours': total_hours,
            'total_cost': total_cost,
        })
    # Sort: physicians with the most locum-covered days first
    data.sort(key=lambda r: r['total'], reverse=True)

    return render(request, 'coverage_tracker/psa_coverage_requests.html', {
        'data': data,
        'year': year,
    })


@login_required_custom
def add_coverage_request(request):
    from django import forms as dj_forms

    class CoverageRequestForm(dj_forms.Form):
        physician = dj_forms.ModelChoiceField(
            queryset=Physician.objects.filter(is_active=True, physician_type='psa'),
            label='PSA Physician'
        )
        requested_date = dj_forms.DateField(widget=dj_forms.DateInput(attrs={'type': 'date'}))
        status = dj_forms.ChoiceField(choices=CoverageRequest.STATUS_CHOICES, initial='pending')
        notes = dj_forms.CharField(required=False, widget=dj_forms.Textarea(attrs={'rows': 2}))

    if request.method == 'POST':
        form = CoverageRequestForm(request.POST)
        if form.is_valid():
            CoverageRequest.objects.update_or_create(
                physician=form.cleaned_data['physician'],
                requested_date=form.cleaned_data['requested_date'],
                defaults={
                    'status': form.cleaned_data['status'],
                    'notes': form.cleaned_data.get('notes', ''),
                }
            )
            messages.success(request, 'Coverage request recorded.')
            return redirect('psa_coverage_request')
    else:
        form = CoverageRequestForm()
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form,
        'title': 'Add PSA Coverage Request',
        'back_url': 'psa_coverage_request',
    })


@login_required_custom
def delete_coverage_request(request, pk):
    req = get_object_or_404(CoverageRequest, pk=pk)
    req.delete()
    messages.success(request, 'Coverage request deleted.')
    return redirect('psa_coverage_request')


# ─── Auth Views ──────────────────────────────────────────────────────────────

def _post_login_landing(user):
    """Where to send a user after login (or when they hit '/').
    Admins get the dashboard; everyone else goes to the time-off list.
    """
    profile = getattr(user, 'profile', None)
    if profile and profile.is_admin:
        return 'dashboard'
    return 'time_off_list'

def login_view(request):
    if request.user.is_authenticated:
        return redirect(_post_login_landing(request.user))
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        # Ensure profile exists
        UserProfile.objects.get_or_create(user=user)
        next_url = request.GET.get('next') or request.POST.get('next')
        # Honor "next" only if it's set and not the root/dashboard
        # (otherwise non-admins would still get bounced to a forbidden page)
        if next_url and next_url not in ('/', '/dashboard/', '/dashboard'):
            return redirect(next_url)
        return redirect(_post_login_landing(user))
    return render(request, 'coverage_tracker/login.html', {'form': form, 'next': request.GET.get('next', '')})


def logout_view(request):
    logout(request)
    return redirect('/login/')


# ─── User Management (Admin only) ────────────────────────────────────────────

@admin_required
def user_management(request):
    from django.contrib.auth.models import User as DjangoUser
    users = DjangoUser.objects.select_related('profile').order_by('last_name', 'first_name')
    # Ensure profile exists for all users
    for u in users:
        UserProfile.objects.get_or_create(user=u)
    users = DjangoUser.objects.select_related('profile__physician').order_by('last_name', 'first_name')
    return render(request, 'coverage_tracker/user_management.html', {'users': users})


@admin_required
def add_user(request):
    from django.contrib.auth.models import User as DjangoUser
    from django import forms as dj_forms

    class AddUserForm(dj_forms.Form):
        
        username     = dj_forms.CharField(max_length=150, widget=dj_forms.TextInput(attrs={'class': 'form-control'}))
        password     = dj_forms.CharField(widget=dj_forms.PasswordInput(attrs={'class': 'form-control'}), min_length=6)
        role         = dj_forms.ChoiceField(choices=[('physician', 'Physician'),('physician_admin', 'Physician Administrator'), ('admin', 'Administrator')],
                                             widget=dj_forms.Select(attrs={'class': 'form-control'}))
        
        scope        = dj_forms.ChoiceField(
            label='Group',
            choices=[
                ('nroc', 'NROC Physicians'),
                ('psa', 'PSA Physicians'),
                ('all', 'Both NROC and PSA'),
            ],
            initial='nroc',
            widget=dj_forms.Select(attrs={'class': 'form-control'}),
        )

        physician    = dj_forms.ModelChoiceField(
            queryset=Physician.objects.filter(is_active=True).exclude(userprofile__isnull=False),
            required=False,
            empty_label='— Not linked to a physician record —',
            widget=dj_forms.Select(attrs={'class': 'form-control'}),
            help_text='Link this account to a physician record so they can submit time-off requests.'
        )

    if request.method == 'POST':
        form = AddUserForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            if DjangoUser.objects.filter(username=cd['username']).exists():
                form.add_error('username', 'Username already taken.')
            else:
                user = DjangoUser.objects.create_user(
                    username=cd['username'],
                    
                    password=cd['password'],
                    
                )
                UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'role': form.cleaned_data['role'],
                    'scope': form.cleaned_data.get('scope', 'nroc'),
                    'physician': form.cleaned_data.get('physician') or None,
                },
            )
                messages.success(request, f"Account created for {user.get_full_name() or user.username}.")
                return redirect('user_management')
    else:
        form = AddUserForm()

    return render(request, 'coverage_tracker/form_page.html', {
        'form': form,
        'title': 'Add User Account',
        'back_url': 'user_management',
    })


@admin_required
def edit_user(request, pk):
    from django.contrib.auth.models import User as DjangoUser
    from django import forms as dj_forms

    user = get_object_or_404(DjangoUser, pk=pk)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    class EditUserForm(dj_forms.Form):
        
       
        role        = dj_forms.ChoiceField(choices=[('physician', 'Physician'), ('physician_admin', 'Physician Administrator'), ('admin', 'Administrator')],
                                            widget=dj_forms.Select(attrs={'class': 'form-control'}))
        scope   = dj_forms.ChoiceField(
            label='Group',
            choices=[
                ('nroc', 'NROC Physicians'),
                ('psa', 'PSA Physicians'),
                ('all', 'Both NROC and PSA'),
            ],
            initial='nroc',
            widget=dj_forms.Select(attrs={'class': 'form-control'}),
        )
        physician   = dj_forms.ModelChoiceField(
            queryset=Physician.objects.filter(is_active=True),
            required=False,
            empty_label='— Not linked to a physician record —',
            widget=dj_forms.Select(attrs={'class': 'form-control'}),
        )
        new_password = dj_forms.CharField(
            required=False, min_length=6,
            widget=dj_forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank to keep current'}),
            help_text='Only fill this in to change the password.'
        )
        is_active   = dj_forms.BooleanField(required=False, initial=True)

    if request.method == 'POST':
        form = EditUserForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            
            user.is_active  = cd.get('is_active', True)
            if cd.get('new_password'):
                user.set_password(cd['new_password'])
            user.save()
            profile.role      = cd['role']
            profile.scope     = cd.get('scope', 'nroc')
            profile.physician = cd.get('physician')
            profile.save()
            messages.success(request, f"Account updated for {user.get_full_name() or user.username}.")
            return redirect('user_management')
    else:
        form = EditUserForm(initial={
            'first_name': user.first_name,
            'last_name':  user.last_name,
            'email':      user.email,
            'role':       profile.role,
            'scope':      profile.scope,
            'physician':  profile.physician,
            'is_active':  user.is_active,
        })

    return render(request, 'coverage_tracker/form_page.html', {
        'form': form,
        'title': f'Edit Account — {user.get_full_name() or user.username}',
        'back_url': 'user_management',
    })


@admin_required
def delete_user(request, pk):
    from django.contrib.auth.models import User as DjangoUser
    user = get_object_or_404(DjangoUser, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('user_management')
    name = user.get_full_name() or user.username
    user.delete()
    messages.success(request, f"Account for {name} deleted.")
    return redirect('user_management')


# ─── Change Password (all logged-in users) ───────────────────────────────────

@login_required_custom
def change_password(request):
    from django import forms as dj_forms
    from django.contrib.auth import update_session_auth_hash

    class ChangePasswordForm(dj_forms.Form):
        current_password = dj_forms.CharField(
            widget=dj_forms.PasswordInput(attrs={'class': 'form-control'}),
            label='Current Password'
        )
        new_password = dj_forms.CharField(
            widget=dj_forms.PasswordInput(attrs={'class': 'form-control'}),
            label='New Password', min_length=6
        )
        confirm_password = dj_forms.CharField(
            widget=dj_forms.PasswordInput(attrs={'class': 'form-control'}),
            label='Confirm New Password'
        )

        def clean(self):
            cleaned = super().clean()
            if cleaned.get('new_password') != cleaned.get('confirm_password'):
                raise dj_forms.ValidationError('New passwords do not match.')
            return cleaned

    if request.method == 'POST':
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data['current_password']):
                form.add_error('current_password', 'Current password is incorrect.')
            else:
                request.user.set_password(form.cleaned_data['new_password'])
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, 'Password updated successfully.')
                return redirect('dashboard')
    else:
        form = ChangePasswordForm()

    return render(request, 'coverage_tracker/form_page.html', {
        'form': form,
        'title': 'Change Password',
        'back_url': 'dashboard',
    })

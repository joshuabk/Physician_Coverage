from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import datetime
import calendar

from .models import Physician, Clinic, TimeOffRequest, CoverageAssignment, PhysicianAvailability
from .forms import (
    TimeOffRequestForm, CoverageAssignmentForm,
    PhysicianAvailabilityForm, PhysicianForm, ClinicForm
)

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



def dashboard(request):
    today = date.today()
    year = int(request.GET.get('year', today.year))

    regular_physicians = Physician.objects.filter(is_active=True, physician_type='regular')
    locum_physicians = Physician.objects.filter(is_active=True, physician_type='locum')

    todays_coverage = CoverageAssignment.objects.filter(date=today).select_related(
        'clinic', 'covering_physician', 'covered_physician'
    )
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
    total_locum_days = 0
    for p in locum_physicians:
        days = p.total_coverage_days(year)
        cost = p.total_coverage_cost(year)
        total_locum_cost += cost
        total_locum_days += days
        locum_summaries.append({
            'physician': p,
            'days': days,
            'cost': cost,
        })

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
        'locum_summaries': locum_summaries,
        'total_locum_cost': total_locum_cost,
        'total_locum_days': total_locum_days,
    }
    return render(request, 'coverage_tracker/dashboard.html', context)


def physician_list(request):
    physician_type = request.GET.get('type', 'regular')
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
        else:
            summaries.append({
                'physician': p,
                'days': p.total_coverage_days(year),
                'cost': p.total_coverage_cost(year),
                'clinics': [],
            })

    return render(request, 'coverage_tracker/physician_list.html', {
        'summaries': summaries,
        'year': year,
        'physician_type': physician_type,
    })


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

    context = {
        'physician': physician,
        'year': year,
        'days_taken': physician.days_taken(year) if physician.is_regular else None,
        'days_remaining': physician.days_remaining(year) if physician.is_regular else None,
        'days_pending': physician.days_pending(year) if physician.is_regular else None,
        'coverage_days': physician.total_coverage_days(year) if physician.is_locum else None,
        'coverage_cost': physician.total_coverage_cost(year) if physician.is_locum else None,
        'assigned_clinics': physician.assigned_clinics.all() if physician.is_regular else [],
        'time_off_requests': time_off_requests,
        'coverage': coverage[:20],
        'coverage_this_year': coverage_this_year,
        'availability': availability,
    }
    return render(request, 'coverage_tracker/physician_detail.html', context)


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


def time_off_list(request):
    status = request.GET.get('status', '')
    physician_id = request.GET.get('physician', '')
    qs = TimeOffRequest.objects.select_related('physician').order_by('-start_date')
    if status:
        qs = qs.filter(status=status)
    if physician_id:
        qs = qs.filter(physician_id=physician_id)
    physicians = Physician.objects.filter(is_active=True, physician_type='regular')

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
            locum_names = list({a.covering_physician for a in assignments})
            coverage = locum_names
        enriched_requests.append({
            'req': req,
            'coverage': coverage,
            'coverage_status': coverage_status,
        })

    return render(request, 'coverage_tracker/time_off_list.html', {
        'enriched_requests': enriched_requests,
        'physicians': physicians,
        'status_filter': status,
        'physician_filter': physician_id,
    })


def add_time_off(request):
    if request.method == 'POST':
        form = TimeOffRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Time off request submitted.')
            return redirect('time_off_list')
    else:
        physician_id = request.GET.get('physician')
        initial = {'physician': physician_id} if physician_id else {}
        form = TimeOffRequestForm(initial=initial)
    return render(request, 'coverage_tracker/form_page.html', {
        'form': form, 'title': 'Request Time Off', 'back_url': 'time_off_list'
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


def approve_time_off(request, pk):
    req = get_object_or_404(TimeOffRequest, pk=pk)
    req.status = 'approved'
    req.save()
    messages.success(request, f'Approved time off for {req.physician}.')
    return redirect('time_off_list')


def deny_time_off(request, pk):
    req = get_object_or_404(TimeOffRequest, pk=pk)
    req.status = 'denied'
    req.save()
    messages.warning(request, f'Denied time off for {req.physician}.')
    return redirect('time_off_list')


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
            clinic=clinic, date=view_date
        ).select_related('covering_physician', 'covered_physician')
        regular_out = [p for p in clinic.regular_physicians.all() if p.id in out_ids]
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


def delete_coverage(request, pk):
    assignment = get_object_or_404(CoverageAssignment, pk=pk)
    date_str = str(assignment.date)
    assignment.delete()
    messages.success(request, 'Coverage assignment removed.')
    return redirect(f'/clinics/?date={date_str}')


def locum_costs(request):
    year = int(request.GET.get('year', date.today().year))
    month = request.GET.get('month', '')

    assignments = CoverageAssignment.objects.filter(
        date__year=year
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
    grand_days = 0

    for p in locums:
        yr_assignments = [a for a in assignments if a.covering_physician_id == p.id]
        days = len(yr_assignments)
        cost = sum(a.cost for a in yr_assignments)
        grand_total += cost
        grand_days += days
        if days > 0 or True:  # show all locums
            locum_data.append({
                'physician': p,
                'days': days,
                'cost': cost,
                'standard_rate': p.daily_rate,
            })

    # Monthly breakdown
    monthly_totals = {}
    for a in CoverageAssignment.objects.filter(date__year=year).select_related('covering_physician'):
        m = a.date.month
        if m not in monthly_totals:
            monthly_totals[m] = {'days': 0, 'cost': Decimal('0.00')}
        monthly_totals[m]['days'] += 1
        monthly_totals[m]['cost'] += a.cost

    months = []
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    for i in range(1, 13):
        d = monthly_totals.get(i, {'days': 0, 'cost': Decimal('0.00')})
        months.append({'num': i, 'name': month_names[i-1], **d})
    #num_assigned = 0
    num_assigned = sum([1 for s in locum_data if s['days'] > 0])
    print([1 for s in locum_data if s['days'] > 0])
    


    context = {
        'year': year,
        'month_filter': month,
        'assignments': assignments,
        'locum_data': locum_data,
        'months': months,
        'grand_total': grand_total,
        'grand_days': grand_days,
        'assigned_count': num_assigned,
        'years': [2023, 2024, 2025, 2026, 2027],
    }
    return render(request, 'coverage_tracker/locum_costs.html', context)


def availability_view(request):
    selected_date = request.GET.get('date', str(date.today()))
    try:
        view_date = datetime.datetime.strptime(selected_date, '%Y-%m-%d').date()
    except ValueError:
        view_date = date.today()

    week_start = view_date - timedelta(days=view_date.weekday())
    calendar_days = [week_start + timedelta(days=i) for i in range(14)]

    locums = Physician.objects.filter(is_active=True, physician_type='locum')

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

    # Also mark days locums are already assigned
    assigned_set = set()
    for a in CoverageAssignment.objects.filter(
        date__gte=calendar_days[0], date__lte=calendar_days[-1]
    ):
        assigned_set.add((a.covering_physician_id, a.date))

    grid = []
    for p in locums:
        row = []
        for d in calendar_days:
            if (p.id, d) in assigned_set:
                row.append('assigned')
            elif (p.id, d) in off_set:
                row.append('off')
            else:
                row.append('available')
        grid.append({'physician': p, 'days': row})

    return render(request, 'coverage_tracker/availability.html', {
        'grid': grid,
        'calendar_days': calendar_days,
        'view_date': view_date,
        'today': date.today(),
    })


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
            if d.weekday()<5 and not d in holidays:
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


def _build_day_locum_data(all_locums, day):
    """Helper: for a given date, return each locum with conflict info."""
    result = []
    for locum in all_locums:
        conflict = CoverageAssignment.objects.filter(
            covering_physician=locum, date=day
        ).exclude(covered_physician=None).exists()
        result.append({
            'physician': locum,
            'has_conflict': conflict,
        })
    return result


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
            locum_id = request.POST.get(f'locum_{date_key}')
            clinic_id = request.POST.get(f'clinic_{date_key}')
            clear = request.POST.get(f'clear_{date_key}')

            existing = existing_assignments.get(day)

            if clear:
                if existing:
                    existing.delete()
                continue

            if not locum_id or not clinic_id:
                continue  # Skip days left blank

            try:
                locum_id = int(locum_id)
                clinic_id = int(clinic_id)
            except (ValueError, TypeError):
                continue

            locum = locums.get(locum_id)
            clinic = clinics.get(clinic_id)
            if not locum or not clinic:
                continue

            if existing:
                # Update existing assignment
                existing.covering_physician = locum
                existing.clinic = clinic
                existing.save()
                saved += 1
            else:
                CoverageAssignment.objects.create(
                    clinic=clinic,
                    covering_physician=locum,
                    covered_physician=req.physician,
                    date=day,
                    notes=f'Assigned for time off: {req.start_date} – {req.end_date}',
                )
                saved += 1

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
        locum_options = _build_day_locum_data(all_locums, day)
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


def edit_coverage_for_time_off(request, pk):
    """
    Edit existing per-day coverage for an approved time-off request.
    Same form as assign but pre-populated with existing assignments.
    """
    # Reuse the same view — just redirect to assign page
    return redirect('assign_locum_to_time_off', pk=pk)


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

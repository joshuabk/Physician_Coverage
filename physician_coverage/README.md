# Physician Coverage Tracker

A Django app for tracking physician time off, vacation balances, clinic coverage, and availability.

## Features

- **Physician Management** — track each physician's vacation allocation, days used, and days remaining
- **Time Off Requests** — submit, approve/deny, and filter by physician or status
- **Clinic Coverage** — see which physician is covering each clinic on any given date
- **Availability Grid** — two-week calendar view showing who is available vs. on leave
- **Dashboard** — today's coverage, who's out, pending requests, and vacation balances at a glance

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run migrations
```bash
python manage.py migrate
```

### 3. Create a superuser (for admin access)
```bash
python manage.py createsuperuser
```

### 4. Start the development server
```bash
python manage.py runserver
```

Visit http://127.0.0.1:8000/ for the app, or http://127.0.0.1:8000/admin/ for the Django admin.

## Data Model

### Physician
- Name, email, specialty
- `total_vacation_days` — annual allocation (default: 20)
- Methods: `days_taken(year)`, `days_remaining(year)`, `days_pending(year)`

### TimeOffRequest
- Links to a physician
- Date range, type (vacation / sick / conference / personal / other)
- Status: pending → approved / denied / cancelled

### Clinic
- Name, location, specialty

### CoverageAssignment
- Links a covering physician to a clinic on a specific date
- Optionally links the physician being covered

### PhysicianAvailability
- Manual availability overrides per physician per date

## Notes

- Change `SECRET_KEY` in `settings.py` before deploying to production
- Set `DEBUG = False` and configure `ALLOWED_HOSTS` for production
- Default database is SQLite — swap for PostgreSQL in production via `DATABASES` setting

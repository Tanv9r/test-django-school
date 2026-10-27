# Hospital Management System (Django + SQLite)

A responsive, database-driven hospital management system built with **Django**, **SQLite**, **Bootstrap 5**, **Bootstrap Icons**, **Chart.js** and plain JavaScript. It has two separate interfaces:

- **Staff workspace** (`/dashboard/`): light theme with navy navigation, for daily operations.
- **Custom admin panel** (`/admin-panel/`): dark gradient theme, for system-wide management. Django's built-in admin is not used.

> ⚠️ This is a **software prototype**. It is not a certified clinical system and must not be used with real patient data without a proper security, privacy, legal and clinical review.

---

## Features

| Module | Highlights |
|---|---|
| Authentication & roles | Django auth, PBKDF2 password hashing, six roles (Administrator, Doctor, Nurse, Receptionist, Pharmacist, Accountant), role-based redirect after login, profile and password pages, login auditing |
| Dashboards | Role-specific staff dashboard and a separate dark admin control center; every number is computed from the database; Chart.js charts for revenue, appointment status, bed occupancy, daily appointments and users by role |
| Patients | Auto-generated IDs (`PT-000001`), validation, duplicate detection, search/filter/pagination, archive/restore, tabs for appointment, admission, medical, prescription and invoice history |
| Doctors & departments | Profiles, specializations, fees, slot length, weekly working hours, login linking, configurable departments |
| Appointments | Booking with server-side availability and conflict checks (form, transaction and DB constraint), live free-slot picker, reschedule, status workflow, table and monthly calendar views |
| Medical records & prescriptions | Records entered by the treating doctor, amendments tracked in the audit log, prescriptions linked to inventory, atomic dispensing by the pharmacy, printable prescriptions |
| Admissions & beds | Admit/discharge in transactions, beds locked and released automatically, one active admission per bed/patient (DB constraints), live bed board, rooms/beds/room-type management, nursing tasks |
| Pharmacy | Inventory with categories, batches and expiry dates; low-stock and expiry alerts; every stock change goes through a validated transaction log; negative stock is impossible |
| Billing | Invoices with consultation/room/other charges, discounts, `Decimal` arithmetic, payments with configurable methods, Unpaid / Partially paid / Paid / Cancelled statuses, printable invoices |
| Staff | Staff directory with employment profiles kept separate from login credentials |
| Reports | Eight reports with date filters, charts, CSV export (formula-injection safe) and print layouts, restricted by role |
| Admin panel | Users & roles, password resets, activation, departments, room types, payment methods, medicine categories, hospital settings, full audit log |
| UX | Global search, notification bell built from live data, breadcrumbs, collapsible mobile sidebar, Django messages, confirmation modals, loading states, empty states |

### Role permissions (summary)

| Capability | Admin | Doctor | Nurse | Receptionist | Pharmacist | Accountant |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Patients: view | all | assigned | assigned | all | – | all (no clinical info) |
| Patients: register/edit | ✔ | – | – | ✔ | – | – |
| Appointments | manage | own (status) | – | manage | – | – |
| Medical records | view | create/edit own | view (assigned) | – | – | – |
| Prescriptions | view | write | view | – | dispense | – |
| Admissions | manage | own, discharge | assigned | manage | – | – |
| Pharmacy inventory | manage | view | – | – | manage | – |
| Billing | ✔ | – | – | – | – | ✔ |
| Admin panel | ✔ | – | – | – | – | – |

All rules live in `accounts/permissions.py` and are enforced **on the server** for every view. Hidden buttons are only a convenience. Row-level rules (for example, "doctors only see their own patients") are in the `visible_*` selectors.

---

## Project structure

```
config/            Django settings, URLs, WSGI/ASGI
core/              Shared models (AuditLog, HospitalSettings), form styling, template tags,
                   error views, test factories, seed_demo command
accounts/          Custom User with roles, capability map, login/profile/password views
patients/          Patient registration, profiles, visibility selector
doctors/           Doctors, departments, weekly availability
appointments/      Scheduling services (availability, conflicts, slots), list/calendar views
medical_records/   Medical records, prescriptions, dispensing service
admissions/        Room types, rooms, beds, admissions, nursing tasks
pharmacy/          Medicines, categories, stock transactions
billing/           Invoices, items, payments, payment methods
staff/             Staff directory (employment profiles)
dashboard/         Staff dashboard, statistics, notifications, global search, reports
adminpanel/        Custom dark admin panel
templates/         Shared templates: layouts/, components/, one folder per app, 403/404/500
static/            css/ (base, staff, admin), js/ (app, charts, appointments, invoice),
                   vendor/ (Bootstrap, Bootstrap Icons, Chart.js — bundled for offline use)
```

Business rules that touch several tables (booking, admitting, discharging, dispensing, payments) live in each app's `services.py` and run inside database transactions.

---

## Getting started

Requirements: **Python 3.11+** (tested with Python 3.14 and Django 6.1). No MySQL or PostgreSQL is needed.

### 1. Create and activate a virtual environment

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the project

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

Edit `.env`:

- `DJANGO_SECRET_KEY`: generate one with `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DJANGO_DEBUG=True` for local development
- `HMS_TIME_ZONE`: your local IANA time zone, e.g. `Europe/London`, `Asia/Dhaka`, `America/New_York`. All appointment times are stored in UTC and shown in this zone.

`.env` is git-ignored. Never commit it.

### 4. Run database migrations

```bash
python manage.py migrate
```

This creates `db.sqlite3` with default departments (Cardiology, Neurology, Orthopedics, Pediatrics, General Medicine, Gynecology, Emergency), payment methods (Cash, Card, Bank Transfer), medicine categories and room types. All of these can be changed later in the admin panel.

### 5. Create the first administrator

```bash
python manage.py createsuperuser
```

Superusers always get the **Administrator** role. You can create other users and assign roles from **Admin panel → Users & roles**.

### 6. Start the development server

```bash
python manage.py runserver
```

### 7. Open the application

Go to **http://127.0.0.1:8000/** and sign in. Administrators land on the dark admin panel (`/admin-panel/`). All other roles land on the staff dashboard (`/dashboard/`). Administrators can switch between the two from the user menu.

---

## Optional: demo data

For testing or recording a tutorial, you can load demo data into a **separate** database file so it never mixes with real records:

```bash
# Windows (PowerShell)
$env:HMS_DB_PATH="demo.sqlite3"
python manage.py migrate
python manage.py seed_demo
python manage.py runserver

# macOS / Linux
HMS_DB_PATH=demo.sqlite3 python manage.py migrate
HMS_DB_PATH=demo.sqlite3 python manage.py seed_demo
HMS_DB_PATH=demo.sqlite3 python manage.py runserver
```

The command creates doctors, 30 patients, about two months of appointments, admissions, stock, invoices and payments. Demo people use e-mail addresses on `demo.hms.local`, and the command refuses to run if the database already contains non-demo patients. All demo logins use the password `Demo@12345` (or set your own with `--password`):

| Username | Role |
|---|---|
| `demo_admin` | Administrator |
| `demo_dr_carter` (also `demo_dr_singh`, `demo_dr_lopez`) | Doctor |
| `demo_nurse` (also `demo_nurse2`) | Nurse |
| `demo_reception` | Receptionist |
| `demo_pharmacist` | Pharmacist |
| `demo_accountant` | Accountant |

Clinical text in the demo data is placeholder content, not medical advice.

---

## Running tests and checks

```bash
python manage.py test          # 79 automated tests
python manage.py check         # Django system checks
python manage.py check --deploy   # production hardening hints (run with DJANGO_DEBUG=False)
```

The tests cover authentication and role permissions, patient validation and visibility, appointment conflicts and availability, bed assignment and release, stock validation and atomic dispensing, invoice calculations and payment status rules, restricted access to medical records, dashboard statistics, reports and CSV export.

---

## Production notes

- Set `DJANGO_DEBUG=False`, a strong `DJANGO_SECRET_KEY`, and real `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Serve over HTTPS. Secure cookies are on by default when debug is off. Also set `DJANGO_SECURE_SSL_REDIRECT=True` and `DJANGO_HSTS_SECONDS`.
- Run `python manage.py collectstatic` and serve `staticfiles/` with your web server (or WhiteNoise).
- Use a WSGI server such as Gunicorn or Waitress instead of `runserver`.
- Store the SQLite file outside any publicly served directory and back it up regularly. For many simultaneous users, move to PostgreSQL.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ImproperlyConfigured: DJANGO_SECRET_KEY is not set` | Create `.env` from `.env.example` and set the key, or set `DJANGO_DEBUG=True`. |
| `ModuleNotFoundError: No module named 'django'` | Activate the virtual environment, then `pip install -r requirements.txt`. |
| `no such table: ...` | Run `python manage.py migrate`. |
| `ZoneInfoNotFoundError` for your time zone | `pip install tzdata` (included in requirements). Use a valid IANA name. |
| Pages look unstyled | Keep `DJANGO_DEBUG=True` locally (runserver only serves static files in debug mode) or run `collectstatic`. |
| CSRF verification failed on login | Use the same host you configured (`127.0.0.1` vs `localhost`). Behind HTTPS, set `DJANGO_CSRF_TRUSTED_ORIGINS`. |
| `database is locked` | SQLite allows one writer at a time. The app uses WAL mode, short transactions and a 20 s timeout. Close other tools holding the DB file open. |
| "Access denied" (403) | Your role lacks permission for that page. An administrator can change your role. |
| Doctor can't write records | The doctor's login must be linked to a doctor profile (Doctors → Edit → *Login account*). |
| Can't book an appointment | Check the doctor's weekly working hours, that the time is in the future, and that the slot is free. |

---

## Known limitations

- No e-mail or SMS notifications. Password resets are done by administrators.
- No login rate limiting. Failed sign-ins are audited and shown to admins; add a package such as `django-axes` for lockouts.
- File uploads (lab reports, scans) are not supported.
- SQLite suits single-site and demo use. Heavy concurrent use needs PostgreSQL.

# 🔧 Uncle Kop's Workshop — Django Management System

> *Raise the Standard. Every repair deserves better.*

A full-featured auto shop management system built with Django, covering repair orders, customers, vehicles, invoicing, inventory, and appointments.

---

## 📁 Project Structure

```
uncle_kops_workshop/
├── manage.py
├── requirements.txt
│
├── uncle_kops_workshop/          ← Django project config
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── workshop/                     ← Main app
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py                 ← All database models
│   ├── views.py                  ← All views / logic
│   ├── forms.py                  ← All forms
│   ├── urls.py                   ← URL routing
│   └── admin.py                  ← Django admin config
│
├── templates/
│   └── workshop/
│       ├── base.html             ← Sidebar layout & styles
│       ├── login.html
│       ├── dashboard.html
│       ├── customer_list.html
│       ├── customer_form.html
│       ├── vehicle_list.html
│       ├── vehicle_form.html
│       ├── repair_order_list.html
│       ├── repair_order_detail.html
│       ├── repair_order_form.html
│       ├── invoice_list.html
│       ├── invoice_detail.html   (extend from invoice_form)
│       ├── invoice_form.html
│       ├── appointment_list.html
│       ├── appointment_form.html
│       ├── parts_list.html
│       ├── part_form.html
│       ├── service_list.html
│       ├── service_form.html
│       └── line_item_form.html
│
├── static/
│   ├── css/
│   └── js/
└── media/
```

---

## 🚀 Step-by-Step Setup

### Step 1 — Prerequisites

Make sure you have Python 3.10+ installed:
```bash
python --version
```

### Step 2 — Create & Activate a Virtual Environment

```bash
# Create the virtual environment
python -m venv venv

# Activate it:
# On Windows:
venv\Scripts\activate

# On macOS / Linux:
source venv/bin/activate
```

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure Environment

Copy `.env.example` to `.env` and set local database credentials, a development `DJANGO_SECRET_KEY`, a valid base64-encoded 32-byte `ENCRYPTION_KEY`, and `PUBLIC_BASE_URL`. Set `DJANGO_DEBUG=True` only for local development. The settings default to `DEBUG=False` when it is omitted.

### Step 5 — Configure MySQL and Run Migrations

The development configuration uses MySQL. Create the configured database and database user before migrating. The project migrations are included in the repository; apply them with:
```bash
python manage.py migrate
```

### Step 6 — Create a Superuser (Admin Account)

```bash
python manage.py createsuperuser
# Enter: username, email (optional), password
```

### Step 7 — Start the Development Server

```bash
python manage.py runserver
```

Then open your browser at: **http://127.0.0.1:8000**

---

## 🖥️ Pages & URLs

| URL                          | Description                        |
|------------------------------|------------------------------------|
| `/`                          | Dashboard (stats overview)         |
| `/login/`                    | Login page                         |
| `/customers/`                | Customer list                      |
| `/customers/new/`            | Add customer                       |
| `/customers/<id>/`           | Customer detail                    |
| `/vehicles/`                 | Vehicle list                       |
| `/vehicles/new/`             | Add vehicle                        |
| `/repairs/`                  | Repair order list (with filters)   |
| `/repairs/new/`              | Create repair order                |
| `/repairs/<id>/`             | Repair order detail + line items   |
| `/repairs/<id>/labor/`       | Add labor line                     |
| `/repairs/<id>/parts/`       | Add parts line                     |
| `/invoices/`                 | Invoice list                       |
| `/invoices/new/`             | Create invoice                     |
| `/appointments/`             | Appointment calendar list          |
| `/appointments/new/`         | Book appointment                   |
| `/parts/`                    | Parts inventory                    |
| `/parts/new/`                | Add part                           |
| `/services/`                 | Service catalogue                  |
| `/admin/`                    | Django admin panel                 |

---

## 🗄️ Database Models

| Model          | Description                                    |
|----------------|------------------------------------------------|
| `Customer`     | Name, email, phone, address                    |
| `Vehicle`      | Linked to customer; make, model, year, VIN     |
| `RepairOrder`  | Core workflow: status, tech, labor & parts     |
| `LaborLine`    | Labor line items on a repair order             |
| `PartsLine`    | Parts line items on a repair order             |
| `Invoice`      | Billing with tax, discount, payment tracking   |
| `Appointment`  | Booking schedule linked to customer/vehicle    |
| `Part`         | Inventory: stock, pricing, reorder levels      |
| `ServiceItem`  | Labour catalogue with default hours/rate       |

---

## ⚙️ Key Features

- **Dashboard** — Real-time stats: open ROs, ready for pickup, today's appointments, low stock alerts
- **Repair Orders** — Full lifecycle: Pending → In Progress → Waiting → Ready → Completed
- **Line Items** — Add labor and parts directly to each repair order with auto-calculated totals
- **Invoicing** — VAT/tax support, discount field, payment status tracking (Unpaid/Partial/Paid)
- **Inventory** — Low stock warnings, reorder levels, supplier tracking
- **Appointments** — Book, confirm, and manage customer appointments
- **Search** — Search customers by name/email/phone; vehicles by plate/VIN
- **Django Admin** — Full admin panel at `/admin/` for superusers

---

## 🎨 UI Theme

- **Dark industrial theme** inspired by a real workshop aesthetic
- **Bebas Neue** display font + **Barlow** body font
- Orange accent color (`#E8500A`) — Uncle Kop's brand
- Color-coded status badges across all list views
- Sticky sidebar navigation with section grouping

---

## 🔒 Production Checklist

Before going live:
1. Set `DJANGO_DEBUG=False`, provide unique `DJANGO_SECRET_KEY` and base64-encoded 32-byte `ENCRYPTION_KEY` values, set `DJANGO_ALLOWED_HOSTS` to a comma-separated list of production hostnames, and set `PUBLIC_BASE_URL` to the HTTPS public application URL used in verification and password-reset emails.
2. Set `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and `DB_HOST`; `DB_PORT` is optional and defaults to `3306`.
3. Run `python manage.py check --deploy` and address its warnings.
4. Run `python manage.py collectstatic`.
5. Set up a production WSGI server and HTTPS reverse proxy.

---

## 📞 Support

Uncle Kop's Workshop — Bloemfontein, South Africa  
Built with Django 5.2 LTS | South African VAT (15%) pre-configured

## Operations and Recovery

### Test and migration checks

Run these commands from PowerShell with the project virtual environment active (or use the explicit `.venv` executable shown):

```powershell
$env:DJANGO_DEBUG = 'True'
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test --keepdb
```

`migrate --check` reports whether migrations are pending; it does not apply them.
The Django suite includes a regression test that inserts an overpayment directly
in its isolated test database, simulates a stale invoice status, and verifies
the application flags the mismatch and rejects further payment attempts.

### End-to-end browser tests

The Playwright suite checks that the admin, mechanic, and customer QA accounts
reach their role-specific dashboards, that key admin pages load and mechanic
access to admin-only creation pages is denied, then exercises creating a
customer, adding a vehicle, and opening a repair order in the browser. It writes
records, so use only a disposable, isolated QA database with the dedicated QA
accounts; never point it at production. The test does not create or reset QA
accounts.

Install Node.js and the project test dependency, install Chromium, and start the
Django application against the isolated QA database in a separate terminal:

```powershell
npm install
npx playwright install chromium
$env:QA_ACCEPTANCE_PASSWORD = 'your-qa-account-password'
npm run test:e2e
```

By default, tests connect to `http://127.0.0.1:8000`. To use another isolated
QA host, set `E2E_BASE_URL` and explicitly set `E2E_ALLOW_REMOTE=true`. QA
usernames default to `qa_acceptance_admin`, `qa_acceptance_mechanic`, and
`qa_acceptance_customer`; override them with `QA_ADMIN_USERNAME`,
`QA_MECHANIC_USERNAME`, and `QA_CUSTOMER_USERNAME` if needed. Never supply
production credentials or enable remote testing against production.

### MySQL and media backups

Database migration `0023_database_wide_audit_triggers` installs MySQL insert,
update, and delete triggers on every base table except `workshop_auditlog`,
which is the append-only audit sink. Database-level events are written to that
table with the source table, operation, primary key, MySQL account, and
connection ID; row contents are not copied. Run
`python manage.py verify_audit_triggers` after deployment to check coverage.
The migration database account needs permission to create and drop triggers.
When MySQL binary logging is enabled, a database administrator must also
temporarily enable `log_bin_trust_function_creators` while running migrations
that create triggers. Re-run `python manage.py migrate` afterward; trigger
definitions remain installed when the setting is turned off again.

Before a production migration or release, take a consistent MySQL dump and back up uploaded documents. Keep backups encrypted, off the application host, access-controlled, and subject to a documented retention period. `mysqldump` prompts for the database password instead of placing it in command history:

```powershell
$backupDirectory = Join-Path $PWD 'backups'
New-Item -ItemType Directory -Force $backupDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
mysqldump "--host=$env:DB_HOST" "--port=$env:DB_PORT" "--user=$env:DB_USER" --password `
	--single-transaction --hex-blob --routines --triggers --databases $env:DB_NAME `
	"--result-file=$backupDirectory\workshop-$stamp.sql"
robocopy .\media "$backupDirectory\media-$stamp" /E /COPY:DAT /R:2 /W:2
```

Restore only into an isolated recovery database first. In MySQL Workbench, use **Server > Data Import**, select the dump file, choose the intended recovery schema, and start the import. Restore the matching media backup as well, then verify record counts, document downloads, and encrypted customer fields before considering recovery complete. Keep the production `ENCRYPTION_KEY` in a separate secrets manager backup: without the matching key, encrypted personal data cannot be decrypted. Do not overwrite production during a recovery drill.

No production backup or restore drill has been run from this workspace; schedule and record one before launch.

### Production deployment

Use a supported Django release; this project targets the Django 5.2 LTS series. Store `DJANGO_SECRET_KEY`, `ENCRYPTION_KEY`, MySQL credentials, SMTP credentials, and host configuration in the deployment secret store, not in source control. Set `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `PUBLIC_BASE_URL` (HTTPS), `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and an appropriate `DB_CONN_MAX_AGE`. The default production connection age is 60 seconds; size it against the database connection limit and number of WSGI workers. `DJANGO_LOG_LEVEL` controls console logging.

After taking and verifying a backup, use the deployment environment's Python executable:

```powershell
python manage.py check --deploy
python manage.py migrate --check
python manage.py migrate
python manage.py collectstatic --noinput
waitress-serve --listen=127.0.0.1:8000 uncle_kops_workshop.wsgi:application
```

Run Waitress behind a maintained HTTPS reverse proxy or managed load balancer; do not expose the WSGI listener directly to the public internet. The proxy must remove client-supplied forwarding headers and set the trusted HTTPS forwarding header correctly. Serve collected static files from `STATIC_ROOT`. Do not publish `MEDIA_ROOT` as a public static directory: repair-document downloads must continue through the permission-checking Django view. `runserver` is for development only. Configure host-level log collection/retention and monitor application, proxy, database, disk, and SMTP failures.

The commands above are a deployment runbook, not evidence that a production host, TLS proxy, backup target, or production secrets have been configured.

## Acceptance Status

Latest local verification on 2026-10-06:

- `manage.py check` reported no issues.
- `makemigrations --check --dry-run` detected no model changes, and `migrate --check` reported no pending migrations.
- The Django 5.2.17 LTS project test suite passed: 133 tests. Six date-dependent test cases were corrected to use dates relative to the current date; currency-formatting and customer-visible repair-document tests were also added. The latest full suite passed after these changes.

Additional acceptance evidence recorded on 2026-10-01 (not rerun as part of the latest local verification):

- The configured MySQL target accepted a read-only query and reported no unapplied migrations.
- The configured SMTP server accepted a one-time test message addressed to its configured sender. Inbox placement was not verified.
- Search, role-scoping, workflow decisions, inventory constraints, estimates, payments, collection records, uploads, and reporting have automated test coverage.
- The admin, mechanic, and customer QA accounts reached their expected dashboards in a browser; all three dashboards and the report page fit tested 390px/desktop widths with no console errors or failed requests.
- Waitress served the login page locally with HTTP 200 and no failed requests.

Still requiring staging/production evidence before claiming full acceptance:

- A complete browser-driven customer-to-admin-to-mechanic-to-customer journey through approvals, invoicing, payment, and collection. Responsive checks covered the dashboards and reports, not every route or device size.
- A scheduled backup and a successful restore drill covering both MySQL and uploaded media, with the matching encryption key.
- Production hosting, reverse-proxy/TLS behavior, static serving, logging retention, and monitoring.
- Live email arrival in the intended inbox and retry/failure behavior under SMTP outages.
- Payment-gateway processing and verified callbacks; the project does not claim a live gateway integration.
- Load testing with representative anonymized workshop data and operational recovery procedures.

The project is integrated on one Django/MySQL application, but the acceptance checklist is not fully signed off until the staging/production items above are exercised and recorded.

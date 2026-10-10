# Uncle Kop's Workshop — Final Project Report

**Report date:** 6 October 2026

**Project:** Uncle Kop's Workshop management system

**Technology:** Django 5.2, Python, and MySQL

## Executive summary

Uncle Kop's Workshop is a web application intended to support the day-to-day
administration of an automotive repair workshop. Its core scope includes
customers and vehicles, appointments, repair orders, labor and parts, estimates,
invoices, payments, inventory, reporting, and role-specific access for
administrators, mechanics, and customers.

The repository contains a substantial implementation, automated tests,
operational documentation, and a browser acceptance script. The current local
technical checks are positive: Django's system check and migration checks
passed, and the full 133-test suite passed on 6 October 2026 after correcting
six date-dependent test cases and adding currency-formatting coverage.

The available evidence does **not** include a completed usability study,
measured task times, user error rates, satisfaction scores, or a recorded
demonstration. These are outstanding project deliverables. No participant
feedback or usability results are invented in this report.

## 1. Project purpose and scope

The project aims to bring common workshop workflows into one application:

- Maintain customer and vehicle records.
- Schedule and manage appointments.
- Create repair orders and track their status and assigned mechanic.
- Record repair estimates, labor, and parts.
- Manage service and inventory catalogues, including low-stock visibility.
- Create invoices, calculate tax and discounts, record payments, and track
  outstanding balances.
- Provide dashboards and operational reports appropriate to user roles.
- Protect customer information and restrict access to role-sensitive records.

The implementation uses a single Django application and a MySQL database.
Django templates provide the interface, while Django forms, views, models,
authentication, and migrations implement the application behavior.

## 2. Methods

This report is based on inspection of the current project documentation,
application routes and templates, Django models and settings, automated tests,
and the browser acceptance script. It also includes a fresh local verification
run performed on 6 October 2026 using the project's `.venv` Python executable.

The verification commands were:

```powershell
$env:DJANGO_DEBUG = 'True'
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test --keepdb
```

This is a code-and-test review, not a substitute for observing representative
workshop staff or customers using the application. No in-person or remote
usability sessions, participant recruitment, task timing, or satisfaction
survey were evidenced in the repository at the time of writing.

## 3. Implementation and technical decisions

### Application structure

The project follows Django's model-view-template approach. The `workshop` app
contains domain models, forms, views, routing, administration, and tests; the
project package configures the application and deployment settings. Database
changes are represented by Django migrations.

### Workflow and data

The application models customer and vehicle records, repair orders and their
work lines, appointments, invoices and payments, inventory, estimates,
notifications, audit records, and repair documents. Role-specific dashboards
and access rules support administrator, mechanic, and customer workflows.

### Security and deployment choices

The settings distinguish development from production configuration, require
production secrets and host configuration, and configure secure cookies and
HTTPS-related behavior when debug mode is disabled. The project documents
MySQL, Waitress, a TLS-terminating reverse proxy, secret storage, backups, and
the requirement that repair-document downloads retain permission checks.

These are implementation and runbook choices, not evidence that a production
environment has been deployed or that its security controls have been
independently assessed.

### Interface decisions

The templates use a dark, industrial visual theme with orange accents,
role-specific dashboards, status indicators, navigation, and workflow
shortcuts. The current implementation also includes responsive layout work.
However, responsive checks described in the README are limited to selected
dashboards and reports; they do not establish usability across every route,
device, or assistive technology.

## 4. Results

### Local engineering verification

| Check | Result on 6 October 2026 |
|---|---|
| `manage.py check` | Passed: no issues reported. |
| `makemigrations --check --dry-run` | Passed: no model changes detected. |
| `migrate --check` | Exited successfully; no pending migrations were reported. |
| Initial `manage.py test --keepdb` | Failed: 128 tests discovered; five errors and one failure. |
| Focused rerun of the six affected tests | Passed: all six tests passed. |
| Full suite after date fixes | Passed: all 128 tests passed. |
| Latest full suite after currency and repair-document changes | Passed: all 133 tests passed. |

The full passing run is the current test result for this report. The README's
acceptance section has been updated with the 6 October result; earlier
acceptance evidence from 1 October is clearly labeled as historical.

### Test failure analysis

The initial failing run identified these six tests in `workshop/tests.py`:

**Five errors caused by a fixed due date of 1 October 2026:**

- `InvoiceFormTests.test_invoice_form_excludes_repair_orders_with_existing_invoices`
- `RepairPricingWorkflowTests.test_tax_total_is_rounded_to_cents`
- `RepairPricingWorkflowTests.test_work_lines_cannot_be_added_after_invoice_creation`
- `ReportPageTests.test_date_filtered_report_uses_real_payments_and_operational_records`
- `RoleBoundaryTests.test_admin_search_filters_vehicles_repairs_invoices_and_appointments`

Those tests let `issue_date` default to the current date while setting
`due_date` to 1 October 2026. When the current date was later than that,
MySQL's `invoice_due_date_not_before_issue` constraint correctly rejected
the invoice because its due date preceded its issue date.

**One failure caused by a fixed-date assertion:**

- `CustomerRepairOrderSummaryTests.test_invoice_edits_record_financial_before_and_after_values`

This test asserted fixed before/after due dates even though its invoice fixture
sets the initial due date relative to the current date.

The five error-producing fixtures now set the due date to one day after
`timezone.localdate()`. The audit test now derives the expected old due date
from its invoice fixture and the new due date from that value, avoiding stale
calendar literals. The six targeted tests passed, and the full suite then
passed all 128 tests. Currency-format tests were subsequently added; the latest
full run passed all 133 tests on 6 October 2026.

The repair-document issue was caused by the upload view overriding the
`customer_visible` checkbox to false for assigned mechanics. That override has
been removed: the saved visibility now follows the submitted checkbox for
authorized uploaders. Regression tests confirm that a checked document appears
on its customer's repair-order page and the customer can download it, while
access remains scoped to that customer's own repair order.

The latest changes also standardize monetary display through one Rand formatter
that uses two decimal places and half-up rounding. It is used for invoice,
payment, repair-order, estimate, inventory, service catalogue, report, and CSV
amounts. The invoice-ready customer email now includes the balance in Rand, for example
`R 115.00`. Regression tests cover rounding, displayed catalogue and
invoice amounts, CSV amounts, and the email balance.

### Feature and workflow evidence

The source and project documentation show implemented areas for customer and
vehicle management, repair orders, estimates, labor and parts, appointments,
inventory, invoicing and payments, reports, authentication, and role-based
dashboards. Automated tests exercise multiple form, workflow, access-control,
financial, inventory, reporting, and audit behaviors.

The Playwright suite in `tests/e2e/workshop.spec.mjs` defines browser tests for
the administrator, mechanic, and customer dashboards, primary admin pages and
mechanic access denials, plus an administrator workflow that creates a
customer, adds a vehicle, and opens a repair order. The suite has not been
executed as part of this verification; it requires dedicated QA accounts and an
isolated QA database. The Django suite now also tests that console-style
overpayment records are flagged and cannot be extended through the payment
views. It does not cover the complete
customer-to-workshop-to-payment journey or measure task completion time, user
errors, or satisfaction.

## 5. Usability testing and demonstration

### Usability testing status

No measured usability study is documented in the available project evidence.
Consequently, the following results are **not available**:

- Number and profile of participants.
- Task completion times or task completion rates.
- User errors, assistance required, or points of confusion.
- User satisfaction scores or qualitative feedback.
- A comparison of usability results before and after interface changes.

These measures should be collected with consent from representative users,
using anonymized results. Until then, no claim about measured usability or
participant satisfaction should be made.

### Proposed demonstration walkthrough

The following walkthrough can be used for a future live demonstration with
isolated sample data and dedicated test accounts:

1. Sign in as an administrator and review the workshop dashboard.
2. Add a customer and register a vehicle.
3. Create a repair order and assign a mechanic.
4. Sign in as the mechanic, review the job, and propose a status update.
5. Return as the administrator to review the proposal and add or approve work
   details.
6. Show the estimate and customer decision step, where configured.
7. Create an invoice, record a payment, and show the resulting balance and
   payment status.
8. Sign in as the customer to review the relevant repair and invoice
   information.
9. Show inventory, appointments, and reporting as supporting operational
   features.

The walkthrough is a proposed demonstration script, not a record of a
completed end-to-end demonstration. Use only synthetic data and QA accounts;
do not expose real customer records or credentials.

## 6. Limitations and risks

1. **Test status records can become stale.** The current 133-test suite passed
   after date-dependent fixtures were corrected. The README now distinguishes
   this result from older, historical acceptance evidence.
2. **Usability evidence is missing.** The project does not document a study
   measuring task times, error rates, or satisfaction.
3. **End-to-end acceptance is incomplete.** The project README identifies a
   full browser-driven customer, administrator, and mechanic workflow as
   outstanding.
4. **Production readiness is not demonstrated.** Production hosting,
   reverse-proxy and TLS behavior, static-file serving, logging and monitoring,
   and production secrets have not been verified in this workspace.
5. **Recovery is unproven.** The README states that a production backup and
   restore drill covering MySQL, uploaded media, and the matching encryption
   key have not been performed.
6. **External-service behavior is incomplete.** Live email arrival and retry
   behavior under SMTP failure remain unverified. The project does not claim
   a live payment-gateway integration or verified gateway callbacks.
7. **Performance has not been measured.** Load testing with representative,
   anonymized workshop data and operational recovery testing remain future
   work.
8. **Responsive and accessibility coverage is limited.** Selected views have
   responsive checks recorded in the README, but that is not comprehensive
   device, keyboard, screen-reader, or accessibility testing.

## 7. Future improvements

### Before presenting the project as complete

- Keep the README acceptance record synchronized with future test runs.
- Run and document a complete browser journey across customer, mechanic, and
  administrator roles using isolated test data.
- Conduct a usability study with representative users. Define realistic tasks
  in advance, capture task completion time and success, record errors and
  assistance, and collect a short satisfaction measure and qualitative
  feedback.
- Demonstrate the application using the walkthrough above, noting which
  steps are live and which are simulated.

### Before production use

- Configure and verify a production deployment behind HTTPS.
- Exercise backup and restore for the database, uploaded documents, and
  encryption-key recovery process.
- Verify email delivery and failure handling in the intended environment.
- Add operational monitoring, log-retention policy, and recovery procedures.
- Perform representative load, security, accessibility, and cross-device
  testing.

### Product improvements

- Prioritize interface changes based on observed usability findings rather
  than assumptions about user preferences.
- Add clearer inline validation and recovery guidance where testing shows
  users make errors or need help.
- Improve coverage for the entire repair lifecycle, including exceptional
  cases such as rejected estimates, cancelled work, partial payment, and
  unavailable parts.

## 8. Reflection: designing for people

This project demonstrates that a workshop system is not only a collection of
records and forms. Its design must help people understand what needs attention,
what a status means, who is responsible for the next step, and what will happen
after they act. Dashboards, status proposals, approval queues, and workflow
shortcuts are attempts to make those responsibilities visible.

One important lesson is that implementation evidence and user evidence answer
different questions. Automated tests can verify business rules such as
preventing invalid invoice dates or restricting access, but they cannot show
whether a mechanic can find the next action quickly or whether a customer
understands an invoice. A technically working screen is not, by itself,
evidence that the screen fits the user's mental model.

The clearest surprise in this review is how much a seemingly small assumption
about dates can affect confidence in a large test suite. Fixed dates that once
worked became invalid as the calendar moved forward. Tests, documentation,
and operational procedures need to be designed to remain trustworthy over
time, not just to pass on the day they are written.

No participant feedback was available for this report, so it would be
misleading to claim that users preferred a particular design or to say that
feedback led to specific changes. With real feedback, the next iteration
should revisit labels, task order, status visibility, error recovery, and
mobile use. The team should then document what changed, why it changed, and
whether the revised workflow improved measured outcomes.

## Conclusion

The project has a broad and meaningful workshop-management implementation,
useful operational documentation, and a substantial automated test suite.
Local Django and migration checks passed on 6 October 2026, and all 133
automated tests passed after fixing the date-dependent tests. The project
still needs further acceptance evidence and production exercises before it
can be described as fully validated or production-ready.

Measured usability testing, a completed end-to-end demonstration, production
and recovery exercises, and a clean current test run are the principal
remaining steps before making a complete Phase 4 acceptance claim.
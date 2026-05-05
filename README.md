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

### Step 4 — Run Migrations

This creates the SQLite database and all tables:
```bash
python manage.py makemigrations workshop
python manage.py migrate
```

### Step 5 — Create a Superuser (Admin Account)

```bash
python manage.py createsuperuser
# Enter: username, email (optional), password
```

### Step 6 — Start the Development Server

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
1. Change `SECRET_KEY` in `settings.py`
2. Set `DEBUG = False`
3. Update `ALLOWED_HOSTS` with your domain
4. Switch database from SQLite to PostgreSQL
5. Run `python manage.py collectstatic`
6. Set up a production WSGI server (Gunicorn + Nginx)

---

## 📞 Support

Uncle Kop's Workshop — Bloemfontein, South Africa  
Built with Django 4.2 | South African VAT (15%) pre-configured

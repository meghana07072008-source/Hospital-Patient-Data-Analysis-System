# Pulseboard: Hospital Patient Data Analysis System

Educational operational analytics on **synthetic, de-identified** hospital visit records.
Built with **Flask, MySQL, Pandas, NumPy, Matplotlib, HTML and CSS** (Chart.js for the animated dashboard charts).

> Every figure is an operational statistic. Nothing here is clinical advice, diagnosis or treatment guidance.

## What you get

| Area | Details |
|---|---|
| Login and register | Hashed passwords, CSRF protection, sign-in throttling, role-based access (user / admin) |
| User dashboard | Animated ECG trace of the last 30 days, KPI tiles, monthly trend, department workload, age bands, visit types, weekday pattern, date-range switcher, light and dark themes |
| Admin dashboard | Everything above plus system overview, workload indicators, department-by-weekday heatmap, recent access activity |
| Admin tools | Visit records (search, add, delete), synthetic patients, departments, user management, audit log, dataset regeneration |
| Reports | Filters by date, department and visit type. Department workload, monthly trend, age-band summary, age-by-department table, charts (Matplotlib), CSV and Excel export, print view |
| Privacy | Reports show aggregates only, counts under 5 are hidden, patients are stored as an age band plus an optional gender, every record view and export is logged |

## Quick start (Windows, macOS, Linux)

1. Install **Python 3.10+** and **MySQL Server 8** (make sure the MySQL service is running).
2. Open a terminal in this folder and create a virtual environment:

   ```bash
   python -m venv venv
   venv\Scripts\activate          # Windows
   # source venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and put your MySQL password in `MYSQL_PASSWORD`.
4. Create the database, tables, accounts and synthetic data:

   ```bash
   python seed.py
   ```

5. Start the app and open <http://127.0.0.1:5000>:

   ```bash
   python app.py
   ```

If you skip step 4, the first page load does the same setup automatically.

### Default accounts (created by `seed.py`)

| Role | Email | Password |
|---|---|---|
| Admin | `admin@hospital.local` | `Admin@12345` |
| User | `user@hospital.local` | `User@12345` |

Change them in `.env` before sharing the app, and set `SHOW_DEMO_HINT=0` to hide the demo panel on the login page. New people can register themselves and get the **user** role. Admins can promote them in **Users**.

### Try it without MySQL

Set `DB_BACKEND=sqlite` in `.env`. The same code runs on a local SQLite file (`instance/hospital.db`), which is handy for a quick look. MySQL is the intended database.

### Manual MySQL import (optional)

```bash
mysql -u root -p < schema.sql
```

## Database design

```
patients(patient_id, age_band, gender)            -- de-identified, gender optional
departments(department_id, department_name)
visits(visit_id, patient_id, department_id, visit_date, visit_type)
users(user_id, full_name, email, password_hash, role, is_active, created_at, last_login)
audit_log(log_id, user_id, action, detail, ip_address, created_at)
```

## How the analysis works

* `analytics.py` loads the joined visit data into a **Pandas** DataFrame and uses grouped analysis for daily, monthly, department, age-band, visit-type and weekday summaries.
* **NumPy** provides the summary statistics: mean, median, standard deviation, 90th percentile and coefficient of variation of daily visits.
* `charts.py` draws the report charts with **Matplotlib** (department workload, monthly trend, daily trend, age bands, visit types, weekday pattern, department-by-weekday heatmap).
* The dashboards fetch aggregated JSON from `/api/dashboard` and draw animated Chart.js charts. If the Chart.js CDN cannot be reached, the dashboard falls back to the Matplotlib images.
* *Workload indicators* compare each department's last 30 days with the 90 days before. They describe visit volume only.

## Acceptance criteria checklist

* **Synthetic or de-identified data only:** `seed.py` generates every record. No names or contact details exist anywhere in the schema.
* **Restricted access:** every page except login and register needs an account, admin pages need the admin role, and views, exports and denied attempts are written to the audit log.
* **Aggregates only:** reports and dashboards return grouped counts. Counts under 5 appear as `<5`. Individual visit rows are visible only on the admin Visit records page, using pseudonymous patient codes.
* **Labelled as operational statistics:** a notice appears in the footer of every page, on the login and register screens, in exports and at the bottom of every Matplotlib chart.

## Project structure

```
hospital_analytics/
  app.py            Flask app: routes, auth, CSRF, exports
  config.py         Settings (reads .env)
  db.py             MySQL (PyMySQL) layer with SQLite fallback
  analytics.py      Pandas and NumPy analysis
  charts.py         Matplotlib charts
  seed.py           Synthetic data generator
  schema.sql        MySQL schema
  templates/        Jinja pages
  static/css/       Stylesheet
  static/js/        Dashboard and UI scripts
```

## Troubleshooting

* **"Database unavailable" page:** MySQL is not running, or the values in `.env` are wrong.
* **`cryptography` or authentication errors:** MySQL 8 uses `caching_sha2_password`. `pip install -r requirements.txt` installs the needed package.
* **Charts look static or plain:** the animated charts load Chart.js from a CDN, so they need internet access. Without it the Matplotlib versions appear instead.
* **Want fresh data:** sign in as admin, open **Data tools**, or run `python seed.py --reset`.

"""Synthetic data generator.

Creates departments, de-identified patients (age band + optional gender only)
and visits. No names, contact details or real records are ever produced.

Usage:
    python seed.py             # create tables, default accounts, data if empty
    python seed.py --reset     # wipe patients/visits and regenerate
    python seed.py --months 24
"""
import argparse
from datetime import date, timedelta

import numpy as np
from werkzeug.security import generate_password_hash

from db import init_schema, now_str

AGE_BANDS = ["0-12", "13-17", "18-29", "30-44", "45-59", "60-74", "75+"]
VISIT_TYPES = ["Outpatient", "Follow-up", "Scheduled", "Emergency"]
GENDERS = ["F", "M", "Other"]

# name, popularity weight, age-band weights, {month: seasonal multiplier}
DEPARTMENTS = [
    ("General Medicine",      20, [3, 2, 14, 24, 24, 24, 9],  {7: 1.25, 8: 1.3, 9: 1.2}),
    ("Pediatrics",            12, [62, 30, 4, 3, 1, 0, 0],    {7: 1.3, 8: 1.35, 9: 1.25, 12: 1.15}),
    ("Emergency Medicine",    14, [8, 6, 20, 22, 18, 17, 9],  {5: 1.1, 12: 1.1}),
    ("Orthopedics",            8, [3, 5, 14, 20, 26, 24, 8],  {}),
    ("Cardiology",             7, [0, 0, 3, 14, 30, 38, 15],  {12: 1.25, 1: 1.3, 2: 1.2}),
    ("Obstetrics & Gynecology",9, [0, 1, 40, 45, 12, 2, 0],   {}),
    ("Dermatology",            6, [6, 8, 28, 28, 18, 9, 3],   {4: 1.25, 5: 1.3, 6: 1.2}),
    ("ENT",                    5, [12, 8, 18, 22, 20, 15, 5], {11: 1.15, 12: 1.2, 1: 1.2}),
    ("Ophthalmology",          5, [6, 6, 12, 18, 24, 26, 8],  {}),
    ("Neurology",              4, [2, 3, 10, 20, 26, 29, 10], {}),
    ("Dentistry",              6, [8, 10, 26, 26, 18, 10, 2], {}),
    ("Radiology",              4, [2, 3, 14, 24, 26, 24, 7],  {}),
]

WEEKDAY_FACTOR = [1.15, 1.10, 1.05, 1.05, 1.00, 0.60, 0.35]  # Mon..Sun
MONTH_FACTOR = {1: 1.08, 2: 1.0, 3: 0.97, 4: 0.95, 5: 0.92, 6: 1.0,
                7: 1.12, 8: 1.15, 9: 1.12, 10: 1.05, 11: 1.0, 12: 1.06}


def ensure_departments(db):
    existing = {r["department_name"] for r in db.all("SELECT department_name FROM departments")}
    for name, *_ in DEPARTMENTS:
        if name not in existing:
            db.execute("INSERT INTO departments (department_name) VALUES (%s)", (name,))
    return {r["department_name"]: r["department_id"]
            for r in db.all("SELECT department_id, department_name FROM departments")}


def ensure_default_users(db, cfg):
    created = []
    seeds = [
        (cfg["ADMIN_NAME"], cfg["ADMIN_EMAIL"], cfg["ADMIN_PASSWORD"], "admin"),
        ("Demo Analyst", cfg["DEMO_USER_EMAIL"], cfg["DEMO_USER_PASSWORD"], "user"),
    ]
    for name, email, password, role in seeds:
        if db.one("SELECT user_id FROM users WHERE email = %s", (email.lower(),)):
            continue
        db.execute(
            "INSERT INTO users (full_name, email, password_hash, role, is_active, created_at) "
            "VALUES (%s, %s, %s, %s, 1, %s)",
            (name, email.lower(), generate_password_hash(password), role, now_str()),
        )
        created.append(email)
    return created


def seed_synthetic(db, months=18, n_patients=2800, rng_seed=42, replace=True, today=None):
    """Generate synthetic patients and visits. Returns (patients, visits)."""
    rng = np.random.default_rng(rng_seed)
    today = today or date.today()
    dept_ids = ensure_departments(db)

    if replace:
        db.execute("DELETE FROM visits")
        db.execute("DELETE FROM patients")

    # ---- patients: age band + optional gender only ----
    band_p = np.array([10, 5, 18, 24, 20, 17, 6], dtype=float)
    band_p /= band_p.sum()
    bands = rng.choice(len(AGE_BANDS), size=n_patients, p=band_p)
    genders = rng.choice(4, size=n_patients, p=[0.48, 0.46, 0.01, 0.05])  # 3 = not disclosed
    db.executemany(
        "INSERT INTO patients (age_band, gender) VALUES (%s, %s)",
        [(AGE_BANDS[b], GENDERS[g] if g < 3 else None) for b, g in zip(bands, genders)],
    )
    patients = db.all("SELECT patient_id, age_band FROM patients ORDER BY patient_id")
    by_band = {}
    for band in AGE_BANDS:
        ids = np.array([p["patient_id"] for p in patients if p["age_band"] == band])
        weights = rng.gamma(1.2, 1.0, size=len(ids)) if len(ids) else np.array([])
        by_band[band] = (ids, weights / weights.sum() if len(ids) else weights)

    # ---- daily volumes ----
    start = today - timedelta(days=int(months * 30.4))
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    total_days = len(days)
    base = 36.0
    names = [d[0] for d in DEPARTMENTS]
    weights = np.array([d[1] for d in DEPARTMENTS], dtype=float)
    age_w = [np.array(d[2], dtype=float) / sum(d[2]) for d in DEPARTMENTS]
    emergency_idx = names.index("Emergency Medicine")

    rows_dept, rows_date = [], []
    for t, day in enumerate(days):
        expected = base * WEEKDAY_FACTOR[day.weekday()] * MONTH_FACTOR[day.month] * (1 + 0.15 * t / total_days)
        n = rng.poisson(expected)
        w = weights.copy()
        for i, d in enumerate(DEPARTMENTS):
            w[i] *= d[3].get(day.month, 1.0)
            if day.weekday() >= 5 and i != emergency_idx:
                w[i] *= 0.5  # elective departments quieten at weekends
        counts = rng.multinomial(n, w / w.sum())
        for i, c in enumerate(counts):
            rows_dept.extend([i] * int(c))
            rows_date.extend([day] * int(c))

    rows_dept = np.array(rows_dept)
    rows_date = np.array([d.isoformat() for d in rows_date])
    patient_col = np.zeros(len(rows_dept), dtype=int)
    type_col = np.empty(len(rows_dept), dtype=object)

    for i in range(len(DEPARTMENTS)):
        idx = np.where(rows_dept == i)[0]
        if not len(idx):
            continue
        band_choice = rng.choice(len(AGE_BANDS), size=len(idx), p=age_w[i])
        for b, band in enumerate(AGE_BANDS):
            sel = idx[band_choice == b]
            ids, w = by_band[band]
            if len(sel) and len(ids):
                patient_col[sel] = rng.choice(ids, size=len(sel), p=w)
        if i == emergency_idx:
            probs = [0.10, 0.05, 0.0, 0.85]
        else:
            probs = [0.62, 0.25, 0.10, 0.03]
        type_col[idx] = rng.choice(VISIT_TYPES, size=len(idx), p=probs)

    keep = patient_col > 0
    records = [
        (int(p), dept_ids[names[d]], dt, vt)
        for p, d, dt, vt in zip(patient_col[keep], rows_dept[keep], rows_date[keep], type_col[keep])
    ]
    db.executemany(
        "INSERT INTO visits (patient_id, department_id, visit_date, visit_type) VALUES (%s, %s, %s, %s)",
        records,
    )
    return len(patients), len(records)


def main():
    from app import create_app
    from db import ensure_database, get_db

    parser = argparse.ArgumentParser(description="Create tables and synthetic data")
    parser.add_argument("--reset", action="store_true", help="wipe and regenerate patients/visits")
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--patients", type=int, default=2800)
    args = parser.parse_args()

    app = create_app()
    ensure_database(app.config)
    with app.app_context():
        db = get_db()
        init_schema(db, app.config)
        ensure_departments(db)
        users = ensure_default_users(db, app.config)
        if users:
            print("Created accounts:", ", ".join(users))
        has_data = db.scalar("SELECT COUNT(*) FROM visits", default=0) > 0
        if args.reset or not has_data:
            p, v = seed_synthetic(db, months=args.months, n_patients=args.patients)
            print(f"Generated {p} synthetic patients and {v} visits.")
        else:
            print("Data already present (use --reset to regenerate).")


if __name__ == "__main__":
    main()

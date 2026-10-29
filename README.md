# PulseLink — Emergency Blood Donor Finder System

A responsive educational mini-project built with **Python Flask, SQLite, HTML, and CSS**. It demonstrates donor registration, account authentication, donor search, blood-request posting, volunteer responses, profile management, and basic web-security practices.

> **Important:** This is a student demonstration project, not a verified medical service. User entries and donor availability are not verified. Blood compatibility and donor eligibility must be confirmed by qualified healthcare professionals. Do not use the demo data for real medical decisions.

## Main features

- Responsive landing page inspired by the supplied PulseLink screenshots
- User registration, login, logout, and password hashing
- Session-based authentication and CSRF token checks on POST forms
- Dashboard showing account activity and recent requests
- Donor directory with city and blood-group filters and a basic compatibility filter
- Blood requests with required group, units, city, hospital/location, contact number, notes, urgency, and status
- Volunteer response to requests, duplicate-response prevention, and owner-only status updates
- Profile management, donor role, and self-reported availability
- SQLite database created automatically on first run
- Demo data seeding command for project presentation

## Requirements

- Python 3.10 or newer (Python 3.11+ recommended)
- Internet connection only if you want the optional Google Fonts to load; the application itself runs locally

## Run locally

### Windows

```bash
cd PulseLink
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py --seed-demo
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

### macOS / Linux

```bash
cd PulseLink
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py --seed-demo
python app.py
```

Open `http://127.0.0.1:5000` in your browser. The server listens on all local interfaces by default so it can also be previewed by supported coding environments.

### Android phone (Termux)

1. Install Termux from a trusted distribution source and open it.
2. Run `pkg update` and `pkg install python`.
3. Move/extract the `PulseLink` folder into Termux-accessible storage, then `cd` into the project folder.
4. Run `pip install -r requirements.txt`, then `python app.py --seed-demo`, then `python app.py`.
5. Keep Termux running and open `http://127.0.0.1:5000` in your phone browser.

A browser-based coding environment can also run the same project if it supports Flask apps and persistent project files.

## Demo login

Seed demo data with `python app.py --seed-demo` first.

- Email: `donor.a@pulselink.demo`
- Password: `Demo@123`

Other seeded donor/recipient accounts use the same password `Demo@123`:
- `donor.b@pulselink.demo`
- `donor.c@pulselink.demo`
- `recipient@pulselink.demo`

Demo data is fictional and exists only to demonstrate the screens. The seed command is safe to run more than once; existing demo users are not duplicated.

## Project structure

```text
PulseLink/
├── app.py                 # Flask routes, database schema, auth, and app logic
├── requirements.txt       # Python dependencies
├── README.md              # Setup and usage instructions
├── pulselink.db           # Created automatically when run
├── static/
│   └── style.css          # Responsive styling
└── templates/
    ├── base.html
    ├── index.html
    ├── auth_layout.html
    ├── register.html
    ├── login.html
    ├── dashboard.html
    ├── donors.html
    ├── requests.html
    ├── create_request.html
    ├── request_detail.html
    ├── profile.html
    └── error.html
```

## Database tables

- `users`: profile, contact, blood group, account role, password hash, availability
- `blood_requests`: request details, urgency, status, creator, and timestamp
- `responses`: volunteer responses linked to a request and user

## Security and limitations

Passwords are stored using Werkzeug password hashing rather than plaintext. POST forms carry a session-based CSRF token, and request ownership is checked before status updates. This is a learning project, not a production deployment. Before any real deployment, configure a strong secret key, HTTPS, rate limiting, email/phone verification, stricter privacy controls, audit logs, and professional medical review. Contact information should not be shared publicly without consent.

## Optional configuration

- `PULSELINK_SECRET_KEY`: set a long random secret before deployment
- `PULSELINK_DB`: set a custom SQLite database file path
- `PORT`: change the local HTTP port (default `5000`)
- `FLASK_DEBUG=1`: enable Flask debug mode for local development only

# Bouvane company website

A Django site for Bouvane's application-aware security platform. Includes AIWAF,
Bouvane Cloud beta signup, and a contact form. Original CSS takes inspiration
from PyCon and DjangoCon's conference design language using the supplied logo's
red, orange, and gold palette; no third-party conference stylesheets are copied.

## Run locally (PowerShell)

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000/.

## Review enquiries and beta signups

```powershell
.\venv\Scripts\python.exe manage.py createsuperuser
```

Sign in at `/admin/` and open **Enquiries** for messages or **Beta signups** for
the waitlist. Contact submissions retain name, email, company, topic, and message;
beta signups retain email, consent, and signup timestamp. Mark an enquiry as
handled after responding or a beta signup as invited after sending an invitation.
Duplicate beta emails are ignored.

Enquiries are saved to SQLite regardless of notification delivery. Optional
contact email notifications use `CONTACT_RECIPIENT` and `DEFAULT_FROM_EMAIL`
environment variables. The default mail backend only prints to the server
console; configure `MAILERS` in `bouvane/settings.py` with a real provider before
expecting delivery. Beta signups are stored; invitations are not sent automatically.

## Check

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test website
```

This checkout uses development settings. Before a production Django deployment,
configure a private secret key, disable DEBUG, set DJANGO_ALLOWED_HOSTS, serve
collected static files, and configure HTTPS, database backups, and mail delivery.
Google Fonts are optional; local Arial and monospace fallbacks are included.

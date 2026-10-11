# Student Portal Management API

A testing-focused student portal backend built with **FastAPI**, **MongoDB Atlas**, JWT bearer authentication, Pydantic validation, and pytest.

> **Testing project, not production-ready.** Use synthetic data. Review security, privacy, retention, backups, monitoring, and access policies before handling real student records.

## Features
- JWT login and student registration with bcrypt password hashes
- Student profiles, course catalogue, enrollments
- Attendance, grades/feedback, announcements
- Student and admin dashboards and role-based access controls
- Validation, bounded pagination, duplicate prevention, MongoDB indexes, OpenAPI docs

## Technology
Python 3.12+, FastAPI, Pydantic v2, Motor/PyMongo, MongoDB Atlas, python-jose JWT, passlib/bcrypt, pytest.

## Project structure
`main.py` contains API routes and database access; `requirements.txt` lists dependencies; `tests/test_main.py` contains smoke/security tests; `.env.example` contains environment variable names and examples; `vercel.json` configures the Python API entrypoint.

## Run locally

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

Fill `.env` with your own MongoDB Atlas URI and a long random JWT secret. Never commit `.env`. Visit http://localhost:8000/docs for Swagger UI, or `/redoc` for ReDoc.

## Environment variables
- `MONGODB_URI`: Atlas connection URI; required for data routes.
- `DATABASE_NAME`: defaults to `student_portal`.
- `JWT_SECRET_KEY`: private token-signing key.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: defaults to 60.
- `CORS_ORIGINS`: comma-separated frontend origins; `*` is for local testing only.

## MongoDB setup
Create a least-privilege Atlas database user with `readWrite` only on `student_portal`. Restrict network access. The project Atlas network access list currently contains a broad `0.0.0.0/0` rule, which allows connections from any IPv4 address; restrict it before real use. The app pings MongoDB and creates indexes at startup. Collections are created on first write: `users`, `courses`, `enrollments`, `attendance`, `grades`, and `announcements`. No student sample data is automatically inserted.

## Authentication

### Register a student
`POST /api/v1/auth/register`

```json
{
  "name": "Demo Student",
  "email": "student@example.com",
  "password": "ChangeThisPassword123!",
  "student_id": "STU-1001",
  "department": "CSE AI/ML",
  "year": 1
}
```

Log in at `POST /api/v1/auth/token` with form fields `username` (the email address) and `password`. Send the returned token as `Authorization: Bearer <access_token>` or use Swagger's **Authorize** button.

### Create the first administrator
Public registration only creates student accounts after an admin exists. Register the intended first admin, then promote that account from a trusted MongoDB shell session on your own test database:

```javascript
db.users.updateOne({ email: "admin@example.com" }, { $set: { role: "admin" } })
```

Replace the email with an account you registered. There is deliberately no public admin-promotion endpoint.

## API endpoints
Everything below is prefixed by `/api/v1`.

| Method | Endpoint | Access |
|---|---|---|
| POST | `/auth/register`, `/auth/token` | Public; registration creates students |
| GET | `/auth/me` | Authenticated |
| GET | `/students` | Admin list; student sees self |
| GET/PATCH/DELETE | `/students/{student_id}` | Admin; owner read/update own profile |
| GET | `/courses` | Authenticated |
| POST | `/courses` | Admin |
| GET/PATCH/DELETE | `/courses/{course_id}` | Authenticated read; admin write |
| POST/GET | `/enrollments` | Authenticated; student limited to self |
| DELETE | `/enrollments/{enrollment_id}` | Owner or admin |
| POST/GET | `/attendance` | Admin creates; student views own records |
| POST/GET/PATCH | `/grades`, `/grades/{grade_id}` | Admin writes; student views own records |
| POST/GET | `/announcements` | Admin creates; authenticated list |
| DELETE | `/announcements/{announcement_id}` | Admin |
| GET | `/dashboard` | Role-aware summary |
| GET | `/admin/overview` | Admin only |
| GET | `/health` | Public health check |

Open `/docs` for request schemas and response models.

## Tests

```bash
pytest -q
```

The initial suite covers route availability, unauthenticated-access rejection, ObjectId validation, password hashing, and avoiding password-hash leakage. These are smoke tests, not a complete integration suite. Add integration tests against a disposable MongoDB before production. Tests have not been executed inside this conversation's environment; run the command above locally or in CI.

## Vercel deployment

The repository includes Vercel Python runtime routing. In Vercel Project Settings → Environment Variables, set these values for the environments you will use:

- `MONGODB_URI` — the full, real Atlas URI with a current valid password (keep it secret)
- `DATABASE_NAME` = `student_portal`
- `JWT_SECRET_KEY` — a long, random generated value; do not reuse the database password
- `ACCESS_TOKEN_EXPIRE_MINUTES` = `60`
- `CORS_ORIGINS` = exact trusted frontend origins, comma-separated (avoid `*` when credentials or real data are involved)

**The deployed API's `/health` currently returns `degraded` because `MONGODB_URI` is a placeholder and isn't connected to Atlas yet.** Replace it with the real URI in Vercel's dashboard and redeploy; do not put database credentials into Git. Then verify `/health`, `/docs`, and an authenticated flow. The environment-value connector was unable to save the valid credential value in this setup, so it must be entered directly in the Vercel dashboard.

A MongoDB application user and password were created during setup. For safety, rotate the generated database password in Atlas and use the new password only in Vercel; do not paste it into GitHub or chat. Vercel Python runtime and connection behaviour can change, so confirm current platform limits. A container host can be more appropriate for a continuously running API.

## Security checklist
Before handling real records, add rate limiting, email verification, password reset, audit logs, monitoring, backups, retention controls, stricter CORS, and an independent security review. Use HTTPS, least-privilege database access, and synthetic test data. Disabled accounts are rejected on every authenticated request; otherwise tokens remain valid until expiry.

## License
For learning and testing. Add a formal license before redistribution.

# Student Portal Management API

A testing-focused FastAPI + MongoDB Atlas backend for student portal management.

> Testing project, not production-ready. Use synthetic data and review security/privacy before handling real student records.

## Features
- JWT login and student registration with bcrypt password hashes
- Student profiles, course catalogue, enrollments
- Attendance, grades/feedback, announcements
- Student and admin dashboards and role-based access controls
- Validation, bounded pagination, duplicate prevention, MongoDB indexes, OpenAPI docs

## Stack
Python 3.12+, FastAPI, Pydantic v2, Motor/PyMongo, MongoDB Atlas, python-jose JWT, passlib/bcrypt, pytest.

## Project files
`main.py` contains API routes and persistence; `requirements.txt` dependencies; `tests/test_main.py` smoke/security tests; `.env.example` environment template; `vercel.json` Vercel Python routing.

## Run locally

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

Edit `.env` with your Atlas URI and strong random JWT secret. Never commit `.env`. Then visit http://localhost:8000/docs or /redoc.

## Environment variables
- `MONGODB_URI`: Atlas connection URI; required for data routes.
- `DATABASE_NAME`: `student_portal` by default.
- `JWT_SECRET_KEY`: private token-signing key.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: token lifetime in minutes; defaults to 60.
- `CORS_ORIGINS`: comma-separated allowed frontend origins; default `*` is for testing only.

## Database
Create a least-privilege Atlas database user with `readWrite` on `student_portal`. Restrict network access; do not use a wide-open IP rule in production. On startup, the app pings Atlas and creates indexes for email, course codes, enrollments, attendance, grades, and announcements. Collections are created on first write. No student sample data is inserted automatically.

## Auth basics
Register a student with `POST /api/v1/auth/register` and JSON body such as:

```json
{"name":"Demo Student","email":"student@example.com","password":"ChangeThisPassword123!","student_id":"STU-1001","department":"CSE AI/ML","year":1}
```

Log in at `POST /api/v1/auth/token` using form fields `username` (email) and `password`. Use the returned token as `Authorization: Bearer <token>` or the Swagger **Authorize** button.

### First administrator
Public registration is student-only after an admin exists. To bootstrap an initial admin, register the intended account, then promote it through a trusted MongoDB shell session on your own test database:

```javascript
db.users.updateOne({ email: "admin@example.com" }, { $set: { role: "admin" } })
```

Replace the email with your registered account. Do not expose a public admin-promotion endpoint.

## Endpoints
Everything below is prefixed by `/api/v1`:

| Method | Endpoint | Access |
|---|---|---|
| POST | `/auth/register`, `/auth/token` | Public; registration creates students |
| GET | `/auth/me` | Authenticated |
| GET | `/students` | Admin list; student sees self |
| GET/PATCH/DELETE | `/students/{student_id}` | Admin; owner read/update |
| GET | `/courses` | Authenticated |
| POST | `/courses` | Admin |
| GET/PATCH/DELETE | `/courses/{course_id}` | Authenticated read; admin write |
| POST/GET | `/enrollments` | Authenticated; student limited to self |
| DELETE | `/enrollments/{enrollment_id}` | Owner or admin |
| POST/GET | `/attendance` | Admin creates; users read allowed records |
| POST/GET/PATCH | `/grades`, `/grades/{grade_id}` | Admin write; students read own |
| POST/GET | `/announcements` | Admin creates; authenticated list |
| DELETE | `/announcements/{announcement_id}` | Admin |
| GET | `/dashboard` | Role-aware summary |
| GET | `/admin/overview` | Admin only |

`GET /health` reports API/database health. `/docs` describes request schemas and responses.

## Tests

```bash
pytest -q
```

The initial suite covers route availability, unauthenticated access rejection, ObjectId validation, password hashing, and avoiding password-hash leakage. These are smoke tests, not a complete integration suite. Add tests against a disposable MongoDB before production.

## Vercel deployment
The repository includes Vercel Python runtime routing. Add `MONGODB_URI`, `DATABASE_NAME`, `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, and `CORS_ORIGINS` as **server-side** project environment variables, then redeploy. Verify `/health`, `/docs`, and an authenticated request. Vercel Python-runtime limits and connection behaviour may change, so confirm the current limits in your account. A container host can be more appropriate for a continuously running API.

## Security checklist
Before real use, add rate limiting, email verification, password reset, auditing, monitoring, backups, data-retention controls, stricter CORS, and an independent security review. Use HTTPS, a random unique JWT secret, least-privilege database permissions, and synthetic data for demos. Disabled users are rejected on every authenticated request; otherwise JWTs remain valid until expiry.

## License
For learning and testing. Add a formal license before redistribution.

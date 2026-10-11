"""Student Portal Management API."""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

APP_NAME = "Student Portal API"
MONGODB_URI = os.getenv("MONGODB_URI", "")
DATABASE_NAME = os.getenv("DATABASE_NAME", "student_portal")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
CORS_ORIGINS = [v.strip() for v in os.getenv("CORS_ORIGINS", "*").split(",") if v.strip()]
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
client: AsyncIOMotorClient | None = None
db = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid resource ID")
    return ObjectId(value)


def public_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    result = dict(doc)
    if "_id" in result:
        result["id"] = str(result.pop("_id"))
    result.pop("hashed_password", None)
    for key, value in list(result.items()):
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [str(v) if isinstance(v, ObjectId) else v.isoformat() if isinstance(v, datetime) else v for v in value]
    return result


def require_database() -> None:
    if db is None:
        raise HTTPException(status_code=503, detail="Database is not configured or unavailable")


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["student", "admin"] = "student"
    student_id: str | None = Field(default=None, max_length=30)
    department: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1, le=8)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1, le=8)


class UserOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    email: EmailStr
    role: str
    student_id: str | None = None
    department: str | None = None
    year: int | None = None
    created_at: str | None = None


class CourseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    credits: int = Field(default=3, ge=1, le=10)
    instructor: str = Field(min_length=2, max_length=100)
    semester: int = Field(ge=1, le=12)


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    credits: int | None = Field(default=None, ge=1, le=10)
    instructor: str | None = Field(default=None, min_length=2, max_length=100)
    semester: int | None = Field(default=None, ge=1, le=12)


class EnrollmentCreate(BaseModel):
    student_id: str
    course_id: str


class AttendanceCreate(BaseModel):
    student_id: str
    course_id: str
    date: datetime | None = None
    status: Literal["present", "absent", "late"] = "present"
    notes: str = Field(default="", max_length=500)


class GradeCreate(BaseModel):
    student_id: str
    course_id: str
    assessment: str = Field(min_length=2, max_length=100)
    score: float = Field(ge=0, le=1000)
    max_score: float = Field(default=100, gt=0, le=1000)
    feedback: str = Field(default="", max_length=1000)


class GradeUpdate(BaseModel):
    assessment: str | None = Field(default=None, min_length=2, max_length=100)
    score: float | None = Field(default=None, ge=0, le=1000)
    max_score: float | None = Field(default=None, gt=0, le=1000)
    feedback: str | None = Field(default=None, max_length=1000)


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=5000)
    audience: Literal["all", "students"] = "all"


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except (ValueError, TypeError):
        return False


def create_access_token(user: dict[str, Any]) -> str:
    if not JWT_SECRET_KEY:
        raise HTTPException(status_code=503, detail="JWT_SECRET_KEY is not configured")
    now = utcnow()
    return jwt.encode({"sub": str(user["_id"]), "role": user["role"], "iat": now,
                       "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
                      JWT_SECRET_KEY, algorithm="HS256")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    require_database()
    if not JWT_SECRET_KEY:
        raise HTTPException(status_code=503, detail="JWT_SECRET_KEY is not configured")
    auth_error = HTTPException(status_code=401, detail="Could not validate credentials",
                               headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise auth_error
        oid = object_id(user_id)
    except (JWTError, HTTPException):
        raise auth_error
    user = await db.users.find_one({"_id": oid, "is_active": True})
    if not user:
        raise auth_error
    return user


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


async def ensure_resource(collection: str, value: str, label: str) -> ObjectId:
    require_database()
    oid = object_id(value)
    if await db[collection].find_one({"_id": oid}) is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return oid


async def paginated(collection, query: dict[str, Any], skip: int, limit: int, sort_field: str = "created_at"):
    docs = await collection.find(query).sort(sort_field, DESCENDING).skip(skip).limit(limit).to_list(length=limit)
    return [public_doc(doc) for doc in docs]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db
    if MONGODB_URI:
        client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
        db = client[DATABASE_NAME]
        try:
            await client.admin.command("ping")
            await db.users.create_index([("email", ASCENDING)], unique=True)
            await db.courses.create_index([("code", ASCENDING)], unique=True)
            await db.enrollments.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)], unique=True)
            await db.attendance.create_index([("student_id", ASCENDING), ("course_id", ASCENDING), ("date", ASCENDING)], unique=True)
            await db.grades.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
            await db.announcements.create_index([("created_at", DESCENDING)])
        except PyMongoError:
            client.close()
            client = None
            db = None
    yield
    if client is not None:
        client.close()


app = FastAPI(title=APP_NAME, description="Student portal management API for testing and learning.",
              version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_credentials=CORS_ORIGINS != ["*"],
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])


@app.get("/", tags=["System"])
async def root():
    return {"name": APP_NAME, "version": app.version, "docs": "/docs", "health": "/health"}


@app.get("/health", tags=["System"])
async def health():
    if db is None:
        return {"status": "degraded", "database": "not_connected", "timestamp": utcnow().isoformat()}
    try:
        await db.command("ping")
        return {"status": "ok", "database": "connected", "timestamp": utcnow().isoformat()}
    except PyMongoError:
        raise HTTPException(status_code=503, detail="Database health check failed")


@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201, tags=["Authentication"])
async def register(payload: UserCreate):
    require_database()
    email = str(payload.email).lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    if payload.role == "admin" and await db.users.count_documents({"role": "admin"}) > 0:
        raise HTTPException(status_code=403, detail="Admin accounts can only be created by an existing administrator")
    doc = {"name": payload.name.strip(), "email": email, "hashed_password": hash_password(payload.password),
           "role": payload.role, "student_id": payload.student_id, "department": payload.department,
           "year": payload.year, "is_active": True, "created_at": utcnow(), "updated_at": utcnow()}
    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    doc["_id"] = result.inserted_id
    return public_doc(doc)


@app.post("/api/v1/auth/token", response_model=TokenOut, tags=["Authentication"])
async def login(form: OAuth2PasswordRequestForm = Depends()):
    require_database()
    user = await db.users.find_one({"email": form.username.lower(), "is_active": True})
    if not user or not verify_password(form.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="Incorrect email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": create_access_token(user), "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}


@app.get("/api/v1/auth/me", response_model=UserOut, tags=["Authentication"])
async def me(user: dict = Depends(get_current_user)):
    return public_doc(user)


@app.get("/api/v1/students", tags=["Students"])
async def list_students(q: str | None = Query(default=None, max_length=100), department: str | None = None,
                        year: int | None = Query(default=None, ge=1, le=8),
                        skip: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                        user: dict = Depends(get_current_user)):
    require_database()
    if user["role"] != "admin":
        return {"items": [public_doc(user)], "total": 1, "skip": 0, "limit": 1}
    query: dict[str, Any] = {"role": "student", "is_active": True}
    if department:
        query["department"] = department
    if year:
        query["year"] = year
    if q:
        query["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                        {"email": {"$regex": q, "$options": "i"}},
                        {"student_id": {"$regex": q, "$options": "i"}}]
    return {"items": await paginated(db.users, query, skip, limit),
            "total": await db.users.count_documents(query), "skip": skip, "limit": limit}


@app.get("/api/v1/students/{student_id}", tags=["Students"])
async def get_student(student_id: str, user: dict = Depends(get_current_user)):
    require_database()
    target = await db.users.find_one({"_id": object_id(student_id), "role": "student", "is_active": True})
    if target is None:
        raise HTTPException(status_code=404, detail="Student not found")
    if user["role"] != "admin" and str(user["_id"]) != student_id:
        raise HTTPException(status_code=403, detail="You can only view your own student profile")
    return public_doc(target)


@app.patch("/api/v1/students/{student_id}", tags=["Students"])
async def update_student(student_id: str, payload: UserUpdate, user: dict = Depends(get_current_user)):
    require_database()
    if user["role"] != "admin" and str(user["_id"]) != student_id:
        raise HTTPException(status_code=403, detail="You can only update your own profile")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields provided")
    changes["updated_at"] = utcnow()
    result = await db.users.find_one_and_update({"_id": object_id(student_id), "role": "student", "is_active": True},
                                                {"$set": changes}, return_document=True)
    if result is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return public_doc(result)


@app.delete("/api/v1/students/{student_id}", status_code=204, tags=["Students"])
async def deactivate_student(student_id: str, _: dict = Depends(require_admin)):
    require_database()
    result = await db.users.update_one({"_id": object_id(student_id), "role": "student"},
                                       {"$set": {"is_active": False, "updated_at": utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")


@app.post("/api/v1/courses", status_code=201, tags=["Courses"])
async def create_course(payload: CourseCreate, admin: dict = Depends(require_admin)):
    require_database()
    doc = {**payload.model_dump(), "code": payload.code.strip().upper(), "created_by": admin["_id"],
           "created_at": utcnow(), "updated_at": utcnow(), "is_active": True}
    try:
        result = await db.courses.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="A course with this code already exists")
    doc["_id"] = result.inserted_id
    return public_doc(doc)


@app.get("/api/v1/courses", tags=["Courses"])
async def list_courses(q: str | None = Query(default=None, max_length=100),
                       semester: int | None = Query(default=None, ge=1, le=12),
                       skip: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                       _: dict = Depends(get_current_user)):
    require_database()
    query: dict[str, Any] = {"is_active": {"$ne": False}}
    if semester:
        query["semester"] = semester
    if q:
        query["$or"] = [{"title": {"$regex": q, "$options": "i"}},
                        {"code": {"$regex": q, "$options": "i"}},
                        {"instructor": {"$regex": q, "$options": "i"}}]
    return {"items": await paginated(db.courses, query, skip, limit, "code"),
            "total": await db.courses.count_documents(query), "skip": skip, "limit": limit}


@app.get("/api/v1/courses/{course_id}", tags=["Courses"])
async def get_course(course_id: str, _: dict = Depends(get_current_user)):
    require_database()
    course = await db.courses.find_one({"_id": object_id(course_id), "is_active": {"$ne": False}})
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return public_doc(course)


@app.patch("/api/v1/courses/{course_id}", tags=["Courses"])
async def update_course(course_id: str, payload: CourseUpdate, _: dict = Depends(require_admin)):
    require_database()
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields provided")
    changes["updated_at"] = utcnow()
    result = await db.courses.find_one_and_update({"_id": object_id(course_id), "is_active": {"$ne": False}},
                                                  {"$set": changes}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Course not found")
    return public_doc(result)


@app.delete("/api/v1/courses/{course_id}", status_code=204, tags=["Courses"])
async def deactivate_course(course_id: str, _: dict = Depends(require_admin)):
    require_database()
    result = await db.courses.update_one({"_id": object_id(course_id)},
                                         {"$set": {"is_active": False, "updated_at": utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")


@app.post("/api/v1/enrollments", status_code=201, tags=["Enrollments"])
async def enroll(payload: EnrollmentCreate, user: dict = Depends(get_current_user)):
    require_database()
    sid = await ensure_resource("users", payload.student_id, "Student")
    cid = await ensure_resource("courses", payload.course_id, "Course")
    student = await db.users.find_one({"_id": sid, "role": "student", "is_active": True})
    course = await db.courses.find_one({"_id": cid, "is_active": {"$ne": False}})
    if not student or not course:
        raise HTTPException(status_code=404, detail="Active student or course not found")
    if user["role"] != "admin" and user["_id"] != sid:
        raise HTTPException(status_code=403, detail="You can only enroll yourself")
    doc = {"student_id": sid, "course_id": cid, "status": "enrolled", "enrolled_at": utcnow()}
    try:
        result = await db.enrollments.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Student is already enrolled in this course")
    doc["_id"] = result.inserted_id
    return public_doc(doc)


@app.get("/api/v1/enrollments", tags=["Enrollments"])
async def list_enrollments(student_id: str | None = None, course_id: str | None = None,
                           user: dict = Depends(get_current_user)):
    require_database()
    query: dict[str, Any] = {}
    if user["role"] != "admin":
        query["student_id"] = user["_id"]
    elif student_id:
        query["student_id"] = object_id(student_id)
    if course_id:
        query["course_id"] = object_id(course_id)
    docs = await db.enrollments.find(query).sort("enrolled_at", DESCENDING).limit(200).to_list(length=200)
    output = []
    for item in docs:
        row = public_doc(item)
        row["student"] = public_doc(await db.users.find_one({"_id": item["student_id"]},
                                                            {"name": 1, "email": 1, "student_id": 1}))
        row["course"] = public_doc(await db.courses.find_one({"_id": item["course_id"]},
                                                             {"title": 1, "code": 1, "credits": 1}))
        output.append(row)
    return output


@app.delete("/api/v1/enrollments/{enrollment_id}", status_code=204, tags=["Enrollments"])
async def drop_enrollment(enrollment_id: str, user: dict = Depends(get_current_user)):
    require_database()
    selector: dict[str, Any] = {"_id": object_id(enrollment_id)}
    if user["role"] != "admin":
        selector["student_id"] = user["_id"]
    result = await db.enrollments.delete_one(selector)
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Enrollment not found")


@app.post("/api/v1/attendance", status_code=201, tags=["Attendance"])
async def create_attendance(payload: AttendanceCreate, _: dict = Depends(require_admin)):
    require_database()
    sid = await ensure_resource("users", payload.student_id, "Student")
    cid = await ensure_resource("courses", payload.course_id, "Course")
    day = payload.date or utcnow()
    doc = {"student_id": sid, "course_id": cid, "date": day, "status": payload.status,
           "notes": payload.notes, "marked_at": utcnow()}
    try:
        result = await db.attendance.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Attendance for this student, course and date already exists")
    doc["_id"] = result.inserted_id
    return public_doc(doc)


@app.get("/api/v1/attendance", tags=["Attendance"])
async def list_attendance(student_id: str | None = None, course_id: str | None = None,
                          user: dict = Depends(get_current_user)):
    require_database()
    query: dict[str, Any] = {}
    if user["role"] != "admin":
        query["student_id"] = user["_id"]
    elif student_id:
        query["student_id"] = object_id(student_id)
    if course_id:
        query["course_id"] = object_id(course_id)
    docs = await db.attendance.find(query).sort("date", DESCENDING).limit(500).to_list(length=500)
    output = []
    for item in docs:
        row = public_doc(item)
        row["course"] = public_doc(await db.courses.find_one({"_id": item["course_id"]}, {"title": 1, "code": 1}))
        output.append(row)
    return output


@app.post("/api/v1/grades", status_code=201, tags=["Grades"])
async def create_grade(payload: GradeCreate, _: dict = Depends(require_admin)):
    require_database()
    sid = await ensure_resource("users", payload.student_id, "Student")
    cid = await ensure_resource("courses", payload.course_id, "Course")
    if payload.score > payload.max_score:
        raise HTTPException(status_code=422, detail="Score cannot exceed max_score")
    doc = {**payload.model_dump(), "student_id": sid, "course_id": cid,
           "created_at": utcnow(), "updated_at": utcnow()}
    result = await db.grades.insert_one(doc)
    doc["_id"] = result.inserted_id
    return public_doc(doc)


@app.get("/api/v1/grades", tags=["Grades"])
async def list_grades(student_id: str | None = None, course_id: str | None = None,
                      user: dict = Depends(get_current_user)):
    require_database()
    query: dict[str, Any] = {}
    if user["role"] != "admin":
        query["student_id"] = user["_id"]
    elif student_id:
        query["student_id"] = object_id(student_id)
    if course_id:
        query["course_id"] = object_id(course_id)
    docs = await db.grades.find(query).sort("created_at", DESCENDING).limit(500).to_list(length=500)
    output = []
    for item in docs:
        row = public_doc(item)
        row["course"] = public_doc(await db.courses.find_one({"_id": item["course_id"]}, {"title": 1, "code": 1}))
        row["percentage"] = round(item["score"] / item["max_score"] * 100, 2)
        output.append(row)
    return output


@app.patch("/api/v1/grades/{grade_id}", tags=["Grades"])
async def update_grade(grade_id: str, payload: GradeUpdate, _: dict = Depends(require_admin)):
    require_database()
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields provided")
    existing = await db.grades.find_one({"_id": object_id(grade_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Grade not found")
    if changes.get("score", existing["score"]) > changes.get("max_score", existing["max_score"]):
        raise HTTPException(status_code=422, detail="Score cannot exceed max_score")
    changes["updated_at"] = utcnow()
    return public_doc(await db.grades.find_one_and_update({"_id": existing["_id"]}, {"$set": changes},
                                                          return_document=True))


@app.post("/api/v1/announcements", status_code=201, tags=["Announcements"])
async def create_announcement(payload: AnnouncementCreate, admin: dict = Depends(require_admin)):
    require_database()
    doc = {**payload.model_dump(), "author_id": admin["_id"], "created_at": utcnow(),
           "updated_at": utcnow(), "is_active": True}
    result = await db.announcements.insert_one(doc)
    doc["_id"] = result.inserted_id
    return public_doc(doc)


@app.get("/api/v1/announcements", tags=["Announcements"])
async def list_announcements(user: dict = Depends(get_current_user)):
    require_database()
    query: dict[str, Any] = {"is_active": True}
    if user["role"] != "admin":
        query["audience"] = {"$in": ["all", "students"]}
    docs = await db.announcements.find(query).sort("created_at", DESCENDING).limit(100).to_list(length=100)
    return [public_doc(item) for item in docs]


@app.delete("/api/v1/announcements/{announcement_id}", status_code=204, tags=["Announcements"])
async def delete_announcement(announcement_id: str, _: dict = Depends(require_admin)):
    require_database()
    result = await db.announcements.update_one({"_id": object_id(announcement_id), "is_active": True},
                                               {"$set": {"is_active": False, "updated_at": utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")


@app.get("/api/v1/dashboard", tags=["Dashboard"])
async def dashboard(user: dict = Depends(get_current_user)):
    require_database()
    if user["role"] == "admin":
        return {
            "role": "admin", "students": await db.users.count_documents({"role": "student", "is_active": True}),
            "courses": await db.courses.count_documents({"is_active": {"$ne": False}}),
            "enrollments": await db.enrollments.count_documents({}),
            "attendance_records": await db.attendance.count_documents({}),
            "grade_records": await db.grades.count_documents({}),
            "announcements": await db.announcements.count_documents({"is_active": True}),
        }
    sid = user["_id"]
    enrollment_count = await db.enrollments.count_documents({"student_id": sid})
    course_ids = await db.enrollments.distinct("course_id", {"student_id": sid})
    attendances = await db.attendance.find({"student_id": sid}).to_list(length=1000)
    grades = await db.grades.find({"student_id": sid}).to_list(length=1000)
    attendance_pct = round(100 * sum(row["status"] == "present" for row in attendances) / len(attendances), 2) if attendances else None
    grade_pct = round(100 * sum(row["score"] for row in grades) / sum(row["max_score"] for row in grades), 2) if grades else None
    return {"role": "student", "student": public_doc(user), "enrolled_courses": enrollment_count,
            "course_details": [public_doc(row) for row in await db.courses.find({"_id": {"$in": course_ids}}).to_list(length=100)],
            "attendance_percentage": attendance_pct, "overall_grade_percentage": grade_pct,
            "upcoming_announcements": await db.announcements.count_documents(
                {"is_active": True, "audience": {"$in": ["all", "students"]}})}


@app.get("/api/v1/admin/overview", tags=["Administration"])
async def admin_overview(_: dict = Depends(require_admin)):
    require_database()
    return {
        "students_by_department": await db.users.aggregate([
            {"$match": {"role": "student", "is_active": True}},
            {"$group": {"_id": {"$ifNull": ["$department", "Unassigned"]}, "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]).to_list(length=100),
        "course_enrollment_counts": await db.enrollments.aggregate([
            {"$group": {"_id": "$course_id", "enrolled": {"$sum": 1}}},
            {"$sort": {"enrolled": -1}}, {"$limit": 100},
        ]).to_list(length=100),
    }


@app.exception_handler(PyMongoError)
async def database_error_handler(_, exc: PyMongoError):
    return JSONResponse(status_code=503, content={"detail": "A database operation failed"})

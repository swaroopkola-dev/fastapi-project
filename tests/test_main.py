from fastapi.testclient import TestClient
import pytest
import main
from fastapi import HTTPException


@pytest.fixture()
def client():
    # Smoke tests intentionally run without a live database.
    main.db = None
    with TestClient(main.app) as test_client:
        yield test_client


def test_root_has_docs_and_health_links(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_health_reports_degraded_without_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_student_listing_requires_authentication(client):
    assert client.get("/api/v1/students").status_code == 401


def test_course_listing_requires_authentication(client):
    assert client.get("/api/v1/courses").status_code == 401


def test_invalid_ids_are_rejected():
    with pytest.raises(HTTPException) as exc:
        main.object_id("not-an-object-id")
    assert exc.value.status_code == 400


def test_password_hash_and_verify():
    hashed = main.hash_password("GoodPassword123!")
    assert hashed != "GoodPassword123!"
    assert main.verify_password("GoodPassword123!", hashed)
    assert not main.verify_password("WrongPassword!", hashed)


def test_public_doc_drops_password_hash():
    result = main.public_doc({"_id": "fake-id", "email": "student@example.com", "hashed_password": "secret"})
    assert result["id"] == "fake-id"
    assert "hashed_password" not in result

def test_app_has_api_routes():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/health" in paths
    assert "/api/v1/comment-screening" in paths
    assert "/api/v1/jobs/{job_id}" in paths

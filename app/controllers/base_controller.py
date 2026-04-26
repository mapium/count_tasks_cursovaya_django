import requests
from django.conf import settings


class BaseController:
    """Единая точка для API URL, заголовков и HTTP-запросов."""

    API_PREFIX = getattr(settings, "API_PREFIX", "/api/v1")
    TIMEOUT = getattr(settings, "API_TIMEOUT", 30)

    @classmethod
    def build_url(cls, path: str) -> str:
        base = settings.BASE_URL.rstrip("/")
        prefix = str(cls.API_PREFIX).strip("/")
        clean_path = path.strip("/")
        if prefix:
            return f"{base}/{prefix}/{clean_path}"
        return f"{base}/{clean_path}"

    @staticmethod
    def build_headers(access_token=None, content_type: str = "application/json"):
        headers = {"Content-Type": content_type}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    @classmethod
    def request(cls, method: str, path: str, **kwargs):
        return requests.request(
            method=method,
            url=cls.build_url(path),
            timeout=cls.TIMEOUT,
            **kwargs,
        )

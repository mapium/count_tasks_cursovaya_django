from django.shortcuts import redirect


class RequireAccessTokenMiddleware:
    """Блокирует доступ к защищенным маршрутам без активного access token."""

    PUBLIC_PREFIXES = (
        "/auth/",
        "/no-access/",
        "/static/",
        "/admin/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"
        if path == "/favicon.ico" or path.startswith(self.PUBLIC_PREFIXES):
            return self.get_response(request)

        if not request.session.get("access_token"):
            return redirect("no_access")

        return self.get_response(request)

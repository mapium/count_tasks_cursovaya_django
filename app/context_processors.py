import base64
import json


def _username_from_access_token(token):
    """Извлекает `sub` из JWT access token без проверки подписи.
    При невалидном токене или ошибке декодирования возвращает пустую строку.
    """
    if not token or token.count(".") < 2:
        return ""
    try:
        payload_part = token.split(".")[1]
        padding = "=" * (-len(payload_part) % 4)
        decoded = base64.urlsafe_b64decode(payload_part + padding).decode("utf-8")
        payload = json.loads(decoded)
        return str(payload.get("sub") or "").strip()
    except Exception:
        return ""


def current_user_ui(request):
    """Формирует данные пользователя для общего UI-контекста шаблонов.
    Берет роль из сессии, логин из сессии/JWT и возвращает безопасные значения по умолчанию.
    """
    role_map = {
        "admin": "Администратор",
        "manager": "Менеджер подразделения",
        "employee": "Сотрудник",
    }
    scope = request.session.get("ui_user_scope")
    role_label = role_map.get(scope, "Не определена")
    username = (request.session.get("username") or "").strip()
    if not username:
        username = _username_from_access_token(request.session.get("access_token"))
        if username:
            request.session["username"] = username
    if not username:
        username = "Гость"

    return {
        "current_username": username,
        "current_role_label": role_label,
        "current_user_scope": scope or "employee",
    }

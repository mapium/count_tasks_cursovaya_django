import requests
from core import settings

base_url = settings.BASE_URL


def _page_items(payload):
    """Достаёт список из ответа fastapi-pagination / плоского JSON."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "data"):
        chunk = payload.get(key)
        if isinstance(chunk, list):
            return chunk
    return []


class EmployeeController:
    @staticmethod
    def get_employees(access_token=None):
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        try:
            response = requests.get(
                f"{base_url}/api/v1/employees",
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            return [], f"Нет связи с API: {exc}"

        try:
            data = response.json()
        except ValueError:
            return [], f"Некорректный JSON от API (код {response.status_code})"

        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else str(data)
            if isinstance(detail, list):
                detail = str(detail)
            return [], detail or f"Ошибка API: {response.status_code}"

        return _page_items(data), None

    @staticmethod
    def update_employee(employee_id, payload, access_token=None):
        """PUT /employees/{id} — тело JSON (частичное обновление)."""
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            return requests.put(
                f"{base_url}/api/v1/employees/{int(employee_id)}",
                json=payload,
                headers=headers,
                timeout=30,
            )
        except (requests.RequestException, ValueError) as exc:
            return None

    @staticmethod
    def create_employee(payload, access_token=None):
        """POST /employees — тело JSON (EmployeeCreate)."""
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            return requests.post(
                f"{base_url}/api/v1/employees",
                json=payload,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException:
            return None

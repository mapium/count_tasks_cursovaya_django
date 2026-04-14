import requests
from core import settings

from app.controllers.employee_controller import _page_items

base_url = settings.BASE_URL


class DepartmentController:
    """Справочник подразделений с API (GET /departments без авторизации)."""

    _PAGE_SIZE = 100  # лимит валидации API: size <= 100

    @staticmethod
    def get_department_name_map():
        """
        Возвращает ({id: название}, None) или ({}, сообщение_об_ошибке).
        """
        name_by_id = {}
        page = 1

        while True:
            try:
                response = requests.get(
                    f"{base_url}/api/v1/departments",
                    params={"page": page, "size": DepartmentController._PAGE_SIZE},
                    timeout=30,
                )
            except requests.RequestException as exc:
                return name_by_id if name_by_id else {}, f"Нет связи с API (отделы): {exc}"

            try:
                data = response.json()
            except ValueError:
                return name_by_id if name_by_id else {}, f"Некорректный JSON отделов (код {response.status_code})"

            if not response.ok:
                detail = data.get("detail") if isinstance(data, dict) else str(data)
                if isinstance(detail, list):
                    detail = str(detail)
                err = detail or f"Ошибка API отделов: {response.status_code}"
                return name_by_id if name_by_id else {}, err

            chunk = _page_items(data)
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                did = row.get("id")
                if did is not None and row.get("name"):
                    name_by_id[did] = row["name"]

            if len(chunk) < DepartmentController._PAGE_SIZE:
                break
            page += 1

        return name_by_id, None

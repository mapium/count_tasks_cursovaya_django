import requests

from app.controllers.base_controller import BaseController
from app.controllers.employee_controller import _page_items


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
                response = BaseController.request(
                    "get",
                    "departments",
                    params={"page": page, "size": DepartmentController._PAGE_SIZE},
                    headers=BaseController.build_headers(),
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

    @staticmethod
    def get_departments(access_token=None):
        try:
            response = BaseController.request(
                "get",
                "departments",
                params={"page": 1, "size": DepartmentController._PAGE_SIZE},
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException as exc:
            return [], f"Нет связи с API (отделы): {exc}"
        try:
            data = response.json()
        except ValueError:
            return [], f"Некорректный JSON отделов (код {response.status_code})"
        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else str(data)
            return [], detail or f"Ошибка API отделов: {response.status_code}"
        return _page_items(data), None

    @staticmethod
    def create_department(payload, access_token=None):
        try:
            return BaseController.request(
                "post",
                "departments",
                json=payload,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException:
            return None

    @staticmethod
    def update_department(department_id, payload, access_token=None):
        try:
            return BaseController.request(
                "put",
                f"departments/{int(department_id)}",
                json=payload,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def delete_department(department_id, access_token=None):
        try:
            return BaseController.request(
                "delete",
                f"departments/{int(department_id)}",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError):
            return None

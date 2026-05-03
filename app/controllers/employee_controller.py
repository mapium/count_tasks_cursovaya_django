import requests
from app.controllers.base_controller import BaseController


def _page_items(payload):
    """Нормализует payload списка сотрудников к обычному list.
    Поддерживает плоский список и обертки `items/results/data`, иначе возвращает пустой список.
    """
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
        """Запрашивает полный список сотрудников.
        Возвращает `(employees, error)` с текстом ошибки при проблемах связи, JSON или статусе API.
        """
        try:
            response = BaseController.request(
                "get",
                "employees",
                headers=BaseController.build_headers(access_token=access_token),
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
    def get_manager_department_employees(access_token=None):
        """Получает сотрудников подразделения текущего менеджера.
        Возвращает `(employees, error)` в едином формате обработки ошибок API.
        """
        try:
            response = BaseController.request(
                "get",
                "employees/manager-department",
                headers=BaseController.build_headers(access_token=access_token),
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
    def get_my_department_employees(access_token=None):
        """Получает сотрудников подразделения текущего пользователя.
        Возвращает `(employees, error)` и скрывает детали HTTP-исключений за текстом ошибки.
        """
        try:
            response = BaseController.request(
                "get",
                "employees/my-department",
                headers=BaseController.build_headers(access_token=access_token),
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
        """Обновляет данные сотрудника через обычный или manager endpoint.
        Опционально переключает путь по флагу `_manager_mode`, затем отправляет JSON payload.
        """
        try:
            manager_mode = bool(payload.pop("_manager_mode", False))
            path = f"employees/manager-department/{int(employee_id)}" if manager_mode else f"employees/{int(employee_id)}"
            return BaseController.request(
                "put",
                path,
                json=payload,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError) as exc:
            return None

    @staticmethod
    def create_employee(payload, access_token=None):
        """Создает сотрудника через endpoint admin/manager в зависимости от `_manager_mode`.
        Удаляет служебный флаг из payload и возвращает raw ответ API или `None`.
        """
        try:
            endpoint = "employees/manager-department" if payload.get("_manager_mode") else "employees"
            payload = {k: v for k, v in payload.items() if k != "_manager_mode"}
            return BaseController.request(
                "post",
                endpoint,
                json=payload,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException:
            return None

    @staticmethod
    def delete_employee(employee_id, access_token=None):
        """Удаляет сотрудника через `DELETE /employees/{id}`.
        Возвращает raw ответ API либо `None` при ошибке соединения.
        """
        try:
            path = f"employees/{int(employee_id)}"
            return BaseController.request(
                "delete",
                path,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException:
            return None

    @staticmethod
    def delete_manager_department_employee(employee_id, access_token=None):
        """Удаляет сотрудника через manager endpoint своего подразделения.
        Используется для ограничения удаления в рамках прав менеджера.
        """
        try:
            return BaseController.request(
                "delete",
                f"employees/manager-department/{int(employee_id)}",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException:
            return None

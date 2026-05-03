import requests
from app.controllers.base_controller import BaseController


def _page_items(payload):
    """Приводит ответ API задач к списку элементов.
    Поддерживает list и словари с ключами `items/results/data`.
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


class TasksController:
    @staticmethod
    def create_task(payload, access_token=None):
        """Создает задачу через `POST /tasks` с JSON payload.
        Возвращает raw ответ API или `None`, если запрос не выполнен.
        """
        try:
            return BaseController.request(
                "post",
                "tasks",
                json=payload,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException:
            return None

    @staticmethod
    def get_current_tasks(access_token=None):
        """Получает задачи текущего подразделения (`tasks/my-department`).
        Возвращает `(tasks, error)` с унифицированной обработкой ошибок API/JSON.
        """
        try:
            response = BaseController.request(
                "get",
                "tasks/my-department",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException as exc:
            return [], f"Нет связи с API задач: {exc}"

        try:
            data = response.json()
        except ValueError:
            return [], f"Некорректный JSON задач (код {response.status_code})"

        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else str(data)
            if isinstance(detail, list):
                detail = str(detail)
            return [], detail or f"Ошибка API задач: {response.status_code}"

        return _page_items(data), None

    @staticmethod
    def get_my_tasks(access_token=None):
        """Получает задачи текущего пользователя (`tasks/my`).
        Возвращает `(tasks, error)` и текст причины при неуспешном ответе API.
        """
        try:
            response = BaseController.request(
                "get",
                "tasks/my",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException as exc:
            return [], f"Нет связи с API задач: {exc}"

        try:
            data = response.json()
        except ValueError:
            return [], f"Некорректный JSON задач (код {response.status_code})"

        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else str(data)
            if isinstance(detail, list):
                detail = str(detail)
            return [], detail or f"Ошибка API задач: {response.status_code}"

        return _page_items(data), None

    @staticmethod
    def get_all_tasks(access_token=None):
        """Запрашивает агрегированный список задач по подразделениям (`GET /tasks`).
        Разворачивает вложенный формат в плоский список и возвращает флаг ошибки доступа 403.
        """
        try:
            response = BaseController.request(
                "get",
                "tasks",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except requests.RequestException as exc:
            return [], f"Нет связи с API задач: {exc}", False

        try:
            data = response.json()
        except ValueError:
            return [], f"Некорректный JSON задач (код {response.status_code})", False

        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else str(data)
            if isinstance(detail, list):
                detail = str(detail)
            return [], detail or f"Ошибка API задач: {response.status_code}", response.status_code == 403

        departments = data.get("departments") if isinstance(data, dict) else None
        if not isinstance(departments, list):
            return [], "Некорректный формат ответа /tasks", False

        flat = []
        for group in departments:
            if not isinstance(group, dict):
                continue
            department_name = group.get("department_name")
            department_id = group.get("department_id")
            for task in group.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                row = dict(task)
                if department_name and not row.get("department"):
                    row["department"] = department_name
                if department_id is not None and row.get("department_id") is None:
                    row["department_id"] = department_id
                flat.append(row)
        return flat, None, False

    @staticmethod
    def update_task_status(task_id, status_name, access_token=None):
        """Меняет статус задачи через `PATCH /tasks/{id}/status`.
        Отправляет `status_name` и возвращает `None` при сетевой ошибке или неверном id.
        """
        try:
            return BaseController.request(
                "patch",
                f"tasks/{int(task_id)}/status",
                json={"status_name": str(status_name)},
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def update_task(task_id, payload, access_token=None):
        """Полностью обновляет задачу через `PUT /tasks/{id}`.
        При ошибках соединения/валидации id возвращает `None`.
        """
        try:
            return BaseController.request(
                "put",
                f"tasks/{int(task_id)}",
                json=payload,
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def add_comment(task_id, comment_text, access_token=None):
        """Добавляет комментарий к задаче (`POST /tasks/{id}/comments`).
        Формирует JSON с `comment_text` и возвращает raw ответ API.
        """
        try:
            return BaseController.request(
                "post",
                f"tasks/{int(task_id)}/comments",
                json={"comment_text": str(comment_text)},
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def get_task_comments(task_id, access_token=None):
        """Загружает список комментариев задачи (`GET /tasks/{id}/comments`).
        Возвращает `(comments, error)` и валидирует, что тело ответа является списком.
        """
        try:
            response = BaseController.request(
                "get",
                f"tasks/{int(task_id)}/comments",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError) as exc:
            return [], f"Нет связи с API комментариев: {exc}"

        try:
            data = response.json()
        except ValueError:
            return [], f"Некорректный JSON комментариев (код {response.status_code})"

        if not response.ok:
            detail = data.get("detail") if isinstance(data, dict) else str(data)
            if isinstance(detail, list):
                detail = str(detail)
            return [], detail or f"Ошибка API комментариев: {response.status_code}"

        if not isinstance(data, list):
            return [], "Некорректный формат ответа комментариев."
        return data, None

    @staticmethod
    def delete_task(task_id, access_token=None):
        """Удаляет задачу через `DELETE /tasks/{id}`.
        Возвращает raw HTTP-ответ API либо `None` при исключении.
        """
        try:
            return BaseController.request(
                "delete",
                f"tasks/{int(task_id)}",
                headers=BaseController.build_headers(access_token=access_token),
            )
        except (requests.RequestException, ValueError):
            return None
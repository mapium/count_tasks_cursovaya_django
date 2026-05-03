from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from openpyxl import Workbook

from app.controllers.department_controller import DepartmentController
from app.controllers.employee_controller import EmployeeController
from app.controllers.tasks_controller import TasksController
from app.controllers.user_controller import UserController

KANBAN_COLUMN_TO_STATUS_NAME = {
    "planned": "К выполнению",
    "in_progress": "В работе",
    "review": "На проверке",
    "done": "Выполнено",
}
STATUS_NAME_TO_KANBAN_COLUMN = {
    value.lower(): key for key, value in KANBAN_COLUMN_TO_STATUS_NAME.items()
}
STATUS_SLUG_TO_ID = {
    "planned": 1,
    "in_progress": 2,
    "review": 3,
    "done": 4,
    "overdue": 5,
}
STATUS_NAME_TO_ID = {
    "К выполнению": 1,
    "В работе": 2,
    "На проверке": 3,
    "Выполнено": 4,
    "Просрочено": 5,
}


def _extract_response_error(response):
    """Извлекает человекочитаемую ошибку из ответа API.
    Пытается взять detail/error из JSON, иначе возвращает текст ответа или код статуса.
    """
    if response is None:
        return "нет ответа"
    try:
        data = response.json()
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, list):
            detail = str(detail)
        return detail or (data.get("error") if isinstance(data, dict) else str(data))
    except Exception:
        return response.text or f"Код {response.status_code}"


def _get_required_token(request, redirect_name):
    """Достает access token из сессии для защищенных операций.
    При отсутствии токена пишет сообщение об ошибке и возвращает redirect на указанную страницу.
    """
    token = request.session.get("access_token")
    if token:
        return token
    messages.error(request, "Войдите в систему (нужен токен для API).")
    return redirect(redirect_name)


def _is_fuzzy_last_name_match(last_name, query):
    """Проверяет совпадение фамилии с поисковым запросом с учетом неточных совпадений.
    Использует прямое вхождение и SequenceMatcher для tolerance к опечаткам.
    """
    candidate = (last_name or "").strip().lower()
    needle = (query or "").strip().lower()
    if not needle:
        return True
    if needle in candidate:
        return True
    if not candidate:
        return False
    if SequenceMatcher(None, candidate, needle).ratio() >= 0.7:
        return True
    candidate_parts = candidate.split()
    return any(SequenceMatcher(None, part, needle).ratio() >= 0.75 for part in candidate_parts)


def _default_employee_form(departments_options):
    """Возвращает стартовые значения формы сотрудника.
    Если есть отделы, подставляет первый department_id по умолчанию.
    """
    return {
        "employee_id": "",
        "first_name": "",
        "last_name": "",
        "middle_name": "",
        "phone_number": "",
        "email": "",
        "passport_data": "",
        "inn": "",
        "snils": "",
        "department_id": str(departments_options[0][0]) if departments_options else "",
        "is_active": True,
    }


def _resolve_user_scope(request, access_token):
    """Определяет UI-роль пользователя: admin, manager или employee.
    Кэширует результат в сессии и возвращает ошибку API, если роль определялась через fallback.
    """
    cached_scope = request.session.get("ui_user_scope")
    if cached_scope in {"admin", "manager", "employee"}:
        return cached_scope, None

    admin_employees, admin_error = EmployeeController.get_employees(access_token=access_token)
    if admin_error is None:
        request.session["ui_user_scope"] = "admin"
        return "admin", None

    manager_employees, manager_error = EmployeeController.get_manager_department_employees(
        access_token=access_token
    )
    if manager_error is None:
        request.session["ui_user_scope"] = "manager"
        return "manager", None

    request.session["ui_user_scope"] = "employee"
    return "employee", admin_error or manager_error


def _load_dashboard_tasks(access_token, scope):
    """Загружает задачи для дашборда в зависимости от роли пользователя.
    Для admin берет все задачи, для manager/employee — профильные endpoint’ы.
    """
    if scope == "admin":
        tasks, error, _ = TasksController.get_all_tasks(access_token=access_token)
        return tasks, error
    if scope == "manager":
        return TasksController.get_current_tasks(access_token=access_token)
    return TasksController.get_my_tasks(access_token=access_token)


def _load_tasks_for_scope(request, access_token, scope):
    """Определяет активный task_scope и набор задач для текущего запроса.
    Для employee поддерживает переключение между своими задачами и задачами подразделения.
    """
    task_scope = (request.GET.get("task_scope") or "").strip().lower()
    if scope == "employee" and task_scope == "department":
        return task_scope, TasksController.get_current_tasks(access_token=access_token)
    tasks, error = _load_dashboard_tasks(access_token, scope)
    if scope == "employee":
        task_scope = "my"
    return task_scope, (tasks, error)


def _parse_int(value):
    """Преобразует значение в целое число без выброса исключения.
    Возвращает None, если конвертация невозможна.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _department_field_errors_from_api(api_error):
    """Маппит текст ошибки API на поля формы подразделения.
    Возвращает словарь ошибок для name, description или обоих полей.
    """
    text = (api_error or "").strip()
    lowered = text.lower()
    if not lowered:
        return {}
    if "name" in lowered or "назван" in lowered:
        return {"name": text}
    if "description" in lowered or "описан" in lowered:
        return {"description": text}
    return {"name": text, "description": text}


def _filter_tasks_by_period(tasks, period):
    """Фильтрует список задач по текущему месяцу или году.
    Ориентируется на planned end/start date и пропускает записи с невалидной датой.
    """
    if period not in {"month", "year"}:
        return tasks

    today = date.today()
    filtered = []
    for row in tasks:
        if not isinstance(row, dict):
            continue
        planned_end = row.get("planned_end_date")
        planned_start = row.get("planned_start_date")
        raw_date = planned_end or planned_start
        if not raw_date:
            continue
        try:
            task_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue

        if period == "month" and task_date.year == today.year and task_date.month == today.month:
            filtered.append(row)
        elif period == "year" and task_date.year == today.year:
            filtered.append(row)
    return filtered


def _safe_iso_date(raw_value):
    """Безопасно парсит дату из строки формата ISO с возможным временем.
    Возвращает date или None, если значение пустое/некорректное.
    """
    if not raw_value:
        return None
    try:
        value = str(raw_value).strip()
        if "T" in value:
            value = value.split("T", 1)[0]
        elif " " in value:
            value = value.split(" ", 1)[0]
        return date.fromisoformat(value)
    except ValueError:
        return None


def _task_report_date(task_row):
    """Выбирает базовую дату задачи для отчетов.
    Приоритет: actual_end_date, затем planned_end_date, затем planned_start_date.
    """
    return (
        _safe_iso_date(task_row.get("actual_end_date"))
        or _safe_iso_date(task_row.get("planned_end_date"))
        or _safe_iso_date(task_row.get("planned_start_date"))
    )


def _is_task_done(task_row):
    """Проверяет, имеет ли задача статус «Выполнено».
    Сравнение выполняется регистронезависимо после нормализации строки статуса.
    """
    return (task_row.get("status") or "").strip().lower() == "выполнено"


def _resolve_task_assignment(
    access_token,
    scope,
    assignee_user_id,
    assignee_name,
    fallback_assignee_id,
    fallback_department_id,
):
    """Подбирает согласованные assignee_id и department_id задачи по данным сотрудников.
    Ищет сначала по user_id, затем по ФИО исполнителя; при промахе возвращает fallback-значения.
    """
    if scope == "admin":
        employees, employees_error = EmployeeController.get_employees(access_token=access_token)
    elif scope == "manager":
        employees, employees_error = EmployeeController.get_manager_department_employees(access_token=access_token)
    else:
        return fallback_assignee_id, fallback_department_id
    if employees_error:
        return fallback_assignee_id, fallback_department_id

    target_assignee_id = _parse_int(assignee_user_id)
    target_assignee_name = (assignee_name or "").strip().lower()

    for row in employees:
        if not isinstance(row, dict):
            continue
        candidate_user_id = _parse_int(row.get("user_id"))
        candidate_employee_id = _parse_int(row.get("id"))
        candidate_assignee_id = (
            candidate_user_id if candidate_user_id is not None else candidate_employee_id
        )
        dep_id = _parse_int(row.get("department_id"))
        if dep_id is None or candidate_assignee_id is None:
            continue

        if target_assignee_id is not None and target_assignee_id in {
            candidate_user_id,
            candidate_employee_id,
        }:
            return candidate_assignee_id, dep_id

        if target_assignee_name:
            full_name = " ".join(
                part
                for part in (
                    row.get("last_name") or "",
                    row.get("first_name") or "",
                    row.get("middle_name") or "",
                )
                if part
            ).strip().lower()
            if full_name and full_name == target_assignee_name:
                return candidate_assignee_id, dep_id

    return fallback_assignee_id, fallback_department_id


def _resolve_task_department_id(access_token, scope, assignee_user_id, fallback_department_id):
    """Определяет корректный department_id задачи по исполнителю.
    Использует выборку сотрудников в рамках роли и возвращает fallback при отсутствии совпадения.
    """
    _, department_id = _resolve_task_assignment(
        access_token=access_token,
        scope=scope,
        assignee_user_id=assignee_user_id,
        assignee_name="",
        fallback_assignee_id=_parse_int(assignee_user_id),
        fallback_department_id=fallback_department_id,
    )
    return department_id


def _xlsx_response(workbook, filename):
    """Упаковывает openpyxl workbook в HTTP-ответ для скачивания.
    Устанавливает MIME-тип XLSX и заголовок Content-Disposition.
    """
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


def _build_tasks_report_excel(department_rows, period_label):
    """Строит Excel-отчет по выполнению задач в разрезе подразделений.
    Записывает свод по статусам задач и процент выполнения для каждого отдела.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Выполнение задач по отделам"
    ws.append(["Отчет", "Выполнение задач подразделений"])
    ws.append(["Период", period_label])
    ws.append([])
    ws.append(
        [
            "Подразделение",
            "Всего задач",
            "К выполнению",
            "В работе",
            "На проверке",
            "Выполнено",
            "Просрочено",
            "Процент выполнения, %",
        ]
    )

    for row in department_rows:
        if not isinstance(row, dict):
            continue
        ws.append(
            [
                row.get("department") or "Без подразделения",
                row.get("total") or 0,
                row.get("planned") or 0,
                row.get("in_progress") or 0,
                row.get("review") or 0,
                row.get("done") or 0,
                row.get("overdue") or 0,
                row.get("done_percent") or 0,
            ]
        )

    if not department_rows:
        ws.append(["Нет данных", 0, 0, 0, 0, 0, 0, 0])

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 24
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 24
    return wb


def _build_employees_report_excel(employees, department_name_map):
    """Строит Excel-отчет по численности сотрудников по подразделениям.
    Группирует сотрудников по отделам и добавляет итоговую строку по всей компании.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Численность сотрудников"
    ws.append(["Отчет", "Численность сотрудников предприятия"])
    ws.append(["Сформировано", str(date.today())])
    ws.append([])
    ws.append(["Подразделение", "Количество сотрудников"])

    by_department = defaultdict(int)
    total = 0
    for row in employees:
        if not isinstance(row, dict):
            continue
        total += 1
        dep_id = row.get("department_id")
        dep_name = department_name_map.get(dep_id) if dep_id is not None else None
        by_department[dep_name or "Без подразделения"] += 1

    for dep_name in sorted(by_department.keys(), key=lambda item: item.lower()):
        ws.append([dep_name, by_department[dep_name]])
    ws.append([])
    ws.append(["Итого", total])

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 24
    return wb


def auth(request):
    """Обрабатывает вход пользователя и сохранение сессионных данных.
    На успехе сохраняет токен/логин и перенаправляет в дашборд, иначе показывает ошибку.
    """
    auth_mode = (request.GET.get("mode") or request.POST.get("mode") or "login").strip().lower()
    if auth_mode not in {"login", "register"}:
        auth_mode = "login"
    context = {"auth_mode": auth_mode, "field_errors": {}}
    if request.method != "POST":
        return render(request, "auth.html", context)

    username = (request.POST.get("username") or "").strip()
    password = (request.POST.get("password") or "").strip()
    field_errors = {}

    if not username:
        context["error"] = "Введите логин"
        field_errors["username"] = "Поле обязательно."
        context["field_errors"] = field_errors
        context["form_username"] = username
        return render(request, "auth.html", context)

    if not password:
        context["error"] = "Введите пароль"
        field_errors["password"] = "Поле обязательно."
        context["field_errors"] = field_errors
        context["form_username"] = username
        return render(request, "auth.html", context)

    if auth_mode == "register":
        confirm_password = (request.POST.get("confirm_password") or "").strip()
        if not confirm_password:
            context["error"] = "Подтвердите пароль."
            field_errors["confirm_password"] = "Поле обязательно."
            context["field_errors"] = field_errors
            context["form_username"] = username
            return render(request, "auth.html", context)
        if password != confirm_password:
            context["error"] = "Пароли не совпадают."
            field_errors["confirm_password"] = "Пароли не совпадают."
            context["field_errors"] = field_errors
            context["form_username"] = username
            return render(request, "auth.html", context)
        response = UserController.register_user(username=username, password=password)
        if response is not None and 200 <= response.status_code < 300:
            messages.success(request, "Регистрация успешна. Теперь войдите в систему.")
            return redirect(f"{request.path}?mode=login")
        status = response.status_code if response is not None else "нет ответа"
        context["error"] = f"Ошибка регистрации: {status}"
    else:
        response = UserController.login_user(username=username, password=password)
        if response is not None and 200 <= response.status_code < 300:
            try:
                data = response.json()
            except Exception:
                data = {}
            request.session["is_authenticated"] = True
            request.session["username"] = username
            if data.get("access_token"):
                request.session["access_token"] = data["access_token"]
            request.session.pop("ui_user_scope", None)
            return redirect("dashboard")
        status = response.status_code if response is not None else "нет ответа"
        context["error"] = f"Ошибка авторизации: {status}"

    context["form_username"] = username
    error_message = _extract_response_error(response)
    if error_message and error_message != "нет ответа":
        context["error_message"] = error_message
    return render(request, "auth.html", context)


def dashboard(request):
    """Рендерит канбан-доску задач с фильтрами и статистикой.
    Подгружает задачи по роли, применяет фильтры и готовит данные колонок для шаблона.
    """
    token = request.session.get("access_token")
    scope, scope_error = _resolve_user_scope(request, token)
    task_scope, (tasks, tasks_error) = _load_tasks_for_scope(request, token, scope)
    selected_department = (request.GET.get("department") or "").strip()
    selected_assignee = (request.GET.get("assignee") or "").strip()
    selected_period = (request.GET.get("period") or "all").strip().lower()
    if selected_period not in {"all", "month", "year"}:
        selected_period = "all"
    if scope == "employee":
        selected_assignee = ""

    departments_filter_options = []
    department_filter_label = "Все подразделения"
    if scope == "admin":
        department_pairs = {}
        for row in tasks:
            if not isinstance(row, dict):
                continue
            dep_id = row.get("department_id")
            dep_name = (row.get("department") or "").strip()
            if dep_id is None:
                continue
            department_pairs[dep_id] = dep_name or f"Отдел #{dep_id}"
        departments_filter_options = sorted(
            department_pairs.items(),
            key=lambda x: ((x[1] or "").lower(), x[0]),
        )
        if selected_department:
            try:
                selected_department_id = int(selected_department)
                tasks = [
                    row
                    for row in tasks
                    if isinstance(row, dict) and row.get("department_id") == selected_department_id
                ]
            except ValueError:
                selected_department = ""
    else:
        department_filter_label = "Моё подразделение"

    assignee_pairs = {}
    for row in tasks:
        if not isinstance(row, dict):
            continue
        assignee_name = (row.get("assignee") or "").strip()
        if not assignee_name:
            continue
        assignee_pairs[assignee_name] = assignee_name
    assignee_filter_options = sorted(assignee_pairs.values(), key=lambda x: x.lower())
    if selected_assignee:
        tasks = [
            row
            for row in tasks
            if isinstance(row, dict) and (row.get("assignee") or "").strip() == selected_assignee
        ]
    if selected_period in {"month", "year"}:
        tasks = _filter_tasks_by_period(tasks, selected_period)

    grouped = {"planned": [], "in_progress": [], "review": [], "done": []}
    today = date.today()
    for row in tasks:
        if not isinstance(row, dict):
            continue
        status_name = (row.get("status") or "").strip()
        status_key = STATUS_NAME_TO_KANBAN_COLUMN.get(status_name.lower(), "planned")
        planned_end_date = row.get("planned_end_date") or ""
        is_overdue = False
        if status_key == "in_progress" and planned_end_date:
            try:
                is_overdue = date.fromisoformat(str(planned_end_date)) < today
            except ValueError:
                is_overdue = False

        task_ui = {
            "id": row.get("id"),
            "title": row.get("title") or "Без названия",
            "assignee": row.get("assignee") or "Неизвестно",
            "department": row.get("department") or "",
            "planned_end_date": planned_end_date,
            "priority": row.get("priority") or "",
            "status_name": status_name,
            "is_overdue": is_overdue,
        }
        grouped[status_key].append(task_ui)

    counts = {key: len(value) for key, value in grouped.items()}
    overdue_count = sum(1 for task in grouped["in_progress"] if task.get("is_overdue"))
    stats = {
        "total": len(tasks),
        "done": counts["done"],
        "overdue": overdue_count,
        "review": counts['review'],
        "in_progress": counts["in_progress"],
    }

    return render(
        request,
        "dashboard.html",
        {
            "tasks_grouped": grouped,
            "counts": counts,
            "stats": stats,
            "tasks_error": tasks_error,
            "scope_error": scope_error if tasks_error else None,
            "column_to_status_name": KANBAN_COLUMN_TO_STATUS_NAME,
            "user_scope": scope,
            "departments_filter_options": departments_filter_options,
            "department_filter_label": department_filter_label,
            "selected_department": selected_department,
            "assignee_filter_options": assignee_filter_options,
            "selected_assignee": selected_assignee,
            "selected_period": selected_period,
            "task_scope": task_scope,
            "active_page": "dashboard",
        },
    )


def task_detail(request, task_id):
    """Показывает карточку задачи и обрабатывает действия в ней.
    Поддерживает добавление комментария, редактирование и удаление с проверкой прав.
    """
    token = request.session.get("access_token")
    scope, _ = _resolve_user_scope(request, token)
    task_scope, (tasks, tasks_error) = _load_tasks_for_scope(request, token, scope)

    if tasks_error:
        messages.error(request, f"Не удалось загрузить задачу: {tasks_error}")
        return redirect("dashboard")

    selected = None
    for row in tasks:
        if isinstance(row, dict) and row.get("id") == int(task_id):
            selected = row
            break

    if not selected:
        messages.error(request, "Задача не найдена или недоступна для вашей роли.")
        return redirect("dashboard")

    current_username = (request.session.get("username") or "").strip()
    task_creator = (selected.get("creator") or "").strip()
    task_assignee = (selected.get("assignee") or "").strip()
    is_admin = scope == "admin"
    is_manager = scope == "manager"
    is_employee = scope == "employee"
    can_comment = is_admin or current_username in {task_creator, task_assignee}
    can_edit = (
        is_admin
        or is_manager
        or (is_employee and current_username and current_username in {task_creator, task_assignee})
    )
    if is_admin:
        edit_mode = "admin_full"
    elif is_manager:
        edit_mode = "manager"
    else:
        edit_mode = "limited"
    comment_form_data = {"comment_text": ""}
    comment_field_errors = {}
    comments, comments_error = TasksController.get_task_comments(task_id, access_token=token)
    if comments_error:
        messages.warning(request, f"Не удалось загрузить комментарии: {comments_error}")
        comments = selected.get("comments") if isinstance(selected.get("comments"), list) else []
    selected["comments"] = [row for row in comments if isinstance(row, dict)]
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "comment":
            if not can_comment:
                messages.error(request, "У вас нет прав на добавление комментария к этой задаче.")
                return redirect("task_detail", task_id=task_id)
            comment_text = (request.POST.get("comment_text") or "").strip()
            comment_form_data["comment_text"] = comment_text
            if not comment_text:
                messages.error(request, "Комментарий не может быть пустым.")
                comment_field_errors["comment_text"] = "Поле обязательно."
                return render(
                    request,
                    "task_detail.html",
                    {
                        "task": selected,
                        "task_is_overdue": False,
                        "task_scope": task_scope,
                        "can_comment": can_comment,
                        "can_edit": can_edit,
                        "edit_mode": edit_mode,
                        "current_user_scope": scope,
                        "comment_form_data": comment_form_data,
                        "comment_field_errors": comment_field_errors,
                        "active_page": "dashboard",
                    },
                )
            response = TasksController.add_comment(task_id, comment_text, access_token=token)
            if response is None:
                messages.error(request, "Нет связи с API при добавлении комментария.")
            elif 200 <= response.status_code < 300:
                messages.success(request, "Комментарий добавлен.")
            else:
                messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
            return redirect("task_detail", task_id=task_id)

        if action == "edit":
            if not can_edit:
                messages.error(request, "У вас нет прав на редактирование этой задачи.")
                return redirect("task_detail", task_id=task_id)
            status_name = (request.POST.get("status_name") or selected.get("status") or "").strip()
            status_id = STATUS_NAME_TO_ID.get(status_name, selected.get("status_id"))
            payload = {
                "status_id": int(status_id) if status_id is not None else None,
                "actual_start_date": (request.POST.get("actual_start_date") or selected.get("actual_start_date") or ""),
                "actual_end_date": (request.POST.get("actual_end_date") or selected.get("actual_end_date") or ""),
            }
            if edit_mode in {"admin_full", "manager"}:
                payload.update(
                    {
                        "title": (request.POST.get("title") or selected.get("title") or "").strip(),
                        "description": (request.POST.get("description") or selected.get("description") or "").strip(),
                        "priority": (request.POST.get("priority") or selected.get("priority") or "малый").strip(),
                    }
                )
            if edit_mode == "manager":
                resolved_assignee_id, resolved_department_id = _resolve_task_assignment(
                    access_token=token,
                    scope=scope,
                    assignee_user_id=selected.get("assignee_id"),
                    assignee_name=selected.get("assignee"),
                    fallback_assignee_id=_parse_int(selected.get("assignee_id")),
                    fallback_department_id=_parse_int(selected.get("department_id")),
                )
                
                if resolved_assignee_id is not None:
                    payload["assignee_id"] = resolved_assignee_id
                payload["department_id"] = resolved_department_id
            if edit_mode == "admin_full":
                resolved_assignee_id, resolved_department_id = _resolve_task_assignment(
                    access_token=token,
                    scope=scope,
                    assignee_user_id=selected.get("assignee_id"),
                    assignee_name=selected.get("assignee"),
                    fallback_assignee_id=_parse_int(selected.get("assignee_id")),
                    fallback_department_id=_parse_int(selected.get("department_id")),
                )
                payload.update(
                    {
                        "creator_id": _parse_int(selected.get("creator_id")),
                        "assignee_id": resolved_assignee_id,
                        "department_id": resolved_department_id,
                        "planned_start_date": selected.get("planned_start_date"),
                        "planned_end_date": selected.get("planned_end_date"),
                    }
                )
            response = TasksController.update_task(task_id, payload, access_token=token)
            if response is None:
                messages.error(request, "Нет связи с API при редактировании задачи.")
            elif 200 <= response.status_code < 300:
                messages.success(request, "Задача обновлена.")
            else:
                api_error_text = _extract_response_error(response)
                messages.error(request, f"Ошибка API: {api_error_text}")
                debug_payload = {
                    "task_id": task_id,
                    "scope": scope,
                    "edit_mode": edit_mode,
                    "creator_id": payload.get("creator_id"),
                    "assignee_id": payload.get("assignee_id"),
                    "department_id": payload.get("department_id"),
                    "status_id": payload.get("status_id"),
                    "title": payload.get("title"),
                    "priority": payload.get("priority"),
                    "planned_start_date": payload.get("planned_start_date"),
                    "planned_end_date": payload.get("planned_end_date"),
                    "actual_start_date": payload.get("actual_start_date"),
                    "actual_end_date": payload.get("actual_end_date"),
                }
                messages.warning(
                    request,
                    f"DEBUG PUT /tasks/{task_id} status={response.status_code}: {debug_payload}",
                )
            return redirect("task_detail", task_id=task_id)

        if action == "delete":
            if not (scope in {"admin", "manager"}):
                messages.error(request, "Удаление задачи доступно только администратору и менеджеру.")
                return redirect("task_detail", task_id=task_id)
            response = TasksController.delete_task(task_id, access_token=token)
            if response is None:
                messages.error(request, "Нет связи с API при удалении задачи.")
                return redirect("task_detail", task_id=task_id)
            if 200 <= response.status_code < 300:
                messages.success(request, "Задача удалена.")
                return redirect("dashboard")
            messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
            return redirect("task_detail", task_id=task_id)

    planned_end = selected.get("planned_end_date") or ""
    is_overdue = False
    if (selected.get("status") or "").strip().lower() == "в работе" and planned_end:
        try:
            is_overdue = date.fromisoformat(str(planned_end)) < date.today()
        except ValueError:
            is_overdue = False

    return render(
        request,
        "task_detail.html",
        {
            "task": selected,
            "task_is_overdue": is_overdue,
            "task_scope": task_scope,
            "can_comment": can_comment,
            "can_edit": can_edit,
            "edit_mode": edit_mode,
            "current_user_scope": scope,
            "comment_form_data": comment_form_data,
            "comment_field_errors": comment_field_errors,
            "active_page": "dashboard",
        },
    )


@require_POST
def dashboard_task_status_update(request):
    """AJAX-обработчик смены колонки задачи на дашборде.
    Валидирует входные данные, обновляет статус через API и возвращает JSON-результат.
    """
    token = request.session.get("access_token")
    if not token:
        return JsonResponse({"ok": False, "error": "Нужна авторизация."}, status=401)

    task_id_raw = (request.POST.get("task_id") or "").strip()
    target_column = (request.POST.get("target_column") or "").strip()
    status_name = KANBAN_COLUMN_TO_STATUS_NAME.get(target_column)
    if status_name is None:
        return JsonResponse({"ok": False, "error": "Некорректная колонка."}, status=400)
    try:
        task_id = int(task_id_raw)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Некорректный task_id."}, status=400)

    response = TasksController.update_task_status(task_id, status_name, access_token=token)
    if response is None:
        return JsonResponse({"ok": False, "error": "Нет связи с API."}, status=502)
    if 200 <= response.status_code < 300:
        return JsonResponse({"ok": True})

    return JsonResponse(
        {"ok": False, "error": _extract_response_error(response)},
        status=response.status_code,
    )


def employees(request):
    """Рендерит страницу сотрудников с группировкой, фильтрами и режимами формы.
    Загружает сотрудников по роли, применяет поиск/фильтры и подготавливает данные для add/edit.
    """
    token = request.session.get("access_token")
    scope, scope_error = _resolve_user_scope(request, token)
    if scope == "admin":
        employees_list, api_error = EmployeeController.get_employees(access_token=token)
    elif scope == "manager":
        employees_list, api_error = EmployeeController.get_manager_department_employees(access_token=token)
    else:
        employees_list, api_error = EmployeeController.get_my_department_employees(access_token=token)

    selected_department = (request.GET.get("department") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    mode = (request.GET.get("mode") or "").strip().lower()
    edit_id_raw = (request.GET.get("edit_id") or "").strip()
    flashed_form_mode = request.session.pop("employees_form_mode", "")
    flashed_form_initial = request.session.pop("employees_form_initial", None)
    flashed_field_errors = request.session.pop("employees_field_errors", None)

    dept_names, dept_error = DepartmentController.get_department_name_map()
    form_departments = dict(dept_names)
    filtered_employees = []
    has_employees_without_department = False
    search_query_norm = search_query.lower()

    for row in employees_list:
        if not isinstance(row, dict):
            continue

        department_id = row.get("department_id")
        row["department_name"] = dept_names.get(department_id) if department_id is not None else None
        if department_id is not None and department_id not in form_departments:
            form_departments[department_id] = f"Отдел №{department_id}"
        if department_id is None:
            has_employees_without_department = True

        if selected_department:
            if selected_department == "__none__" and department_id is not None:
                continue
            if selected_department != "__none__" and str(department_id) != selected_department:
                continue

        if search_query_norm and not _is_fuzzy_last_name_match(row.get("last_name"), search_query_norm):
            continue

        filtered_employees.append(row)

    departments_options = sorted(
        form_departments.items(),
        key=lambda x: ((x[1] or "").lower(), x[0] or 0),
    )

    by_dept = defaultdict(list)
    for row in filtered_employees:
        by_dept[row.get("department_id")].append(row)

    ordered_dept_ids = [
        did for did, _ in departments_options if did in by_dept and by_dept[did]
    ]
    ordered_dept_ids.extend(
        did
        for did in sorted(k for k in by_dept if k is not None)
        if did not in ordered_dept_ids
    )
    if None in by_dept and by_dept[None]:
        ordered_dept_ids.append(None)

    employees_by_department = []
    for did in ordered_dept_ids:
        people = by_dept[did]
        if not people:
            continue
        dept_title = "Без подразделения" if did is None else form_departments.get(did, f"Отдел №{did}")
        employees_by_department.append({"id": did, "name": dept_title, "employees": people})

    form_initial = _default_employee_form(departments_options)
    edit_employee_id = None
    if edit_id_raw:
        try:
            edit_employee_id = int(edit_id_raw)
            mode = "edit"
        except (TypeError, ValueError):
            edit_employee_id = None

    if mode == "edit" and edit_employee_id is not None:
        selected_employee = next(
            (
                row
                for row in employees_list
                if isinstance(row, dict) and row.get("id") == edit_employee_id
            ),
            None,
        )
        if selected_employee:
            form_initial = {
                "employee_id": selected_employee.get("id") or "",
                "first_name": selected_employee.get("first_name") or "",
                "last_name": selected_employee.get("last_name") or "",
                "middle_name": selected_employee.get("middle_name") or "",
                "phone_number": selected_employee.get("phone_number") or "",
                "email": selected_employee.get("email") or "",
                "passport_data": selected_employee.get("passport_data") or "",
                "inn": selected_employee.get("inn") or "",
                "snils": selected_employee.get("snils") or "",
                "department_id": (
                    str(selected_employee.get("department_id"))
                    if selected_employee.get("department_id") is not None
                    else ""
                ),
                "is_active": bool(selected_employee.get("is_active")),
            }
        else:
            messages.warning(request, "Сотрудник для редактирования не найден.")
            mode = "add"
    elif mode != "add":
        mode = ""

    field_errors = {}
    if flashed_form_mode == "add":
        mode = "add"
        if isinstance(flashed_form_initial, dict):
            form_initial = {**form_initial, **flashed_form_initial}
        if isinstance(flashed_field_errors, dict):
            field_errors = flashed_field_errors

    return render(
        request,
        "employees.html",
        {
            "employees": employees_list,
            "employees_by_department": employees_by_department,
            "has_employees_without_department": has_employees_without_department,
            "api_error": api_error,
            "scope_error": scope_error,
            "departments_error": dept_error,
            "departments_options": departments_options,
            "selected_department": selected_department,
            "search_query": search_query,
            "form_mode": mode,
            "form_initial": form_initial,
            "field_errors": field_errors,
            "user_scope": scope,
            "active_page": "employees",
        },
    )


def employee_create(request):
    """Создает сотрудника из данных POST-формы.
    Проверяет права и обязательные поля, отправляет payload в API и показывает результат.
    """
    if request.method != "POST":
        return redirect("employees")

    token_or_redirect = _get_required_token(request, "employees")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect
    scope, _ = _resolve_user_scope(request, token)
    if scope == "employee":
        messages.error(request, "У сотрудника нет прав на создание сотрудников.")
        return redirect("employees")

    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    passport_data = (request.POST.get("passport_data") or "").strip()
    dept_raw = request.POST.get("department_id")
    flashed_form_initial = {
        "employee_id": "",
        "first_name": first_name,
        "last_name": last_name,
        "middle_name": (request.POST.get("middle_name") or "").strip(),
        "phone_number": (request.POST.get("phone_number") or "").strip(),
        "email": email,
        "passport_data": passport_data,
        "inn": (request.POST.get("inn") or "").strip(),
        "snils": (request.POST.get("snils") or "").strip(),
        "department_id": (dept_raw or "").strip(),
        "is_active": request.POST.get("is_active") == "on",
    }

    field_errors = {}
    if not first_name:
        field_errors["first_name"] = "Поле обязательно."
    if not last_name:
        field_errors["last_name"] = "Поле обязательно."
    if not email:
        field_errors["email"] = "Поле обязательно."
    if not passport_data:
        field_errors["passport_data"] = "Поле обязательно."
    if field_errors:
        messages.error(request, "Заполните имя, фамилию, email и паспортные данные.")
        request.session["employees_form_mode"] = "add"
        request.session["employees_form_initial"] = flashed_form_initial
        request.session["employees_field_errors"] = field_errors
        return redirect("employees")
    try:
        department_id = int(dept_raw)
    except (TypeError, ValueError):
        messages.error(request, "Выберите подразделение.")
        request.session["employees_form_mode"] = "add"
        request.session["employees_form_initial"] = flashed_form_initial
        request.session["employees_field_errors"] = {"department_id": "Поле обязательно."}
        return redirect("employees")

    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "passport_data": passport_data,
        "department_id": department_id,
        "is_active": request.POST.get("is_active") == "on",
    }
    for key in ("middle_name", "phone_number", "inn", "snils"):
        value = (request.POST.get(key) or "").strip()
        if value:
            payload[key] = value

    if scope == "manager":
        payload["_manager_mode"] = True
    response = EmployeeController.create_employee(payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при создании.")
        return redirect("employees")
    if 200 <= response.status_code < 300:
        messages.success(request, "Сотрудник добавлен.")
        return redirect("employees")

    messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")


def employee_update(request):
    """Обновляет данные сотрудника по форме редактирования.
    Собирает частичный payload, валидирует id/отдел и отправляет изменения в API.
    """
    if request.method != "POST":
        return redirect("employees")

    token_or_redirect = _get_required_token(request, "employees")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect
    scope, _ = _resolve_user_scope(request, token)
    if scope == "employee":
        messages.error(request, "У сотрудника нет прав на редактирование сотрудников.")
        return redirect("employees")

    raw_id = request.POST.get("employee_id")
    try:
        employee_id = int(raw_id)
    except (TypeError, ValueError):
        messages.error(request, "Некорректный идентификатор сотрудника.")
        return redirect("employees")

    payload = {}
    for key in ("first_name", "last_name", "middle_name", "phone_number", "email", "passport_data", "inn", "snils"):
        value = (request.POST.get(key) or "").strip()
        if value:
            payload[key] = value

    dept_raw = (request.POST.get("department_id") or "").strip()
    if dept_raw:
        try:
            payload["department_id"] = int(dept_raw)
        except ValueError:
            messages.error(request, "Некорректный отдел.")
            return redirect("employees")

    payload["is_active"] = request.POST.get("is_active") == "on"
    if scope == "manager":
        payload["_manager_mode"] = True
    response = EmployeeController.update_employee(employee_id, payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при сохранении.")
        return redirect("employees")
    if 200 <= response.status_code < 300:
        messages.success(request, "Данные сотрудника обновлены.")
        return redirect("employees")

    messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")


def employee_delete(request):
    """Удаляет сотрудника по идентификатору из POST-формы.
    Выбирает endpoint по роли (admin/manager) и сообщает итог операции пользователю.
    """
    if request.method != "POST":
        return redirect("employees")

    token_or_redirect = _get_required_token(request, "employees")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect
    scope, _ = _resolve_user_scope(request, token)
    if scope == "employee":
        messages.error(request, "У сотрудника нет прав на удаление сотрудников.")
        return redirect("employees")

    raw_id = request.POST.get("employee_id")
    try:
        employee_id = int(raw_id)
    except (TypeError, ValueError):
        messages.error(request, "Некорректный идентификатор сотрудника.")
        return redirect("employees")

    if scope == "manager":
        response = EmployeeController.delete_manager_department_employee(employee_id, access_token=token)
    else:
        response = EmployeeController.delete_employee(employee_id, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при удалении.")
        return redirect("employees")
    if 200 <= response.status_code < 300:
        messages.success(request, "Сотрудник удален.")
        return redirect("employees")

    messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")


def _period_label(period):
    """Преобразует ключ периода фильтра в читаемую подпись.
    Используется в отчетах и заголовках экспортируемых файлов.
    """
    if period == "month":
        return "За месяц"
    if period == "year":
        return "За год"
    return "За всё время"


def _build_employee_options(employees):
    """Строит отсортированные options исполнителей для фильтров/форм.
    Формирует пары (user_id, ФИО) и исключает записи без user_id.
    """
    options = []
    for row in employees:
        user_id = row.get("user_id")
        if user_id is None:
            continue
        full_name = " ".join(
            value
            for value in (
                row.get("last_name") or "",
                row.get("first_name") or "",
                row.get("middle_name") or "",
            )
            if value
        ).strip()
        options.append((user_id, full_name or f"Сотрудник #{user_id}"))
    options.sort(key=lambda pair: pair[1].lower())
    return options


def _build_monthly_employee_stats(tasks, selected_employee_id, selected_year):
    """Считает помесячную статистику выполнения задач сотрудника за выбранный год.
    Возвращает детализацию по месяцам и суммарные значения для графиков.
    """
    by_month_total = {month: 0 for month in range(1, 13)}
    by_month_done = {month: 0 for month in range(1, 13)}
    for row in tasks:
        assignee_id = _parse_int(row.get("assignee_id"))
        if assignee_id != selected_employee_id:
            continue
        task_date = _task_report_date(row)
        if task_date is None or task_date.year != selected_year:
            continue
        by_month_total[task_date.month] += 1
        if _is_task_done(row):
            by_month_done[task_date.month] += 1

    month_labels = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
    monthly_stats = []
    chart_total_tasks = 0
    chart_done_tasks = 0
    for month in range(1, 13):
        total = by_month_total[month]
        done = by_month_done[month]
        pending = total - done
        done_percent = (done / total) * 100 if total else 0
        pending_percent = (pending / total) * 100 if total else 0
        chart_total_tasks += total
        chart_done_tasks += done
        monthly_stats.append(
            {
                "month": month_labels[month - 1],
                "percent": round(done_percent, 2),
                "pending_percent": round(pending_percent, 2),
                "done_width": f"{done_percent:.2f}",
                "pending_width": f"{pending_percent:.2f}",
                "total": total,
                "done": done,
                "pending": pending,
            }
        )
    return monthly_stats, chart_total_tasks, chart_done_tasks


def reports(request):
    """Рендерит страницу отчетов и обрабатывает экспорт в Excel.
    Готовит срезы по периодам/подразделениям/сотрудникам и агрегированную статистику.
    """
    token = request.session.get("access_token")
    scope, scope_error = _resolve_user_scope(request, token)
    me_response = UserController.get_me(access_token=token) if token else None
    if me_response is not None and 200 <= me_response.status_code < 300:
        try:
            me_payload = me_response.json()
        except Exception:
            me_payload = {}
        if isinstance(me_payload, dict):
            role_id = me_payload.get("role_id")
            if role_id == 1:
                scope = "admin"
            elif role_id == 2:
                scope = "manager"
            elif role_id is not None:
                scope = "employee"

    if scope == "employee":
        messages.error(request, "Отчеты доступны только администратору и менеджеру.")
        return redirect("dashboard")

    if scope == "admin":
        all_tasks, tasks_error, _ = TasksController.get_all_tasks(access_token=token)
        employees, employees_error = EmployeeController.get_employees(access_token=token)
    elif scope == "manager":
        all_tasks, tasks_error = TasksController.get_current_tasks(access_token=token)
        employees, employees_error = EmployeeController.get_manager_department_employees(access_token=token)
    else:
        messages.error(request, "Не удалось определить роль пользователя для отчетов.")
        return redirect("dashboard")

    all_tasks = [row for row in all_tasks if isinstance(row, dict)]
    employees = [row for row in employees if isinstance(row, dict)]

    department_name_map, departments_error = DepartmentController.get_department_name_map()
    department_options = sorted(
        department_name_map.items(),
        key=lambda pair: ((pair[1] or "").lower(), pair[0]),
    )

    selected_period = (request.GET.get("period") or ("all" if scope == "manager" else "month")).strip().lower()
    if selected_period not in {"month", "year", "all"}:
        selected_period = "month"
    selected_department_raw = (request.GET.get("department_id") or "").strip()
    selected_employee_raw = (request.GET.get("employee_id") or "").strip()
    selected_year = date.today().year

    manager_department_name = ""
    tasks_filtered = list(all_tasks)
    if scope == "manager":
        task_form_context = _task_form_context(request)
        manager_department_id = task_form_context.get("manager_department_id")
        if manager_department_id is None:
            selected_department_raw = ""
            department_options = []
            tasks_filtered = []
        else:
            selected_department_raw = str(manager_department_id)
            for dep_id, dep_name in task_form_context.get("departments_options") or []:
                if dep_id == manager_department_id:
                    manager_department_name = dep_name or ""
                    break
            if not manager_department_name:
                manager_department_name = department_name_map.get(manager_department_id) or "Моё подразделение"
            department_name_map = {manager_department_id: manager_department_name}
            department_options = [(manager_department_id, manager_department_name)]

    # Фильтр по подразделению из селектора.
    if selected_department_raw:
        selected_dep_str = str(selected_department_raw).strip()
        filtered_by_id = [
            row
            for row in tasks_filtered
            if row.get("department_id") is not None and str(row.get("department_id")).strip() == selected_dep_str
        ]
        if filtered_by_id:
            tasks_filtered = filtered_by_id
        elif scope != "manager":
            selected_dep_name = ""
            for dep_id, dep_name in department_options:
                if str(dep_id).strip() == selected_dep_str:
                    selected_dep_name = (dep_name or "").strip().lower()
                    break
            if selected_dep_name:
                tasks_filtered = [
                    row
                    for row in tasks_filtered
                    if (row.get("department") or "").strip().lower() == selected_dep_name
                ]

    period_label = _period_label(selected_period)
    today = date.today()
    period_tasks = []
    for row in tasks_filtered:
        task_date = _task_report_date(row)
        if task_date is None:
            if selected_period == "all":
                period_tasks.append(row)
            continue
        if selected_period == "all":
            period_tasks.append(row)
        elif selected_period == "month":
            if task_date.year == today.year and task_date.month == today.month:
                period_tasks.append(row)
        elif task_date.year == today.year:
            period_tasks.append(row)

    department_task_report_map = defaultdict(
        lambda: {
            "department": "Без подразделения",
            "total": 0,
            "done": 0,
            "planned": 0,
            "in_progress": 0,
            "review": 0,
            "overdue": 0,
        }
    )
    for row in period_tasks:
        dep_id = row.get("department_id")
        dep_name = (row.get("department") or "").strip() or department_name_map.get(dep_id) or "Без подразделения"
        if scope == "manager" and manager_department_name:
            dep_name = manager_department_name
        bucket = department_task_report_map[dep_name]
        bucket["department"] = dep_name
        bucket["total"] += 1
        status_name = (row.get("status") or "").strip().lower()
        if status_name == "выполнено":
            bucket["done"] += 1
        elif status_name == "к выполнению":
            bucket["planned"] += 1
        elif status_name == "в работе":
            bucket["in_progress"] += 1
        elif status_name == "на проверке":
            bucket["review"] += 1
        elif status_name == "просрочено":
            bucket["overdue"] += 1

    department_task_report = []
    for dep_name in sorted(department_task_report_map.keys(), key=lambda value: value.lower()):
        row = department_task_report_map[dep_name]
        total = row["total"]
        row["done_percent"] = round((row["done"] / total) * 100, 2) if total else 0
        department_task_report.append(row)

    action = (request.GET.get("action") or "").strip().lower()
    if action == "download_tasks_excel":
        workbook = _build_tasks_report_excel(department_task_report, period_label)
        file_name = f"department_tasks_report_{selected_period}_{today.isoformat()}.xlsx"
        return _xlsx_response(workbook, file_name)

    if action == "download_employees_excel":
        workbook = _build_employees_report_excel(employees, department_name_map)
        file_name = f"employees_report_{today.isoformat()}.xlsx"
        return _xlsx_response(workbook, file_name)

    employees_count_map = defaultdict(int)
    for row in employees:
        dep_id = row.get("department_id")
        dep_name = department_name_map.get(dep_id) if dep_id is not None else None
        employees_count_map[dep_name or "Без подразделения"] += 1
    employees_count_rows = [
        {"department": dep_name, "count": employees_count_map[dep_name]}
        for dep_name in sorted(employees_count_map.keys(), key=lambda value: value.lower())
    ]

    employee_options = _build_employee_options(employees)
    selected_employee_id = _parse_int(selected_employee_raw)
    if selected_employee_id is None and selected_employee_raw:
        selected_employee_raw = ""

    monthly_stats = []
    selected_employee_name = ""
    chart_total_tasks = 0
    chart_done_tasks = 0
    if selected_employee_id is not None:
        for employee_id, employee_name in employee_options:
            if employee_id == selected_employee_id:
                selected_employee_name = employee_name
                break
        monthly_stats, chart_total_tasks, chart_done_tasks = _build_monthly_employee_stats(
            tasks_filtered,
            selected_employee_id,
            selected_year,
        )

    return render(
        request,
        "reports.html",
        {
            "active_page": "reports",
            "user_scope": scope,
            "scope_error": scope_error,
            "tasks_error": tasks_error,
            "employees_error": employees_error,
            "departments_error": departments_error,
            "department_options": department_options,
            "employee_options": employee_options,
            "selected_period": selected_period,
            "selected_department_id": selected_department_raw,
            "selected_employee_id": selected_employee_raw,
            "is_manager_reports": scope == "manager",
            "period_tasks_count": len(period_tasks),
            "period_tasks_done_count": sum(1 for row in period_tasks if _is_task_done(row)),
            "period_label": period_label,
            "department_task_report": department_task_report,
            "employees_count_rows": employees_count_rows,
            "employees_total_count": sum(row["count"] for row in employees_count_rows),
            "monthly_stats": monthly_stats,
            "selected_employee_name": selected_employee_name,
            "chart_total_tasks": chart_total_tasks,
            "chart_done_tasks": chart_done_tasks,
            "chart_done_percent": round((chart_done_tasks / chart_total_tasks) * 100, 2) if chart_total_tasks else 0,
            "selected_year": selected_year,
        },
    )


def admin_departments(request):
    """Админ-раздел управления подразделениями (создание, редактирование, удаление).
    Валидирует формы, вызывает API подразделений и возвращает данные для шаблона.
    """
    token = request.session.get("access_token")
    scope, _ = _resolve_user_scope(request, token)

    if scope != "admin":
        messages.error(request, "Доступно только администратору.")
        return redirect("dashboard")

    department_form_data = {"name": "", "description": ""}
    department_field_errors = {}
    update_form_data = {"name": "", "description": ""}
    update_field_errors = {}
    edit_department_id = ""

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "department_create":
            department_form_data = {
                "name": (request.POST.get("name") or "").strip(),
                "description": (request.POST.get("description") or "").strip(),
            }
            if not department_form_data["name"]:
                department_field_errors["name"] = "Поле обязательно."
            if not department_form_data["description"]:
                department_field_errors["description"] = "Поле обязательно."
            if department_field_errors:
                messages.error(request, "Заполните обязательные поля подразделения.")
            else:
                payload = {
                    "name": department_form_data["name"],
                    "description": department_form_data["description"],
                }
                response = DepartmentController.create_department(payload, access_token=token)
                if response is not None and 200 <= response.status_code < 300:
                    messages.success(request, "Подразделение создано.")
                    return redirect("admin_departments")
                api_error = _extract_response_error(response)
                department_field_errors = _department_field_errors_from_api(api_error)
                messages.error(request, f"Ошибка API: {api_error}")
        elif action == "department_update":
            dep_id = (request.POST.get("department_id") or "").strip()
            edit_department_id = dep_id
            update_form_data = {
                "name": (request.POST.get("name") or "").strip(),
                "description": (request.POST.get("description") or "").strip(),
            }
            if not update_form_data["name"]:
                update_field_errors["name"] = "Поле обязательно."
            if not update_form_data["description"]:
                update_field_errors["description"] = "Поле обязательно."
            if not dep_id:
                messages.error(request, "Некорректный идентификатор подразделения.")
            elif update_field_errors:
                messages.error(request, "Заполните обязательные поля подразделения.")
            else:
                response = DepartmentController.update_department(dep_id, update_form_data, access_token=token)
                if response is not None and 200 <= response.status_code < 300:
                    messages.success(request, "Подразделение обновлено.")
                    return redirect("admin_departments")
                api_error = _extract_response_error(response)
                update_field_errors = _department_field_errors_from_api(api_error)
                messages.error(request, f"Ошибка API: {api_error}")
        elif action == "department_delete":
            dep_id = (request.POST.get("department_id") or "").strip()
            response = DepartmentController.delete_department(dep_id, access_token=token)
            if response is not None and 200 <= response.status_code < 300:
                messages.success(request, "Подразделение удалено.")
            else:
                messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
        if action == "department_delete":
            return redirect("admin_departments")

    departments, departments_error = DepartmentController.get_departments(access_token=token)
    return render(
        request,
        "admin_departments.html",
        {
            "active_page": "admin_departments",
            "departments": departments,
            "departments_error": departments_error,
            "department_form_data": department_form_data,
            "field_errors": department_field_errors,
            "update_form_data": update_form_data,
            "update_field_errors": update_field_errors,
            "edit_department_id": edit_department_id,
        },
    )


def admin_users(request):
    """Админ-раздел управления пользователями и созданием учетных записей.
    Обрабатывает форму создания пользователя и загружает список пользователей из API.
    """
    token = request.session.get("access_token")
    scope, _ = _resolve_user_scope(request, token)

    if scope != "admin":
        messages.error(request, "Доступно только администратору.")
        return redirect("dashboard")

    user_form_data = {"username": "", "password": "", "role_id": "3"}
    user_field_errors = {}

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "user_create":
            user_form_data = {
                "username": (request.POST.get("username") or "").strip(),
                "password": (request.POST.get("password") or "").strip(),
                "role_id": (request.POST.get("role_id") or "").strip() or "3",
            }
            if not user_form_data["username"]:
                user_field_errors["username"] = "Поле обязательно."
            if not user_form_data["password"]:
                user_field_errors["password"] = "Поле обязательно."
            try:
                role_id_int = int(user_form_data["role_id"])
                if role_id_int not in {1, 2, 3}:
                    raise ValueError
            except ValueError:
                user_field_errors["role_id"] = "Выберите корректную роль."
                role_id_int = 0

            if user_field_errors:
                messages.error(request, "Заполните обязательные поля пользователя.")
            else:
                response = UserController.create_user_as_admin(
                    username=user_form_data["username"],
                    password=user_form_data["password"],
                    role_id=role_id_int,
                    access_token=token,
                )
                if response is not None and 200 <= response.status_code < 300:
                    messages.success(request, "Пользователь создан администратором.")
                    return redirect("admin_users")
                messages.error(request, f"Ошибка API: {_extract_response_error(response)}")

    users_response = UserController.get_users(access_token=token)
    users = []
    users_error = None
    if users_response is None:
        users_error = "Нет связи с API пользователей."
    else:
        try:
            users_payload = users_response.json()
        except ValueError:
            users_payload = {}
        if 200 <= users_response.status_code < 300:
            if isinstance(users_payload, dict):
                users = users_payload.get("items") or []
        else:
            users_error = _extract_response_error(users_response)

    return render(
        request,
        "admin_users.html",
        {
            "active_page": "admin_users",
            "users": users,
            "users_error": users_error,
            "user_form_data": user_form_data,
            "field_errors": user_field_errors,
        },
    )


def _task_form_context(request):
    """Собирает контекст для формы создания задачи.
    Подготавливает списки сотрудников/создателей/отделов и ограничения по роли пользователя.
    """
    token = request.session.get("access_token")
    scope, _ = _resolve_user_scope(request, token)
    me_response = UserController.get_me(access_token=token) if token else None
    me = {}
    if me_response is not None and 200 <= me_response.status_code < 300:
        try:
            me_payload = me_response.json()
            me = me_payload if isinstance(me_payload, dict) else {}
        except Exception:
            me = {}

    if scope == "admin":
        employees, employees_error = EmployeeController.get_employees(access_token=token)
    elif scope == "manager":
        employees, employees_error = EmployeeController.get_manager_department_employees(access_token=token)
    else:
        employees, employees_error = [], "Создание задач доступно только администратору и менеджеру."
    departments, departments_error = DepartmentController.get_departments(access_token=token)
    department_map = {
        row.get("id"): row.get("name")
        for row in departments
        if isinstance(row, dict) and row.get("id") is not None and row.get("name")
    }

    employees_options = []
    employee_rows = []
    for row in employees:
        if not isinstance(row, dict):
            continue
        user_id = row.get("user_id")
        if user_id is None:
            continue
        department_id = row.get("department_id")
        full_name = " ".join(
            part for part in (
                row.get("last_name") or "",
                row.get("first_name") or "",
                row.get("middle_name") or "",
            ) if part
        ).strip()
        employees_options.append((user_id, full_name or f"Сотрудник #{user_id}", department_id))
        employee_rows.append(row)
    employees_options.sort(key=lambda x: x[1].lower())

    departments_options = sorted(department_map.items(), key=lambda x: ((x[1] or "").lower(), x[0] or 0))
    manager_department_id = None
    if scope == "manager":
        department_ids = sorted(
            {
                row.get("department_id")
                for row in employee_rows
                if isinstance(row, dict) and row.get("department_id") is not None
            }
        )
        if department_ids:
            manager_department_id = department_ids[0]

    creator_options = []
    users_error = None

    if scope == "admin":
        users_response = UserController.get_users(access_token=token)
        if users_response is not None and 200 <= users_response.status_code < 300:
            try:
                users_payload = users_response.json()
            except Exception:
                users_payload = {}
            users = users_payload.get("items") if isinstance(users_payload, dict) else []
            manager_department_by_user = {
                dep.get("department_manager_id"): dep.get("id")
                for dep in departments
                if isinstance(dep, dict)
                and dep.get("department_manager_id") is not None
                and dep.get("id") is not None
            }
            for user in users or []:
                if not isinstance(user, dict):
                    continue
                role_id = user.get("role_id")
                user_id = user.get("id")
                if role_id not in (1, 2) or user_id is None:
                    continue
                label = f"{user.get('username')} ({'админ' if role_id == 1 else 'менеджер'})"
                creator_options.append((user_id, label, role_id, manager_department_by_user.get(user_id)))
        else:
            users_error = _extract_response_error(users_response)
    else:
        me_id = me.get("id")
        me_username = me.get("username")
        if me_id is not None and me_username:
            creator_options = [(me_id, f"{me_username} (менеджер)", 2, manager_department_id)]

    return {
        "employees_options": employees_options,
        "creator_options": creator_options,
        "departments_options": departments_options,
        "employees_error": employees_error,
        "departments_error": departments_error,
        "users_error": users_error,
        "form_data": {
            "creator_id": str(creator_options[0][0]) if scope == "manager" and creator_options else "",
            "department_id": str(manager_department_id) if manager_department_id is not None else "",
        },
        "user_scope": scope,
        "me_user_id": me.get("id"),
        "manager_department_id": manager_department_id,
        "active_page": "tasks_create",
    }


def _task_form_data_from_post(request):
    """Извлекает и нормализует данные формы создания задачи из POST.
    Возвращает словарь строковых полей без преобразования типов.
    """
    return {
        "title": (request.POST.get("title") or "").strip(),
        "description": (request.POST.get("description") or "").strip(),
        "creator_id": (request.POST.get("creator_id") or "").strip(),
        "assignee_id": (request.POST.get("assignee_id") or "").strip(),
        "department_id": (request.POST.get("department_id") or "").strip(),
        "status": (request.POST.get("status") or "").strip(),
        "priority": (request.POST.get("priority") or "").strip(),
        "start_date": (request.POST.get("start_date") or "").strip(),
        "end_date": (request.POST.get("end_date") or "").strip(),
    }


def _render_task_create_with_form_data(request, field_errors=None):
    """Переотрисовывает форму создания задачи с введенными пользователем значениями.
    Подмешивает ошибки валидации и фиксирует принудительные поля для роли manager.
    """
    context = _task_form_context(request)
    posted = _task_form_data_from_post(request)
    if context.get("user_scope") == "manager" and context.get("manager_department_id") is not None:
        posted["department_id"] = str(context["manager_department_id"])
    if context.get("user_scope") == "manager" and context.get("me_user_id") is not None:
        posted["creator_id"] = str(context["me_user_id"])
    context["form_data"] = posted
    context["field_errors"] = field_errors or {}
    return render(request, "tasks_create.html", context)


def _task_create_required_errors(scope, form_data):
    """Проверяет наличие обязательных полей формы создания задачи.
    Возвращает первое сообщение об ошибке и словарь ошибок полей для UI.
    """
    required_fields = {
        "title": "Укажите название задачи.",
        "description": "Укажите описание задачи.",
        "priority": "Укажите приоритет задачи.",
        "status": "Укажите статус задачи.",
        "assignee_id": "Выберите исполнителя задачи.",
        "start_date": "Укажите дату начала выполнения задачи.",
        "end_date": "Укажите дату окончания выполнения задачи."
    }
    if scope == "admin":
        required_fields["creator_id"] = "Выберите создателя задачи."

    for field, message in required_fields.items():
        if form_data.get(field):
            continue
        return message, {field: "Поле обязательно."}
    return None, {}


def task_create(request):
    """Страница создания задач и обработчик отправки формы.
    Валидирует поля и права, собирает payload для API и возвращает ошибки по соответствующим полям.
    """
    context = _task_form_context(request)
    scope = context.get("user_scope")
    if scope == "employee":
        messages.error(request, "У сотрудника нет прав на создание задач.")
        return redirect("dashboard")

    if request.method != "POST":
        return render(request, "tasks_create.html", context)

    token_or_redirect = _get_required_token(request, "task_create")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect

    form_data = _task_form_data_from_post(request)
    required_error_message, field_errors = _task_create_required_errors(scope, form_data)
    if required_error_message:
        messages.error(request, required_error_message)
        return _render_task_create_with_form_data(request, field_errors)

    payload = {
        "title": form_data["title"],
        "description": form_data["description"],
        "priority": form_data["priority"],
    }

    if form_data["start_date"]:
        payload["planned_start_date"] = form_data["start_date"]
    if form_data["end_date"]:
        payload["planned_end_date"] = form_data["end_date"]

    status_id = STATUS_SLUG_TO_ID.get(form_data["status"])
    if status_id is None:
        messages.error(request, "Некорректный статус задачи.")
        return _render_task_create_with_form_data(request, {"status": "Выберите корректный статус."})
    payload["status_id"] = status_id

    for key in ("creator_id", "assignee_id", "department_id"):
        value = form_data.get(key)
        if not value:
            continue
        numeric_value = _parse_int(value)
        if numeric_value is None:
            messages.error(request, f"Некорректное значение поля: {key}.")
            return _render_task_create_with_form_data(request, {key: "Некорректное числовое значение."})
        payload[key] = numeric_value

    if scope == "manager":
        me_user_id = context.get("me_user_id")
        if me_user_id is None:
            messages.error(request, "Не удалось определить текущего менеджера.")
            return _render_task_create_with_form_data(request, {"creator_id": "Не удалось определить создателя."})
        payload["creator_id"] = int(me_user_id)
        manager_department_id = context.get("manager_department_id")
        if manager_department_id is None:
            messages.error(request, "Не удалось определить подразделение менеджера.")
            return _render_task_create_with_form_data(request, {"department_id": "Не удалось определить подразделение."})
        payload["department_id"] = int(manager_department_id)

    response = TasksController.create_task(payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при создании задачи.")
        return _render_task_create_with_form_data(request)
    if 200 <= response.status_code < 300:
        messages.success(request, "Задача создана.")
        return redirect("task_create")

    api_error = _extract_response_error(response) or ""
    messages.error(
        request,
        f"Ошибка API (код {response.status_code}): {api_error}",
    )
    field_errors = {}
    api_error_lower = api_error.lower()
    if "title" in api_error_lower or "назван" in api_error_lower:
        field_errors["title"] = api_error
    elif "description" in api_error_lower or "описан" in api_error_lower:
        field_errors["description"] = api_error
    elif "priority" in api_error_lower or "приоритет" in api_error_lower:
        field_errors["priority"] = api_error
    elif "status" in api_error_lower or "статус" in api_error_lower:
        field_errors["status"] = api_error
    elif "creator" in api_error_lower or "создател" in api_error_lower:
        field_errors["creator_id"] = api_error
    elif "assignee" in api_error_lower or "исполн" in api_error_lower:
        field_errors["assignee_id"] = api_error
    elif "department" in api_error_lower or "подраздел" in api_error_lower:
        field_errors["department_id"] = api_error
    return _render_task_create_with_form_data(request, field_errors)


def no_access(request):
    """Показывает страницу отказа в доступе для неавторизованных пользователей.
    Используется как целевая страница редиректа при отсутствии активного токена.
    """
    return render(request, "no_access.html")


def logout_view(request):
    """Очищает пользовательскую сессию и переводит на страницу входа.
    Используется для корректного завершения сеанса и удаления access token.
    """
    request.session.flush()
    return redirect("auth")

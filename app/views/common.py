from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
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
}
STATUS_NAME_TO_ID = {
    "К выполнению": 1,
    "В работе": 2,
    "На проверке": 3,
    "Выполнено": 4,
}


def _extract_response_error(response):
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
    token = request.session.get("access_token")
    if token:
        return token
    messages.error(request, "Войдите в систему (нужен токен для API).")
    return redirect(redirect_name)


def _is_fuzzy_last_name_match(last_name, query):
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
    return {
        "employee_id": "",
        "user_id": "",
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
    cached_scope = request.session.get("ui_user_scope")
    if cached_scope in {"admin", "manager", "employee"}:
        return cached_scope, None

    _, admin_error = EmployeeController.get_employees(access_token=access_token)
    if admin_error is None:
        request.session["ui_user_scope"] = "admin"
        return "admin", None

    _, manager_error = EmployeeController.get_manager_department_employees(
        access_token=access_token
    )
    if manager_error is None:
        request.session["ui_user_scope"] = "manager"
        return "manager", None

    request.session["ui_user_scope"] = "employee"
    return "employee", admin_error or manager_error


def _load_dashboard_tasks(access_token, scope):
    if scope == "admin":
        tasks, error, _ = TasksController.get_all_tasks(access_token=access_token)
        return tasks, error
    if scope == "manager":
        return TasksController.get_current_tasks(access_token=access_token)
    return TasksController.get_my_tasks(access_token=access_token)


def _load_tasks_for_scope(request, access_token, scope):
    task_scope = (request.GET.get("task_scope") or "").strip().lower()
    if scope == "employee" and task_scope == "department":
        return task_scope, TasksController.get_current_tasks(access_token=access_token)
    tasks, error = _load_dashboard_tasks(access_token, scope)
    if scope == "employee":
        task_scope = "my"
    return task_scope, (tasks, error)


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _available_users_for_employee_form(users, employees_list, selected_user_id=None):
    occupied_user_ids = {
        row.get("user_id")
        for row in employees_list
        if isinstance(row, dict) and row.get("user_id") is not None
    }
    options = []
    selected_user_id = _parse_int(selected_user_id)
    for user in users:
        if not isinstance(user, dict):
            continue
        uid = user.get("id")
        if uid is None:
            continue
        if uid in occupied_user_ids and uid != selected_user_id:
            continue
        username = (user.get("username") or "").strip() or f"user#{uid}"
        options.append((uid, username))
    options.sort(key=lambda pair: pair[1].lower())
    return options


def _department_field_errors_from_api(api_error):
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
    if period not in {"month", "year"}:
        return tasks

    today = date.today()
    filtered = []
    for row in tasks:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("planned_end_date") or row.get("planned_start_date")
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


def _is_task_overdue_by_date(task_row, today=None):
    status_name = (task_row.get("status") or "").strip().lower()
    if status_name not in {"к выполнению", "в работе"}:
        return False
    planned_end = _safe_iso_date(task_row.get("planned_end_date"))
    if planned_end is None:
        return False
    return planned_end < (today or date.today())


def _task_report_date(task_row):
    return (
        _safe_iso_date(task_row.get("actual_end_date"))
        or _safe_iso_date(task_row.get("planned_end_date"))
        or _safe_iso_date(task_row.get("planned_start_date"))
    )


def _is_task_done(task_row):
    return (task_row.get("status") or "").strip().lower() == "выполнено"


def _resolve_task_assignment(
    access_token,
    scope,
    assignee_user_id,
    assignee_name,
    fallback_assignee_id,
    fallback_department_id,
):
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
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


def _build_tasks_report_excel(department_rows, period_label):
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


def _period_label(period):
    if period == "month":
        return "За месяц"
    if period == "year":
        return "За год"
    return "За всё время"


def _build_employee_options(employees):
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


def _task_form_context(request):
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

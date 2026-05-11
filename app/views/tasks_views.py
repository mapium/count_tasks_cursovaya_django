from datetime import date

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from app.controllers.tasks_controller import TasksController
from app.views.common import (
    KANBAN_COLUMN_TO_STATUS_NAME,
    STATUS_NAME_TO_ID,
    STATUS_NAME_TO_KANBAN_COLUMN,
    STATUS_SLUG_TO_ID,
    _extract_response_error,
    _filter_tasks_by_period,
    _get_required_token,
    _is_task_overdue_by_date,
    _load_tasks_for_scope,
    _parse_int,
    _resolve_task_assignment,
    _resolve_user_scope,
    _task_form_context,
)


def dashboard(request):
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
        if status_key in {"planned", "in_progress"}:
            is_overdue = _is_task_overdue_by_date(row, today=today)

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
    overdue_count = sum(
        1 for column in ("planned", "in_progress") for task in grouped[column] if task.get("is_overdue")
    )
    stats = {
        "total": len(tasks),
        "done": counts["done"],
        "overdue": overdue_count,
        "review": counts["review"],
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
            actual_start_raw = (request.POST.get("actual_start_date") or selected.get("actual_start_date") or "").strip()
            actual_end_raw = (request.POST.get("actual_end_date") or selected.get("actual_end_date") or "").strip()
            status_name = (request.POST.get("status_name") or selected.get("status") or "").strip()
            status_id = STATUS_NAME_TO_ID.get(status_name, selected.get("status_id"))
            payload = {
                "status_id": int(status_id) if status_id is not None else None,
                "actual_start_date": actual_start_raw or None,
                "actual_end_date": actual_end_raw or None,
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
    if planned_end:
        is_overdue = _is_task_overdue_by_date(selected)

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


def _task_form_data_from_post(request):
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

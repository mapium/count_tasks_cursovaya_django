from collections import defaultdict

from django.contrib import messages
from django.shortcuts import redirect, render

from app.controllers.department_controller import DepartmentController
from app.controllers.employee_controller import EmployeeController
from app.controllers.tasks_controller import TasksController
from app.controllers.user_controller import UserController


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


def _default_employee_form(departments_options):
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


def auth(request):
    if request.method != "POST":
        return render(request, "auth.html")

    response = UserController.login_user(
        username=request.POST.get("username"),
        password=request.POST.get("password"),
    )
    if response is not None and 200 <= response.status_code < 300:
        try:
            data = response.json()
        except Exception:
            data = {}
        request.session["is_authenticated"] = True
        if data.get("access_token"):
            request.session["access_token"] = data["access_token"]
        return redirect("dashboard")

    status = response.status_code if response is not None else "нет ответа"
    context = {"error": f"Ошибка авторизации: {status}"}
    error_message = _extract_response_error(response)
    if error_message and error_message != "нет ответа":
        context["error_message"] = error_message
    return render(request, "auth.html", context)


def dashboard(request):
    return render(request, "dashboard.html")


def employees(request):
    token = request.session.get("access_token")
    employees_list, api_error = EmployeeController.get_employees(access_token=token)

    selected_department = (request.GET.get("department") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    mode = (request.GET.get("mode") or "").strip().lower()
    edit_id_raw = (request.GET.get("edit_id") or "").strip()

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

        if search_query_norm and search_query_norm not in (row.get("last_name") or "").lower():
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

    return render(
        request,
        "employees.html",
        {
            "employees": employees_list,
            "employees_by_department": employees_by_department,
            "has_employees_without_department": has_employees_without_department,
            "api_error": api_error,
            "departments_error": dept_error,
            "departments_options": departments_options,
            "selected_department": selected_department,
            "search_query": search_query,
            "form_mode": mode,
            "form_initial": form_initial,
            "active_page": "employees",
        },
    )


def employee_create(request):
    if request.method != "POST":
        return redirect("employees")

    token_or_redirect = _get_required_token(request, "employees")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect

    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    passport_data = (request.POST.get("passport_data") or "").strip()
    dept_raw = request.POST.get("department_id")

    if not first_name or not last_name or not email or not passport_data:
        messages.error(request, "Заполните имя, фамилию, email и паспортные данные.")
        return redirect("employees")
    if len(passport_data) < 10:
        messages.error(request, "Паспортные данные — не менее 10 символов.")
        return redirect("employees")
    try:
        department_id = int(dept_raw)
    except (TypeError, ValueError):
        messages.error(request, "Выберите подразделение.")
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
    if request.method != "POST":
        return redirect("employees")

    token_or_redirect = _get_required_token(request, "employees")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect

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
    if request.method != "POST":
        return redirect("employees")

    token_or_redirect = _get_required_token(request, "employees")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect

    raw_id = request.POST.get("employee_id")
    try:
        employee_id = int(raw_id)
    except (TypeError, ValueError):
        messages.error(request, "Некорректный идентификатор сотрудника.")
        return redirect("employees")

    response = EmployeeController.delete_employee(employee_id, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при удалении.")
        return redirect("employees")
    if 200 <= response.status_code < 300:
        messages.success(request, "Сотрудник удален.")
        return redirect("employees")

    messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")


def reports(request):
    return render(request, "reports.html")


def _task_form_context(request):
    token = request.session.get("access_token")
    employees, employees_error = EmployeeController.get_employees(access_token=token)
    department_map, departments_error = DepartmentController.get_department_name_map()

    employees_options = []
    for row in employees:
        if not isinstance(row, dict):
            continue
        employee_id = row.get("id")
        if employee_id is None:
            continue
        full_name = " ".join(
            part for part in (
                row.get("last_name") or "",
                row.get("first_name") or "",
                row.get("middle_name") or "",
            ) if part
        ).strip()
        employees_options.append((employee_id, full_name or f"Сотрудник #{employee_id}"))
    employees_options.sort(key=lambda x: x[1].lower())

    departments_options = sorted(
        department_map.items(),
        key=lambda x: ((x[1] or "").lower(), x[0] or 0),
    )

    return {
        "employees_options": employees_options,
        "departments_options": departments_options,
        "employees_error": employees_error,
        "departments_error": departments_error,
        "form_data": {},
        "active_page": "tasks_create",
    }


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


def _render_task_create_with_form_data(request):
    context = _task_form_context(request)
    context["form_data"] = _task_form_data_from_post(request)
    return render(request, "tasks_create.html", context)


def task_create(request):
    if request.method != "POST":
        return render(request, "tasks_create.html", _task_form_context(request))

    token_or_redirect = _get_required_token(request, "task_create")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect

    payload = {}
    for key in ("title", "description", "priority"):
        value = (request.POST.get(key) or "").strip()
        if value:
            payload[key] = value

    start_date = (request.POST.get("start_date") or "").strip()
    if start_date:
        payload["planned_start_date"] = start_date

    end_date = (request.POST.get("end_date") or "").strip()
    if end_date:
        payload["planned_end_date"] = end_date

    status_value = (request.POST.get("status") or "").strip()
    if status_value:
        status_map = {
            "planned": 1,
            "in_progress": 2,
            "done": 3,
            "overdue": 4,
        }
        status_id = status_map.get(status_value)
        if status_id is None:
            messages.error(request, "Некорректный статус задачи.")
            return _render_task_create_with_form_data(request)
        payload["status_id"] = status_id

    for key in ("creator_id", "assignee_id", "department_id"):
        value = (request.POST.get(key) or "").strip()
        if not value:
            continue
        try:
            payload[key] = int(value)
        except ValueError:
            messages.error(request, f"Некорректное значение поля: {key}.")
            return _render_task_create_with_form_data(request)

    if not payload:
        messages.warning(request, "Нет данных для сохранения.")
        return _render_task_create_with_form_data(request)

    response = TasksController.create_task(payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при создании задачи.")
        return _render_task_create_with_form_data(request)
    if 200 <= response.status_code < 300:
        messages.success(request, "Задача создана.")
        return redirect("task_create")

    messages.error(
        request,
        f"Ошибка API (код {response.status_code}): {_extract_response_error(response)}",
    )
    return _render_task_create_with_form_data(request)

from collections import defaultdict

from django.contrib import messages
from django.shortcuts import redirect, render

from app.controllers.department_controller import DepartmentController
from app.controllers.employee_controller import EmployeeController
from app.controllers.user_controller import UserController
from app.views.common import (
    _available_users_for_employee_form,
    _default_employee_form,
    _extract_response_error,
    _get_required_token,
    _is_fuzzy_last_name_match,
    _resolve_user_scope,
)


def employees(request):
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
    users = []
    users_error = None
    if scope == "admin":
        users_response = UserController.get_users(access_token=token)
        if users_response is None:
            users_error = "Нет связи с API пользователей."
        elif 200 <= users_response.status_code < 300:
            try:
                payload = users_response.json()
            except ValueError:
                payload = {}
            users = payload.get("items") if isinstance(payload, dict) else []
        else:
            users_error = _extract_response_error(users_response)
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

    ordered_dept_ids = [did for did, _ in departments_options if did in by_dept and by_dept[did]]
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
                "user_id": (
                    str(selected_employee.get("user_id"))
                    if selected_employee.get("user_id") is not None
                    else ""
                ),
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

    users_options = _available_users_for_employee_form(
        users,
        employees_list,
        selected_user_id=form_initial.get("user_id"),
    )

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
            "users_options": users_options,
            "users_error": users_error,
            "user_scope": scope,
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
    scope, _ = _resolve_user_scope(request, token)
    if scope == "employee":
        messages.error(request, "У сотрудника нет прав на создание сотрудников.")
        return redirect("employees")

    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    passport_data = (request.POST.get("passport_data") or "").strip()
    dept_raw = request.POST.get("department_id")
    user_id_raw = (request.POST.get("user_id") or "").strip()
    flashed_form_initial = {
        "employee_id": "",
        "user_id": user_id_raw,
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
    if user_id_raw:
        try:
            payload["user_id"] = int(user_id_raw)
        except ValueError:
            messages.error(request, "Выберите корректного пользователя.")
            request.session["employees_form_mode"] = "add"
            request.session["employees_form_initial"] = flashed_form_initial
            request.session["employees_field_errors"] = {"user_id": "Выберите корректного пользователя."}
            return redirect("employees")
    for key in ("middle_name", "phone_number", "inn", "snils"):
        value = (request.POST.get(key) or "").strip()
        if value:
            payload[key] = value
    if scope == "manager":
        payload["_manager_mode"] = True
    response = EmployeeController.create_employee(payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при создании.")
    elif 200 <= response.status_code < 300:
        messages.success(request, "Сотрудник добавлен.")
    else:
        messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")


def employee_update(request):
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
    user_id_raw = (request.POST.get("user_id") or "").strip()
    if dept_raw:
        try:
            payload["department_id"] = int(dept_raw)
        except ValueError:
            messages.error(request, "Некорректный отдел.")
            return redirect("employees")
    payload["is_active"] = request.POST.get("is_active") == "on"
    if user_id_raw:
        try:
            payload["user_id"] = int(user_id_raw)
        except ValueError:
            messages.error(request, "Некорректный пользователь.")
            return redirect("employees")
    if scope == "manager":
        payload["_manager_mode"] = True
    response = EmployeeController.update_employee(employee_id, payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при сохранении.")
    elif 200 <= response.status_code < 300:
        messages.success(request, "Данные сотрудника обновлены.")
    else:
        messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")


def employee_delete(request):
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
    elif 200 <= response.status_code < 300:
        messages.success(request, "Сотрудник удален.")
    else:
        messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
    return redirect("employees")

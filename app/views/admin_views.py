from django.contrib import messages
from django.shortcuts import redirect, render

from app.controllers.department_controller import DepartmentController
from app.controllers.user_controller import UserController
from app.views.common import (
    _department_field_errors_from_api,
    _extract_response_error,
    _parse_int,
    _resolve_user_scope,
)


def admin_departments(request):
    token = request.session.get("access_token")
    scope, _ = _resolve_user_scope(request, token)
    if scope != "admin":
        messages.error(request, "Доступно только администратору.")
        return redirect("dashboard")

    department_form_data = {"name": "", "description": "", "manager_id": ""}
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
                "manager_id": (request.POST.get("manager_id") or "").strip(),
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
                manager_id = _parse_int(department_form_data.get("manager_id"))
                if manager_id is not None:
                    payload["department_manager_id"] = manager_id
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
    users_response = UserController.get_users(access_token=token)
    users_payload = {}
    if users_response is not None and 200 <= users_response.status_code < 300:
        try:
            users_payload = users_response.json()
        except ValueError:
            users_payload = {}
    users = users_payload.get("items") if isinstance(users_payload, dict) else []
    occupied_manager_ids = {
        row.get("department_manager_id")
        for row in departments
        if isinstance(row, dict) and row.get("department_manager_id") is not None
    }
    manager_options = []
    manager_name_by_id = {}
    for row in users:
        if not isinstance(row, dict):
            continue
        if row.get("role_id") != 2:
            continue
        user_id = row.get("id")
        manager_name = row.get("username") or f"manager#{user_id}"
        if user_id is not None:
            manager_name_by_id[user_id] = manager_name
        if user_id is None or user_id in occupied_manager_ids:
            continue
        manager_options.append((user_id, manager_name))
    manager_options.sort(key=lambda pair: pair[1].lower())
    for dep in departments:
        if not isinstance(dep, dict):
            continue
        current_manager_id = dep.get("department_manager_id")
        dep["department_manager_name"] = manager_name_by_id.get(current_manager_id, "")
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
            "manager_options": manager_options,
        },
    )


def admin_users(request):
    token = request.session.get("access_token")
    scope, _ = _resolve_user_scope(request, token)
    if scope != "admin":
        messages.error(request, "Доступно только администратору.")
        return redirect("dashboard")

    user_form_data = {"username": "", "password": "", "role_id": "3"}
    edit_form_data = {"id": "", "username": "", "password": "", "role_id": "3"}
    user_field_errors = {}
    edit_field_errors = {}

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
        elif action == "user_update":
            edit_form_data = {
                "id": (request.POST.get("user_id") or "").strip(),
                "username": (request.POST.get("username") or "").strip(),
                "password": (request.POST.get("password") or "").strip(),
                "role_id": (request.POST.get("role_id") or "").strip() or "3",
            }
            target_user_id = _parse_int(edit_form_data["id"])
            if target_user_id is None:
                edit_field_errors["user_id"] = "Некорректный пользователь."
            if not edit_form_data["username"]:
                edit_field_errors["username"] = "Поле обязательно."
            try:
                role_id_int = int(edit_form_data["role_id"])
                if role_id_int not in {1, 2, 3}:
                    raise ValueError
            except ValueError:
                role_id_int = 0
                edit_field_errors["role_id"] = "Выберите корректную роль."

            if edit_field_errors:
                messages.error(request, "Проверьте поля формы редактирования пользователя.")
            else:
                response = UserController.update_user_as_admin(
                    user_id=target_user_id,
                    username=edit_form_data["username"],
                    password=edit_form_data["password"],
                    role_id=role_id_int,
                    access_token=token,
                )
                if response is not None and 200 <= response.status_code < 300:
                    messages.success(request, "Профиль пользователя обновлен.")
                    return redirect("admin_users")
                messages.error(request, f"Ошибка API: {_extract_response_error(response)}")
        elif action == "user_delete":
            target_user_id = _parse_int((request.POST.get("user_id") or "").strip())
            if target_user_id is None:
                messages.error(request, "Некорректный пользователь.")
            else:
                response = UserController.delete_user_as_admin(
                    user_id=target_user_id,
                    access_token=token,
                )
                if response is not None and 200 <= response.status_code < 300:
                    messages.success(request, "Профиль пользователя удален.")
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
            "edit_form_data": edit_form_data,
            "edit_field_errors": edit_field_errors,
        },
    )

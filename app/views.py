from collections import defaultdict

from django.contrib import messages
from django.shortcuts import render, redirect
from app.controllers.user_controller import UserController
from app.controllers.employee_controller import EmployeeController
from app.controllers.department_controller import DepartmentController

def auth(request):
    if request.method == 'POST':
        response = UserController.login_user(
            username=request.POST.get('username'),
            password=request.POST.get('password'),
        )

        if response is not None and 200 <= response.status_code < 300:
            try:
                data = response.json()
            except Exception:
                data = {}

            request.session['is_authenticated'] = True
            if data.get('access_token'):
                request.session['access_token'] = data['access_token']

            return redirect('dashboard')

        status = response.status_code if response is not None else 'нет ответа'
        message = None
        if response is not None:
            try:
                data = response.json()
                message = data.get('detail') or data.get('error') or str(data)
            except Exception:
                message = None

        context = {
            'error': f'Ошибка авторизации: {status}',
        }
        if message:
            context['error_message'] = message

        return render(request, 'auth.html', context)

    return render(request, template_name='auth.html')
def dashboard(request):
    return render(request, 'dashboard.html')
def employees(request):
    token = request.session.get('access_token')
    employees_list, api_error = EmployeeController.get_employees(access_token=token)

    selected_department = (request.GET.get("department") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    mode = (request.GET.get("mode") or "").strip().lower()
    edit_id_raw = (request.GET.get("edit_id") or "").strip()

    dept_names, dept_error = DepartmentController.get_department_name_map()
    for row in employees_list:
        if isinstance(row, dict):
            did = row.get("department_id")
            row["department_name"] = dept_names.get(did) if did is not None else None

    # Справочник для select в модалке: из API + отделы только из списка сотрудников
    form_departments = dict(dept_names)
    for row in employees_list:
        if isinstance(row, dict):
            did = row.get("department_id")
            if did is not None and did not in form_departments:
                form_departments[did] = f"Отдел №{did}"
    departments_options = sorted(
        form_departments.items(),
        key=lambda x: ((x[1] or "").lower(), x[0] or 0),
    )

    filtered_employees = []
    search_query_norm = search_query.lower()
    for row in employees_list:
        if not isinstance(row, dict):
            continue

        dept_val = row.get("department_id")
        if selected_department:
            if selected_department == "__none__":
                if dept_val is not None:
                    continue
            else:
                if str(dept_val) != selected_department:
                    continue

        if search_query_norm:
            last_name = (row.get("last_name") or "").lower()
            if search_query_norm not in last_name:
                continue

        filtered_employees.append(row)

    by_dept = defaultdict(list)
    for row in filtered_employees:
        if isinstance(row, dict):
            by_dept[row.get("department_id")].append(row)

    ordered_dept_ids = []
    for did, _ in departments_options:
        if did in by_dept and by_dept[did]:
            ordered_dept_ids.append(did)
    for did in sorted(k for k in by_dept if k is not None):
        if did not in ordered_dept_ids:
            ordered_dept_ids.append(did)
    if None in by_dept and by_dept[None]:
        ordered_dept_ids.append(None)

    employees_by_department = []
    for did in ordered_dept_ids:
        people = by_dept[did]
        if not people:
            continue
        if did is None:
            dept_title = "Без подразделения"
        else:
            dept_title = form_departments.get(did, f"Отдел №{did}")
        employees_by_department.append(
            {"id": did, "name": dept_title, "employees": people}
        )

    has_employees_without_department = bool(
        any(isinstance(row, dict) and row.get("department_id") is None for row in employees_list)
    )

    edit_employee_id = None
    if edit_id_raw:
        try:
            edit_employee_id = int(edit_id_raw)
            mode = "edit"
        except (TypeError, ValueError):
            edit_employee_id = None

    form_initial = {
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

    if mode == "edit" and edit_employee_id is not None:
        selected_employee = next(
            (
                row for row in employees_list
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
        'employees.html',
        context={
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

    token = request.session.get("access_token")
    if not token:
        messages.error(request, "Войдите в систему (нужен токен для API).")
        return redirect("employees")

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

    middle_name = (request.POST.get("middle_name") or "").strip()
    if middle_name:
        payload["middle_name"] = middle_name

    phone_number = (request.POST.get("phone_number") or "").strip()
    if phone_number:
        payload["phone_number"] = phone_number

    inn = (request.POST.get("inn") or "").strip()
    if inn:
        payload["inn"] = inn

    snils = (request.POST.get("snils") or "").strip()
    if snils:
        payload["snils"] = snils

    response = EmployeeController.create_employee(payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при создании.")
        return redirect("employees")

    if 200 <= response.status_code < 300:
        messages.success(request, "Сотрудник добавлен.")
        return redirect("employees")

    try:
        data = response.json()
        detail = data.get("detail")
        if isinstance(detail, list):
            detail = str(detail)
        msg = detail or str(data)
    except Exception:
        msg = response.text or f"Код {response.status_code}"
    messages.error(request, f"Ошибка API: {msg}")
    return redirect("employees")


def employee_update(request):
    if request.method != "POST":
        return redirect("employees")

    token = request.session.get("access_token")
    if not token:
        messages.error(request, "Войдите в систему (нужен токен для API).")
        return redirect("employees")

    raw_id = request.POST.get("employee_id")
    try:
        employee_id = int(raw_id)
    except (TypeError, ValueError):
        messages.error(request, "Некорректный идентификатор сотрудника.")
        return redirect("employees")

    payload = {}
    mapping = (
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("middle_name", "middle_name"),
        ("phone_number", "phone_number"),
        ("email", "email"),
        ("passport_data", "passport_data"),
    )
    for form_key, api_key in mapping:
        val = (request.POST.get(form_key) or "").strip()
        if val != "":
            payload[api_key] = val

    inn = (request.POST.get("inn") or "").strip()
    if inn:
        payload["inn"] = inn

    snils = (request.POST.get("snils") or "").strip()
    if snils:
        payload["snils"] = snils

    dept_raw = request.POST.get("department_id")
    if dept_raw is not None and str(dept_raw).strip() != "":
        try:
            payload["department_id"] = int(dept_raw)
        except ValueError:
            messages.error(request, "Некорректный отдел.")
            return redirect("employees")

    if request.POST.get("is_active") == "on":
        payload["is_active"] = True
    else:
        payload["is_active"] = False

    if not payload:
        messages.warning(request, "Нет данных для сохранения.")
        return redirect("employees")

    response = EmployeeController.update_employee(employee_id, payload, access_token=token)
    if response is None:
        messages.error(request, "Не удалось связаться с API при сохранении.")
        return redirect("employees")

    if 200 <= response.status_code < 300:
        messages.success(request, "Данные сотрудника обновлены.")
        return redirect("employees")

    try:
        data = response.json()
        detail = data.get("detail")
        if isinstance(detail, list):
            detail = str(detail)
        msg = detail or str(data)
    except Exception:
        msg = response.text or f"Код {response.status_code}"
    messages.error(request, f"Ошибка API: {msg}")
    return redirect("employees")
def reports(request):
    return render(request, 'reports.html')
def task_create(request):
    return render(request, 'tasks_create.html')
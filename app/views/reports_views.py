from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render

from app.controllers.department_controller import DepartmentController
from app.controllers.employee_controller import EmployeeController
from app.controllers.tasks_controller import TasksController
from app.controllers.user_controller import UserController
from app.views.common import (
    _build_employee_options,
    _build_employees_report_excel,
    _build_monthly_employee_stats,
    _build_tasks_report_excel,
    _is_task_done,
    _is_task_overdue_by_date,
    _parse_int,
    _period_label,
    _resolve_user_scope,
    _task_form_context,
    _task_report_date,
    _xlsx_response,
)


def reports(request):
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
        if _is_task_overdue_by_date(row, today=today):
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

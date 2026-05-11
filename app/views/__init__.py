from app.views.admin_views import admin_departments, admin_users
from app.views.auth_views import auth, logout_view, no_access, profile_change_password
from app.views.employees_views import employee_create, employee_delete, employee_update, employees
from app.views.reports_views import reports
from app.views.tasks_views import (
    dashboard,
    dashboard_task_status_update,
    task_create,
    task_detail,
)

__all__ = [
    "admin_departments",
    "admin_users",
    "auth",
    "dashboard",
    "dashboard_task_status_update",
    "employee_create",
    "employee_delete",
    "employee_update",
    "employees",
    "logout_view",
    "no_access",
    "profile_change_password",
    "reports",
    "task_create",
    "task_detail",
]

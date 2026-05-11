"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from app import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('auth/', views.auth, name='auth'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/change-password/', views.profile_change_password, name='profile_change_password'),
    path('no-access/', views.no_access, name='no_access'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/tasks/<int:task_id>/', views.task_detail, name='task_detail'),
    path('dashboard/tasks/status-update/', views.dashboard_task_status_update, name='dashboard_task_status_update'),
    path('employees/', views.employees, name='employees'),
    path('employees/create/', views.employee_create, name='employee_create'),
    path('employees/update/', views.employee_update, name='employee_update'),
    path('employees/delete/', views.employee_delete, name='employee_delete'),
    path('reports/', views.reports, name='reports'),
    path('management/departments/', views.admin_departments, name='admin_departments'),
    path('management/users/', views.admin_users, name='admin_users'),
    path('task_create/', views.task_create, name='task_create'),
]

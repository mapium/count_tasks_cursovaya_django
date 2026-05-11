from django.contrib import messages
from django.shortcuts import redirect, render

from app.controllers.user_controller import UserController
from app.views.common import _extract_response_error, _get_required_token


def auth(request):
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


def profile_change_password(request):
    token_or_redirect = _get_required_token(request, "auth")
    if not isinstance(token_or_redirect, str):
        return token_or_redirect
    token = token_or_redirect

    field_errors = {}
    form_data = {"old_password": "", "new_password": "", "confirm_password": ""}
    if request.method == "POST":
        form_data = {
            "old_password": (request.POST.get("old_password") or "").strip(),
            "new_password": (request.POST.get("new_password") or "").strip(),
            "confirm_password": (request.POST.get("confirm_password") or "").strip(),
        }
        if not form_data["old_password"]:
            field_errors["old_password"] = "Поле обязательно."
        if not form_data["new_password"]:
            field_errors["new_password"] = "Поле обязательно."
        elif len(form_data["new_password"]) < 4:
            field_errors["new_password"] = "Минимум 4 символа."
        if form_data["new_password"] != form_data["confirm_password"]:
            field_errors["confirm_password"] = "Пароли не совпадают."

        if field_errors:
            messages.error(request, "Проверьте корректность полей формы.")
        else:
            response = UserController.change_my_password(
                old_password=form_data["old_password"],
                new_password=form_data["new_password"],
                access_token=token,
            )
            if response is not None and 200 <= response.status_code < 300:
                messages.success(request, "Пароль успешно изменен.")
                return redirect("dashboard")
            messages.error(request, f"Ошибка API: {_extract_response_error(response)}")

    return render(
        request,
        "profile_change_password.html",
        {
            "form_data": form_data,
            "field_errors": field_errors,
            "active_page": "",
        },
    )


def no_access(request):
    return render(request, "no_access.html")


def logout_view(request):
    request.session.flush()
    return redirect("auth")

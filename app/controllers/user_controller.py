from app.controllers.base_controller import BaseController


class UserController:
    @staticmethod
    def login_user(username: str, password: str):
        """Авторизует пользователя через endpoint `auth/login`.
        Отправляет form-urlencoded payload и возвращает raw HTTP-ответ API.
        """
        payload = {
            'username': username,
            'password': password,
        }
        response = BaseController.request(
            "post",
            "auth/login",
            data=payload,
            headers=BaseController.build_headers(content_type="application/x-www-form-urlencoded"),
        )
        return response

    @staticmethod
    def logout_user():
        """Заглушка для выхода пользователя на стороне клиента.
        Сейчас не вызывает API и всегда возвращает `None`.
        """
        return None

    @staticmethod
    def get_users(access_token=None):
        """Запрашивает список пользователей из API.
        Передает Bearer токен и возвращает HTTP-ответ без дополнительной обработки.
        """
        return BaseController.request(
            "get",
            "users",
            headers=BaseController.build_headers(access_token=access_token),
        )

    @staticmethod
    def create_user_as_admin(username: str, password: str, role_id: int, access_token=None):
        """Создает пользователя от имени администратора через `accounts/sign_up_as_admin`.
        Передает логин, пароль и роль как form-urlencoded данные.
        """
        payload = {
            "username": username,
            "password": password,
            "role_id": str(role_id),
        }
        return BaseController.request(
            "post",
            "accounts/sign_up_as_admin",
            data=payload,
            headers=BaseController.build_headers(
                access_token=access_token,
                content_type="application/x-www-form-urlencoded",
            ),
        )

    @staticmethod
    def get_me(access_token=None):
        """Получает профиль текущего пользователя (`users/me`).
        Используется для определения роли и контекста текущей сессии.
        """
        return BaseController.request(
            "get",
            "users/me",
            headers=BaseController.build_headers(access_token=access_token),
        )

    @staticmethod
    def change_my_password(old_password: str, new_password: str, access_token=None):
        payload = {
            "old_password": old_password,
            "new_password": new_password,
        }
        return BaseController.request(
            "post",
            "users/me/change-password",
            data=payload,
            headers=BaseController.build_headers(
                access_token=access_token,
                content_type="application/x-www-form-urlencoded",
            ),
        )

    @staticmethod
    def update_user_as_admin(user_id: int, username: str, role_id: int, password: str = "", access_token=None):
        payload = {
            "username": username,
            "role_id": str(role_id),
            "password": password or "",
        }
        return BaseController.request(
            "put",
            f"users/{int(user_id)}",
            data=payload,
            headers=BaseController.build_headers(
                access_token=access_token,
                content_type="application/x-www-form-urlencoded",
            ),
        )

    @staticmethod
    def delete_user_as_admin(user_id: int, access_token=None):
        return BaseController.request(
            "delete",
            f"users/{int(user_id)}",
            headers=BaseController.build_headers(access_token=access_token),
        )

    @staticmethod
    def register_user(username: str, password: str):
        """Регистрирует обычного пользователя через публичный endpoint API.
        Пытается отправить form-urlencoded payload в стандартные пути регистрации.
        """
        payload = {
            "username": username,
            "password": password,
            "role_id": "3",
        }
        headers = BaseController.build_headers(content_type="application/x-www-form-urlencoded")
        response = BaseController.request(
            "post",
            endpoint="accounts/sign_up",
            data=payload,
            headers=headers,
        )
        if response.status_code != 404:
            return response
        return headers

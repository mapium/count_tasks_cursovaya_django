from app.controllers.base_controller import BaseController


class UserController:
    @staticmethod
    def login_user(username: str, password: str):
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
        return None

    @staticmethod
    def get_users(access_token=None):
        return BaseController.request(
            "get",
            "users",
            headers=BaseController.build_headers(access_token=access_token),
        )

    @staticmethod
    def create_user_as_admin(username: str, password: str, role_id: int, access_token=None):
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
        return BaseController.request(
            "get",
            "users/me",
            headers=BaseController.build_headers(access_token=access_token),
        )

import requests
from core import settings


base_url = settings.BASE_URL


class UserController:
    @staticmethod
    def login_user(username: str, password: str):
        payload = {
            'username': username,
            'password': password,
        }
        response = requests.post(
            f'{base_url}/api/v1/auth/login',
            data=payload,
        )
        return response

    @staticmethod
    def logout_user():
        return None

import requests
from core import settings

base_url = settings.BASE_URL

class TasksController:
    @staticmethod
    def create_task(payload, access_token=None):
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            return requests.post(
                f"{base_url}/api/v1/tasks",
                json=payload,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException:
            return None
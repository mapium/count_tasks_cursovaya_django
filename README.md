# count_tasks_cursovaya_django

Приложение работает с внешним API (по умолчанию: `http://127.0.0.1:8001`).

## Необходимо

- Python 3.11+ (рекомендуется)
- Запущенный backend API на `127.0.0.1:8001`  
  (или поменяйте `BASE_URL` в `core/settings.py`)


### Запуск

.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

После запуска:

- веб-приложение: [http://127.0.0.1:8000/auth/](http://127.0.0.1:8000/auth/)
- страница без доступа: [http://127.0.0.1:8000/no-access/](http://127.0.0.1:8000/no-access/)

## Важно

- Если API запущен не на `127.0.0.1:8001`, поменяйте `BASE_URL` в `core/settings.py`.

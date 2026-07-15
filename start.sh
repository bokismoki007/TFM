#!/bin/bash
python manage.py collectstatic --noinput
python manage.py migrate
python manage.py createsuperuser --noinput || true
gunicorn autoinsight.wsgi:application --bind 0.0.0.0:8000
#!/bin/bash
python manage.py collectstatic --noinput
python manage.py migrate
python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); not User.objects.filter(username='admin').exists() and User.objects.create_superuser('admin', 'admin@test.com', '0J.8h]9eL47h')"
gunicorn autoinsight.wsgi:application --bind 0.0.0.0:8000
#!/bin/bash

python manage.py collectstatic --no-input
PORT=9070
exec gunicorn \
    --bind 0.0.0.0:$PORT \
    --access-logfile - \
    --timeout 300 \
    conf.wsgi:application -w 2

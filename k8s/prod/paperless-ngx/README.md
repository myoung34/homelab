Paperless
=========


## First time set up

### PSQL

```
psql=# CREATE user "<changeme>" with password '<changeme>';
CREATE ROLE
psql=# create database paperless;
CREATE DATABASE
paperless=# ALTER database paperless owner to "<changeme>";
ALTER DATABASE
```

### user

From inside the container

```
# python3 manage.py createsuperuser
Username (leave blank to use 'root'): foo
Email address: foo@email.com
Password:
Password (again):
Superuser created successfully.
```

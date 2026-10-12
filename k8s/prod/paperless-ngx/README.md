Paperless
=========


## First time set up

### PSQL

Sanity check the user
```
k -n paperless-ngx get secrets/paperless-ngx -oyaml | grep PAPERLESS_DBUSER | awk '{print $2}' | base64 -d
changeme%
```

```
CREATE user "changeme" with password 'changeme';
create database paperless;
ALTER database paperless owner to "changeme";
ALTER SCHEMA public OWNER TO "changeme";
GRANT CONNECT ON DATABASE paperless TO "changeme";
GRANT USAGE ON SCHEMA public TO "changeme";
GRANT CREATE ON SCHEMA public TO "changeme";
GRANT ALL ON SCHEMA public TO "changeme";
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


## Backup/restore

**in progress**

Restoring from psql + longhorn should be possible but its not ready yet

The current lazy way:

* exec into the pod
* `export _date=$(date '+%Y%m%d%H%M%S')`
* `mkdir /opt/paperless/backup/${_date}`
* `chown 1000:1000 /opt/paperless/backup/${_date}`
* `document_exporter /opt/paperless/backup/${_date}`
* `kubectl cp paperless-ngx/{podname}:/opt/paperless/backup .`
* `tar czf $(date '+%Y%m%d%H%M%S').tgz {backup}`
* upload that to s3 (minio creds are in `argocd/argowf`):

```bash
# aws cli v2 sends checksums minio rejects ("invalid/unknown checksum sent")
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required
export AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=$(kubectl -n argocd get secret argowf -o jsonpath='{.data.MINIO_ACCESS_KEY_ID}' | base64 -d)
export AWS_SECRET_ACCESS_KEY=$(kubectl -n argocd get secret argowf -o jsonpath='{.data.MINIO_SECRET_ACCESS_KEY}' | base64 -d)
aws --endpoint-url http://192.168.3.2:9000 s3 cp {date}.tgz s3://backups/paperless/
```

* `rm -rf /opt/paperless/backup/${_date}` in the pod

To restore:

* drop database and re-run psql above, `rm -rf /opt/paperless/media /opt/paperless/data`, restart pod
* `kubectl cp {backup} paperless-ngx/{podname}:/opt/paperless/backup`
* `document_importer /opt/paperless/backup/{backup}`

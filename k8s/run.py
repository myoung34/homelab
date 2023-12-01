import requests
import re
import json
import base64
import os

GH_USER='myoung34',
GH_TOKEN=os.environ.get('GH_TOKEN')
def whatever(upstream, filename_url, original_string, string_to_replace, tag) -> bool:
    current_version = requests.get(
        f'{filename_url}/../.version?ref=main',
        headers={'Accept': 'application/vnd.github.v3.raw'},
        auth=(GH_USER, GH_TOKEN)
    )
    if tag == current_version.text.strip():
        print(f'No change between {tag} and {current_version.text.strip()}. Nothing to do.')
        return False

    print(f'Found change between {tag} and {current_version.text.strip()}. Keep on keepin on')
    req = requests.get(
        f'{filename_url}?ref=main',
        headers={'Accept': 'application/vnd.github.v3+json'},
        auth=(GH_USER, GH_TOKEN)
    )
    req.raise_for_status()
    new_contents = re.sub(
        original_string,
        string_to_replace,
        base64.b64decode(req.json()['content']).decode("utf-8"),
    )

    # Update the real file
    payload_body = {
        "message": f"[Automated :robot: ] Bump {upstream} from {current_version.text.strip()} to {tag}",
        "committer": {
            "name": "Marcus Young",
            "email": "myoung34@my.apsu.edu"
        },
        "sha": req.json()['sha'],
        "content": base64.b64encode(new_contents.encode('ascii')).decode('utf-8')
    }

    _req = requests.put(
        filename_url,
        headers={'Accept': 'application/vnd.github.v3+json'},
        auth=(GH_USER, GH_TOKEN),
        data=json.dumps(payload_body).encode("utf-8")
    )
    _req.raise_for_status()

   # Update the version file
    version_payload_body = {
        "message": f"[Automated :robot: ] Bump version file for {upstream} from {current_version.text.strip()} to {tag}",
        "committer": {
            "name": "Marcus Young",
            "email": "myoung34@my.apsu.edu"
        },
        "sha": requests.get(
            f'{filename_url}/../.version?ref=main',
            headers={'Accept': 'application/vnd.github.v3+json'},
            auth=(GH_USER, GH_TOKEN)
        ).json()['sha'],
        "content": base64.b64encode(f'{tag}\n'.encode('ascii')).decode('utf-8')
    }

    _req = requests.put(
        f'{filename_url}/../.version',
        headers={'Accept': 'application/vnd.github.v3+json'},
        auth=(GH_USER, GH_TOKEN),
        data=json.dumps(version_payload_body).encode("utf-8")
    )
    _req.raise_for_status()



    return True

def do_work():
    updates = [
        {
            'upstream': 'myoung34/atlantis',
            'filename_url': 'k8s/prod/atlantis/kustomization.yaml',
            'original_string': r"      tag: 'v[0-9\.]+'",
            'string_to_replace': "      tag: '{}'",
        },
        {
            'upstream': 'esphome/esphome',
            'filename_url': 'k8s/prod/esphome/esphome.yaml',
            'original_string': r"        image: esphome/esphome:[0-9\.]+",
            'string_to_replace': r"        image: esphome/esphome:{}",
        },
        {
            'upstream': 'home-assistant/core',
            'filename_url': 'k8s/prod/hass/hass.yaml',
            'original_string': r"        image: ghcr.io/home-assistant/home-assistant:[0-9\.]+",
            'string_to_replace': "        image: ghcr.io/home-assistant/home-assistant:{}",
        },
        {
            'upstream': 'rancher/local-path-provisioner',
            'filename_url': 'k8s/prod/local-path-storage/chart.yaml',
            'original_string': r"        image: rancher/local-path-provisioner:v[0-9\.]+",
            'string_to_replace': r"        image: rancher/local-path-provisioner:{}",
        },
        {
            'upstream': 'eclipse/mosquitto',
            'filename_url': 'k8s/prod/mosquitto/mosquitto.yaml',
            'original_string': r"        image: eclipse-mosquitto:[0-9\.]+",
            'string_to_replace': r"        image: eclipse-mosquitto:{}",
            'strip_v': True,
        },
        {
            'upstream': 'Koenkk/zigbee2mqtt',
            'filename_url': 'k8s/prod/zigbee2mqtt/zigbee2mqtt.yaml',
            'original_string': r"        image: koenkk/zigbee2mqtt:[0-9\.]+",
            'string_to_replace': r"        image: koenkk/zigbee2mqtt:{}",
        },
        {
            'upstream': 'zwave-js/zwave-js-ui',
            'filename_url': 'k8s/prod/zwave-js-ui/zwave.yaml',
            'original_string': r'          image: "zwavejs/zwave-js-ui:[0-9\.]+"',
            'string_to_replace': r'          image: "zwavejs/zwave-js-ui:{}"',
            'strip_v': True,
        },
    ]
    for update in updates:
        tag = None
        try:
            tag = requests.get(
                f'https://api.github.com/repos/{update["upstream"]}/releases/latest',
                headers={ 'Accept': 'application/vnd.github.v3+json'},
                auth=(GH_USER, GH_TOKEN)
            ).json()['tag_name']
            print(f'Got tag {tag} for {update["upstream"]}')
        except KeyError:
            tag = requests.get(
                f'https://api.github.com/repos/{update["upstream"]}/tags',
                headers={ 'Accept': 'application/vnd.github.v3+json'},
                auth=(GH_USER, GH_TOKEN)
            ).json()[0]['name']
            print(f'Got tag by name {tag} for {update["upstream"]}')

        if update.get('strip_v', False):
            print(f'Got strip_v, fixing tag to {tag[1:]}')
            tag = tag[1:]

        print(f'Want to update {update["upstream"]} from {tag} to {update["string_to_replace"].format(tag)}')
        updated = whatever(
            upstream=update['upstream'],
            filename_url=f'https://api.github.com/repos/myoung34/homelab/contents/{update["filename_url"]}',
            original_string=update['original_string'],
            string_to_replace=update['string_to_replace'].format(tag),
            tag=tag,
        )
        if updated:
            print(f'Updated {update["filename_url"]} to {tag}')
        else:
            print(f'No update needed for {update["filename_url"]}')


if __name__ == '__main__':
    do_work()

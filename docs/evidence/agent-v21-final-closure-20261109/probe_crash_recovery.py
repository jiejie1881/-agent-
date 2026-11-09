"""Fault injection against the dedicated synthetic fixture on the acceptance stack."""
import json
import os
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4

import requests


STACK = 'logistics-v21-closure-20261109'
FIXTURE = STACK + '-synthetic'


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def main():
    synthetic = os.environ['V21_SYNTHETIC_URL']
    peer = os.environ['V21_BACKEND_B']
    assert all(urlsplit(url).hostname == '127.0.0.1' for url in (synthetic, peer))
    assert synthetic != peer
    assert docker('inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', FIXTURE) == STACK
    output = {'provider': 'synthetic_fixture'}
    with requests.Session() as client:
        client.trust_env = False
        login = client.post(peer + '/api/v1/auth/login', json={
            'username': 'v21-closure-a', 'password': os.environ['V21_PROBE_PASSWORD']})
        login.raise_for_status()
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}

        def run(scenario):
            created = client.post(synthetic + '/api/v1/agent/conversations', headers=headers)
            created.raise_for_status()
            path = f"/api/v1/agent/conversations/{created.json()['id']}"
            op = {**headers, 'Idempotency-Key': 'closure-fault-' + uuid4().hex}
            payload = {'message': '查看车辆'}
            first_event = None
            report = None
            with client.post(synthetic + path + '/stream', headers=op, json=payload, stream=True, timeout=45) as stream:
                stream.raise_for_status()
                for raw_line in stream.iter_lines(chunk_size=1):
                    line = raw_line.decode('utf-8')
                    if not line.startswith('data: '):
                        continue
                    event = json.loads(line[6:])
                    if first_event is None:
                        first_event = event
                    if report is not None or event['event_type'] != 'token':
                        continue
                    reports = client.get(peer + path + '/executions', headers=headers)
                    reports.raise_for_status()
                    report = next(item for item in reports.json() if item['status'] == 'RUNNING')
                    execution_path = path + '/executions/' + report['execution_id']
                    if scenario == 'cancel':
                        response = client.post(peer + execution_path + '/cancel', headers=headers)
                        response.raise_for_status()
                        output['peer_cancel_requested'] = response.json()['cancellation_requested']
                    else:
                        docker('kill', '--signal=KILL', FIXTURE)
                        break
            assert first_event is not None and report is not None
            persisted = client.get(peer + path + '/executions', headers=headers)
            persisted.raise_for_status()
            saved = next(item for item in persisted.json() if item['execution_id'] == report['execution_id'])
            if scenario == 'cancel':
                output.update(cancel_terminal=saved['status'], cancel_trace_id=first_event['trace_id'])
                return
            output.update(after_kill_status=saved['status'], can_resume=saved['can_resume'],
                          recovery_reason=saved['recovery_reason'], crash_trace_id=first_event['trace_id'])
            journal = client.get(peer + path + '/stream/events', headers=headers,
                                 params={'message_id': first_event['message_id']})
            journal.raise_for_status()
            output['journal_event_types'] = [event['event_type'] for event in journal.json()]
            repeated = client.post(peer + path + '/stream', headers=op, json=payload)
            output['duplicate_after_crash_status'] = repeated.status_code
            docker('start', FIXTURE)
            restarted = 'http://' + docker('port', FIXTURE, '8000/tcp')
            assert urlsplit(restarted).hostname == '127.0.0.1'
            for _ in range(30):
                try:
                    if client.get(restarted + '/health/ready', timeout=2).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError('Fixture did not become ready after restart')
            resumed = client.post(restarted + execution_path + '/resume', headers=headers, timeout=30)
            output['explicit_resume_http'] = resumed.status_code
            output['explicit_resume_status'] = resumed.json().get('status')
            output['explicit_resume_error_code'] = resumed.json().get('code')

        try:
            run('cancel')
            run('crash')
        finally:
            if docker('inspect', '-f', '{{.State.Running}}', FIXTURE) != 'true':
                docker('start', FIXTURE)
            print(json.dumps(output))


if __name__ == '__main__':
    main()

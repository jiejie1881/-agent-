"""Read/write only against the two new loopback acceptance backends."""
import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def main():
    first, second = os.environ['V21_BACKEND_A'], os.environ['V21_BACKEND_B']
    assert first != second
    for endpoint in (first, second):
        assert urlsplit(endpoint).hostname == '127.0.0.1'
    with httpx.Client(timeout=30, trust_env=False) as client:
        def login(base, username):
            result = client.post(base + '/api/v1/auth/login', json={
                'username': username, 'password': os.environ['V21_PROBE_PASSWORD']})
            result.raise_for_status()
            return {'Authorization': 'Bearer ' + result.json()['access_token']}

        a, b = login(first, 'v21-closure-a'), login(second, 'v21-closure-b')
        created = client.post(first + '/api/v1/agent/conversations', headers=a)
        assert created.status_code == 201
        conversation = created.json()['id']
        path = f'/api/v1/agent/conversations/{conversation}'
        assert client.get(second + path, headers=a).status_code == 200
        assert client.get(second + path, headers=b).status_code == 404
        assert client.post(second + path + '/stream/cancel', headers=b).status_code == 404
        operation = 'closure-' + uuid4().hex
        headers = {**a, 'Idempotency-Key': operation}
        payload = {'message': '查询今天合成业务库中的车辆'}
        result = client.post(first + path + '/stream', headers=headers, json=payload)
        assert result.status_code == 200
        events = [json.loads(line.removeprefix('data: ')) for line in result.text.splitlines()
                  if line.startswith('data: ')]
        assert events[0]['event_type'] == 'message_start'
        assert events[-1]['event_type'] == 'error'
        message = events[0]['message_id']
        saved = client.get(second + path + '/stream/events', headers=a,
                           params={'message_id': message})
        assert saved.status_code == 200 and saved.json() == events
        repeated = client.post(second + path + '/stream', headers=headers, json=payload)
        assert repeated.status_code == 409
        print(json.dumps({'status': 'PASS', 'conversation_id': conversation, 'trace_id': events[0]['trace_id'],
                          'event_types': [e['event_type'] for e in events], 'duplicate_status': 409,
                          'checks': ['shared_mysql_conversation', 'other_user_read_denied',
                                     'other_user_cancel_denied', 'shared_event_journal',
                                     'duplicate_operation_blocked'],
                          'active_cross_instance_cancel': 'NOT RUN', 'provider': 'NOT RUN'}))


if __name__ == '__main__':
    main()

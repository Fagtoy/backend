# Copyright The IETF Trust 2021, All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# We always check result.is_json, so result.json will never return None.
# pyright: reportOptionalSubscript=false

__author__ = 'Richard Zilincik'
__copyright__ = 'Copyright The IETF Trust 2021, All Rights Reserved'
__license__ = 'Apache License, Version 2.0'
__email__ = 'richard.zilincik@pantheon.tech'

import json
import os
import shutil
import unittest
from copy import deepcopy
from unittest import mock

from redis import RedisError

import api.views.userSpecificModuleMaintenance.moduleMaintenance as mm
from api.globalConfig import yc_gc
from api.views.admin.admin import hash_pw
from api.yangCatalogApi import app
from redisConnections.redis_users_connection import RedisUsersConnection


class MockRepoUtil:
    local_dir = 'test'

    def __init__(self, repourl, logger=None):
        pass

    def get_commit_hash(self, path=None, branch='master'):
        return branch


class TestApiContributeClass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources_path = os.path.join(os.environ['BACKEND'], 'tests/resources')
        cls.client = app.test_client()
        # TODO: Mock RedisUsersConnection to run on db=12 when running tests
        cls.users = RedisUsersConnection()

        with open(os.path.join(resources_path, 'payloads.json'), 'r') as f:
            cls.payloads_content = json.load(f)

        cls.send_patcher = mock.patch('api.yangCatalogApi.app.config.sender.send')
        cls.mock_send = cls.send_patcher.start()
        cls.addClassCleanup(cls.send_patcher.stop)
        cls.mock_send.return_value = 1

        cls.confd_patcher = mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_mod_redis')
        cls.mock_redis_get = cls.confd_patcher.start()
        cls.addClassCleanup(cls.confd_patcher.stop)
        cls.mock_redis_get.side_effect = mock_redis_get

        cls.get_patcher = mock.patch('requests.get')
        cls.mock_get = cls.get_patcher.start()
        cls.addClassCleanup(cls.get_patcher.stop)
        cls.mock_get.return_value.json.return_value = json.loads(yc_gc.redis.get('modules-data') or '{}')

    def setUp(self):
        self.uid = self.users.create(
            temp=False,
            username='test',
            password=hash_pw('test'),
            email='test@test.test',
            models_provider='test',
            first_name='test',
            last_name='test',
            access_rights_sdo='/',
            access_rights_vendor='/',
        )
        os.makedirs(yc_gc.save_requests, exist_ok=True)
        self.payloads_content = deepcopy(self.payloads_content)

    def tearDown(self):
        self.users.delete(self.uid, temp=False)
        shutil.rmtree(yc_gc.save_requests)

    @mock.patch('api.yangCatalogApi.app.config.redis_users.create', mock.MagicMock())
    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.MessageFactory', mock.MagicMock)
    def test_register_user(self):
        # we use a username different from "test" because such a user already exists
        body = {
            'username': 'tset',
            'password': 'tset',
            'password-confirm': 'tset',
            'email': 'tset',
            'company': 'tset',
            'first-name': 'tset',
            'last-name': 'tset',
            'motivation': 'tset',
        }
        result = self.client.post('api/register-user', json=body)

        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('info', data)
        self.assertEqual(data['info'], 'User created successfully')

    def test_register_user_no_data(self):
        result = self.client.post('api/register-user')

        self.assertEqual(result.status_code, 400)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('description', data)
        self.assertEqual(data['description'], 'bad request - no data received')

    def test_register_user_missing_field(self):
        body = {k: 'test' for k in ['username', 'password', 'password-confirm', 'email', 'company', 'first-name']}
        result = self.client.post('api/register-user', json=body)

        self.assertEqual(result.status_code, 400)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('description', data)
        self.assertEqual(data['description'], 'bad request - missing last-name data in input')

    def test_register_user_mismatched_passwd(self):
        body = {
            k: 'test'
            for k in [
                'username',
                'password',
                'password-confirm',
                'email',
                'company',
                'first-name',
                'last-name',
                'motivation',
            ]
        }
        body['password-confirm'] = 'different'
        result = self.client.post('api/register-user', json=body)

        self.assertEqual(result.status_code, 400)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('description', data)
        self.assertEqual(data['description'], 'Passwords do not match')

    def test_register_user_user_exist(self):
        body = {
            k: 'test'
            for k in [
                'username',
                'password',
                'password-confirm',
                'email',
                'company',
                'first-name',
                'last-name',
                'motivation',
            ]
        }
        result = self.client.post('api/register-user', json=body)

        self.assertEqual(result.status_code, 409)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('description', data)
        self.assertEqual(data['description'], 'User with username test already exists')

    @mock.patch('api.yangCatalogApi.app.config.redis_users.is_approved', mock.MagicMock(return_value=False))
    @mock.patch('api.yangCatalogApi.app.config.redis_users.is_temp', mock.MagicMock(return_value=True))
    def test_register_user_tempuser_exist(self):
        body = {
            k: 'test'
            for k in [
                'username',
                'password',
                'password-confirm',
                'email',
                'company',
                'first-name',
                'last-name',
                'motivation',
            ]
        }
        result = self.client.post('api/register-user', json=body)

        self.assertEqual(result.status_code, 409)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('description', data)
        self.assertEqual(data['description'], 'User with username test is pending for permissions')

    @mock.patch('api.yangCatalogApi.app.config.redis_users.username_exists', mock.MagicMock(side_effect=RedisError))
    def test_register_user_db_exception(self):
        body = {
            k: 'test'
            for k in [
                'username',
                'password',
                'password-confirm',
                'email',
                'company',
                'first-name',
                'last-name',
                'motivation',
            ]
        }
        result = self.client.post('api/register-user', json=body)

        self.assertEqual(result.status_code, 500)
        self.assertTrue(result.is_json)
        data = result.json
        self.assertIn('error', data)
        self.assertEqual(data['error'], 'Server problem connecting to database')

    def test_delete_modules_one_module(self):
        """Test correct action is taken for a valid deletion attempt."""
        name = 'yang-catalog'
        revision = '2018-04-03'
        organization = 'ietf'
        path = f'{name},{revision},{organization}'
        result = self.client.delete(f'api/modules/module/{path}', auth=('test', 'test'))

        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.content_type, 'application/json')
        data = json.loads(result.data)
        self.assertIn('info', data)
        self.assertEqual(data['info'], 'Verification successful')
        self.assertIn('job-id', data)
        self.assertEqual(data['job-id'], 1)

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_delete_modules_unavailable_module(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = ''
        mod = {'name': 'test', 'revision': '2017-01-01', 'organization': 'ietf'}
        path = f'{mod["name"]},{mod["revision"]},{mod["organization"]}'
        result = self.client.delete(f'api/modules/module/{path}', auth=('test', 'test'))

        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.content_type, 'application/json')
        data = json.loads(result.data)
        self.assertIn('info', data)
        self.assertEqual(data['info'], 'Verification successful')
        self.assertIn('job-id', data)
        self.assertEqual(data['job-id'], 1)

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_vendors(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = '/test/test/test/test'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        body = {
            'platforms': {
                'platform': [{'name': 'test', 'vendor': 'test', 'software-version': 'test', 'software-flavor': 'test'}],
            },
        }
        with app.app_context():
            result = mm.authorize_for_vendors(request, body)

        self.assertEqual(result, True)

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_vendors_root(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = '/'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        with app.app_context():
            result = mm.authorize_for_vendors(request, {})

        self.assertEqual(result, True)

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_vendors_missing_rights(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = 'test'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        body = {
            'platforms': {
                'platform': [
                    {'name': 'other', 'vendor': 'other', 'software-version': 'other', 'software-flavor': 'other'},
                ],
            },
        }
        with app.app_context():
            result = mm.authorize_for_vendors(request, body)

        self.assertEqual(result, 'vendor')

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_sdos_root(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = '/'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        with app.app_context():
            result = mm.authorize_for_sdos(request, 'test', 'test')

        self.assertTrue(result)

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_sdos(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = 'test'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        with app.app_context():
            result = mm.authorize_for_sdos(request, 'test', 'test')

        self.assertTrue(result)

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_sdos_not_same(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = '/'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        with app.app_context():
            result = mm.authorize_for_sdos(request, 'test', 'other')

        self.assertEqual(result, 'module`s organization is not the same as organization provided')

    @mock.patch('api.views.userSpecificModuleMaintenance.moduleMaintenance.get_user_access_rights')
    def test_authorize_for_sdos_not_in_rights(self, mock_access_rights: mock.MagicMock):
        mock_access_rights.return_value = 'test'
        request = mock.MagicMock()
        request.authorization = {'username': 'test'}
        with app.app_context():
            result = mm.authorize_for_sdos(request, 'test', 'other')

        self.assertEqual(result, 'module`s organization is not in users rights')

    @mock.patch('api.sender.Sender.get_response', mock.MagicMock(return_value='Failed#split#reason'))
    def test_get_job(self):
        job_id = 'invalid-id'
        result = self.client.get(f'api/job/{job_id}')

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content_type, 'application/json')
        data = json.loads(result.data)
        self.assertIn('info', data)
        self.assertIn('job-id', data['info'])
        self.assertEqual(data['info']['job-id'], 'invalid-id')
        self.assertIn('result', data['info'])
        self.assertEqual(data['info']['result'], 'Failed')
        self.assertIn('reason', data['info'])
        self.assertEqual(data['info']['reason'], 'reason')


def mock_redis_get(module: dict):
    file = f'{os.environ["BACKEND"]}/tests/resources/confd_responses/{module["name"]}@{module["revision"]}.json'
    if not os.path.isfile(file):
        return json.loads('{}')
    else:
        with open(file) as f:
            data = json.load(f)
            return data.get('yang-catalog:module')[0]


if __name__ == '__main__':
    unittest.main()

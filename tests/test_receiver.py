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

__author__ = 'Slavomir Mazur'
__copyright__ = 'Copyright The IETF Trust 2021, All Rights Reserved'
__license__ = 'Apache License, Version 2.0'
__email__ = 'slavomir.mazur@pantheon.tech'

import json
import os
import shutil
import unittest
from unittest import mock

from ddt import data, ddt
from redis import Redis

from api.receiver import Receiver
from api.status_message import StatusMessage
from redisConnections.redisConnection import RedisConnection
from utility.create_config import create_config


class MockModulesComplicatedAlgorithms:
    def __init__(
        self,
        log_directory: str,
        yangcatalog_api_prefix: str,
        credentials: list,
        save_file_dir: str,
        direc: str,
        all_modules,
        yang_models_dir: str,
        temp_dir: str,
        json_ytree: str,
    ):
        pass

    def parse_non_requests(self):
        pass

    def parse_requests(self):
        pass

    def populate(self):
        pass


class MockConfdService:
    def patch_modules(self, new_data: str):
        r = mock.MagicMock()
        r.status_code = 201
        return r

    def patch_vendors(self, new_data: str):
        r = mock.MagicMock()
        r.status_code = 201
        return r

    def delete_dependent(self, module_key: str, dependent: str):
        r = mock.MagicMock()
        r.status_code = 204
        return r

    def delete_module(self, module_key: str):
        r = mock.MagicMock()
        r.status_code = 204
        return r

    def delete_vendor(self, confd_suffix: str):
        r = mock.MagicMock()
        r.status_code = 204
        return r

    def delete_implementation(self, module_key: str, implementation_key: str):
        r = mock.MagicMock()
        r.status_code = 204
        return r


class MockRepoUtil:
    localdir = 'test'

    def __init__(self, repourl, logger=None):
        pass

    def clone(self):
        pass

    def get_commit_hash(self, path=None, branch='master'):
        return branch

    def remove(self):
        pass


class TestReceiverBaseClass(unittest.TestCase):
    receiver: Receiver
    redis_connection: RedisConnection
    directory: str
    test_data: dict

    @classmethod
    def setUpClass(cls):
        config = create_config()
        cls.log_directory = config.get('Directory-Section', 'logs')
        temp_dir = config.get('Directory-Section', 'temp')
        cls.credentials = config.get('Secrets-Section', 'confd-credentials').strip('"').split(' ')
        cls.nonietf_dir = config.get('Directory-Section', 'non-ietf-directory')
        yang_models = config.get('Directory-Section', 'yang-models-dir')
        _redis_host = config.get('DB-Section', 'redis-host')
        _redis_port = int(config.get('DB-Section', 'redis-port'))

        cls.redis_connection = RedisConnection(modules_db=6, vendors_db=9)
        cls.receiver = Receiver(os.environ['YANGCATALOG_CONFIG_PATH'])
        cls.receiver.redisConnection = cls.redis_connection
        cls.modulesDB = Redis(host=_redis_host, port=_redis_port, db=6)
        cls.vendorsDB = Redis(host=_redis_host, port=_redis_port, db=9)
        cls.huawei_dir = f'{yang_models}/vendor/huawei/network-router/8.20.0/ne5000e'
        cls.directory = f'{temp_dir}/receiver_test'
        resources_path = os.path.join(os.environ['BACKEND'], 'tests/resources')
        cls.private_dir = os.path.join(resources_path, 'html/private')

        with open(os.path.join(resources_path, 'receiver_tests_data.json'), 'r') as f:
            cls.test_data = json.load(f)

        redis_modules_patcher = mock.patch('redisConnections.redisConnection.RedisConnection')
        cls.mock_redis_modules = redis_modules_patcher.start()
        cls.addClassCleanup(redis_modules_patcher.stop)
        cls.mock_redis_modules.return_value = cls.redis_connection

        confd_patcher = mock.patch('utility.confdService.ConfdService')
        cls.mock_confd_service = confd_patcher.start()
        cls.addClassCleanup(confd_patcher.stop)
        cls.mock_confd_service.side_effect = MockConfdService

    def tearDown(self):
        self.modulesDB.flushdb()
        self.vendorsDB.flushdb()


class TestReceiverClass(TestReceiverBaseClass):
    def setUp(self):
        super().setUp()
        os.makedirs(self.directory, exist_ok=True)

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.directory)

    def test_run_ping_successful(self):
        status = self.receiver.run_ping('ping')

        self.assertEqual(status, StatusMessage.SUCCESS)

    def test_run_ping_failure(self):
        status = self.receiver.run_ping('pong')

        self.assertEqual(status, StatusMessage.FAIL)


@ddt
class TestReceiverVendorsDeletionClass(TestReceiverBaseClass):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendors_to_populate = cls.test_data.get('vendor-deletion-tests').get('vendors')
        cls.modules_to_populate = cls.test_data.get('vendor-deletion-tests').get('modules')

    def setUp(self):
        super().setUp()
        self.redis_connection.populate_implementation([self.vendors_to_populate])
        self.redis_connection.populate_modules(self.modules_to_populate)
        self.redis_connection.reload_vendors_cache()
        self.redis_connection.reload_modules_cache()

    @data(
        ('fujitsu', 'T100', '2.4', 'Linux'),
        ('fujitsu', 'T100', '2.4', 'None'),
        ('fujitsu', 'T100', 'None', 'None'),
        ('fujitsu', 'None', 'None', 'None'),
        ('huawei', 'ne5000e', 'None', 'None'),
    )
    @mock.patch('api.receiver.prepare_for_es_removal')
    def test_process_vendor_deletion(self, params, indexing_mock: mock.MagicMock):
        indexing_mock.return_value = {}
        vendor, platform, software_version, software_flavor = params

        deleted_vendor_branch = ''
        if vendor != 'None':
            deleted_vendor_branch += f'{vendor}/'
        if platform != 'None':
            deleted_vendor_branch += f'{platform}/'
        if software_version != 'None':
            deleted_vendor_branch += f'{software_version}/'
        if software_flavor != 'None':
            deleted_vendor_branch += software_flavor

        arguments = ['DELETE-VENDORS', *self.credentials, vendor, platform, software_version, software_flavor]
        status = self.receiver.process_vendor_deletion(arguments)
        self.redis_connection.reload_vendors_cache()
        self.redis_connection.reload_modules_cache()

        created_vendors_dict = self.redis_connection.create_vendors_data_dict(deleted_vendor_branch)
        self.assertEqual(status, StatusMessage.SUCCESS)
        self.assertEqual(created_vendors_dict, [])
        for key in self.vendorsDB.scan_iter():
            redis_key = key.decode('utf-8')
            self.assertNotIn(deleted_vendor_branch, redis_key)

        raw_all_modules = self.redis_connection.get_all_modules()
        all_modules = json.loads(raw_all_modules)
        for module in all_modules.values():
            implementations = module.get('implementations', {}).get('implementation', [])
            for implementation in implementations:
                implementation_key = self.redis_connection.create_implementation_key(implementation)
                self.assertNotIn(deleted_vendor_branch, implementation_key)


if __name__ == '__main__':
    unittest.main()

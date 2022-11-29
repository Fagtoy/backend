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
import unittest

from redis import RedisError

import api.views.admin.admin as admin
from api.yangCatalogApi import app
from redisConnections.redis_users_connection import RedisUsersConnection

ac = app.config


class TestApiAdminClass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources_path = os.path.join(os.environ['BACKEND'], 'tests/resources')
        cls.client = app.test_client()
        cls.users = RedisUsersConnection()
        with open(os.path.join(resources_path, 'payloads.json'), 'r') as f:
            content = json.load(f)
        fields = content['user']['input']
        cls.user_info_fields = {key.replace('-', '_'): value for key, value in fields.items()}
        with open(os.path.join(resources_path, 'testlog.log'), 'r') as f:
            cls.test_log_text = f.read()
        with open(os.path.join(resources_path, 'payloads.json'), 'r') as f:
            cls.payloads_content = json.load(f)

    def setUp(self):
        self.uid = self.users.create(temp=True, **self.user_info_fields)

    def tearDown(self):
        self.users.delete(self.uid, temp=True)

    def test_catch_db_error(self):
        with app.app_context():

            def error():
                raise RedisError

            result = admin.catch_db_error(error)()

        self.assertEqual(result, ({'error': 'Server problem connecting to database'}, 500))


if __name__ == '__main__':
    unittest.main()

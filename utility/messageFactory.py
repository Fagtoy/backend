"""
MessageFactory class that send a automated messages to
specified rooms or people.
"""
# Copyright 2018 Cisco and its affiliates
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

__author__ = "Miroslav Kovac"
__copyright__ = "Copyright 2018 Cisco and its affiliates"
__license__ = "Apache License, Version 2.0"
__email__ = "miroslav.kovac@pantheon.tech"

import os
import smtplib
import sys
from email.mime.text import MIMEText

from ciscosparkapi import CiscoSparkAPI

import utility.log as lo

if sys.version_info >= (3, 4):
    import configparser as ConfigParser
else:
    import ConfigParser

LOGGER = lo.get_logger('Messaging', '/home/miroslav/log/messaging/yang.log')
GREETINGS = 'Hello from yang-catalog'


class MessageFactory:
    """This class serves to automatically send a message to
       Webex Teams cisco admins private room and/or to send
       a message to a group of admin e-mails
    """

    def __init__(self, config_path='/etc/yangcatalog/yangcatalog.conf'):
        """Setup Webex teams rooms and smtp

            Arguments:
                :param config_path: (str) path to a yangcatalog.conf file
        """
        def list_matching_rooms(a, title_match):
            return [r for r in a.rooms.list() if title_match in r.title]

        LOGGER.info('Initialising Message')
        config_path = os.getcwd() + '/' + config_path
        config = ConfigParser.ConfigParser()
        config.read(config_path)
        token = config.get('Message-Section', 'access-token')
        self.__api = CiscoSparkAPI(access_token=token)
        rooms = list_matching_rooms(self.__api, 'YANG Catalog admin')

        if len(rooms) == 0:
            LOGGER.error('Need at least one room')
            sys.exit(1)
        if len(rooms) != 1:
            print('Too many rooms! Refine the name:')
            for r in rooms:
                LOGGER.info('{}'.format(r.title))
            sys.exit(1)

        # Ok, we should have just one room if we get here
        self.__room = rooms[0]
        self.__smtp = smtplib.SMTP('localhost')

    def __post_to_spark(self, msg, markdown=False, files=None):
        """Send message to a spark room

            Arguments:
                :param msg: (str) message to send
                :param markdown: (boolean) whether to use markdown.
                    Default False
                :param files: (list) list of paths to files that
                    need to be attache with a message. Default None
        """
        if markdown:
            self.__api.messages.create(self.__room.id, markdown=msg
                                       , files=files)
        else:
            self.__api.messages.create(self.__room.id, text=msg, files=files)

        if files:
            for f in files:
                os.remove(f)

    def __post_to_email(self, message, to):
        """Send message to a e-mail

            Arguments:
                :param message: (str) message to send
                :param to: (str/list) list of people to whom we
                    need to send a message.
        """
        if not isinstance(to, list):
            to = [to]
        msg = MIMEText(message)
        msg['Subject'] = 'Automatic generated message - RFC ietf'
        msg['From'] = 'no-reply@yangcatalog.org'
        msg['To'] = ', '.join(to)

        self.__smtp.sendmail('no-reply@yangcatalog.org', to, msg.as_string())
        self.__smtp.quit()

    def send_new_rfc_message(self, new_files, diff_files):
        LOGGER.info('Sending notification about new IETF RFC modules')
        new_files = '\n'.join(new_files)
        diff_files = '\n'.join(diff_files)
        message = ('{}\n\nSome of the files are different'
                   ' in http://www.claise.be/IETFYANGRFC.json against'
                   ' yangModels/yang repository\n\n'
                   'Files that are missing in yangModles repo: \n{} \n\n '
                   'Files that are different then in yangModels repo: \n{}'
                   .format(GREETINGS, new_files, diff_files))
        to = ['bclaise@cisco.com', 'einarnn@cisco.com', 'jclarke@cisco.com',
              'mirolsav.kovac@pantheon.tech', 'evyncke@cisco.com']

        self.__post_to_spark(message)
        self.__post_to_email(message, to)

    def send_travis_auth_failed(self):
        LOGGER.info('Sending notification about travis authorization failed')
        message = ('Travis pull job not sent because patch was not sent from'
                   ' travis. Key verification failed')
        self.__post_to_spark(message)

    def send_automated_procedure_failed(self, procedure, error_message):
        LOGGER.info('Sending notification about any automated procedure failure'
                    )
        message = ('Automated procedure - {} - failed with error - {}'
                   .format(procedure, error_message))
        self.__post_to_spark(message)

    def send_removed_temp_diff_files(self):
        # TODO send spark message about removed searched diff files
        pass

    def send_removed_yang_files(self, removed_yang_files):
        LOGGER.info('Sending notification about removed yang modules')
        message = ("Files have been removed from yangcatalog. See attached"
                   " document")
        text = ("The following files has been removed from yangcatalog.org"
                " using api: \n{}\n".format(removed_yang_files))
        with open('./log.txt', 'w') as f:
            f.write(text)
        self.__post_to_spark(message, True, files=['./log.txt'])

    def send_added_new_yang_files(self, added_yang_files):
        LOGGER.info('Sending notification about added yang modules')
        message = ("Files have been added to yangcatalog. See attached"
                   " document")
        text = ("The following files has been added to yangcatalog.org"
                " using api as a new modules or old modules with new "
                "revision: \n{}\n".format(added_yang_files))
        with open('./log.txt', 'w') as f:
            f.write(text)
        self.__post_to_spark(message, True, files=['./log.txt'])

    def send_new_modified_platform_metadata(self, new_files, modified_files):
        LOGGER.info(
            'Sending notification about new or modified platform metadata')
        new_files = '\n'.join(new_files)
        modified_files = '\n'.join(modified_files)
        message = ("Files have been modified in yangcatalog. See attached"
                   " document")
        text = ("There were new or modified platform metadata json files "
                "added to yangModels-yang repository, that are currently"
                "being processed in following paths:\n\n"
                "\n New json files: \n {} \n\n Modified json files:\n{}\n"
                .format(new_files, modified_files))
        with open('./log.txt', 'w') as f:
            f.write(text)
        self.__post_to_spark(message, True, files=['./log.txt'])

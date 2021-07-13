# Copyright The IETF Trust 2020, All Rights Reserved
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
__copyright__ = "Copyright The IETF Trust 2020, All Rights Reserved"
__license__ = "Apache License, Version 2.0"
__email__ = "miroslav.kovac@pantheon.tech"

import json
import os

import requests
from api.authentication.auth import auth, check_authorized
from api.globalConfig import yc_gc
from flask import Blueprint, abort, jsonify, make_response, request, current_app
from utility import messageFactory, repoutil


class YcJobs(Blueprint):

    def __init__(self, name, import_name, static_folder=None, static_url_path=None, template_folder=None,
                 url_prefix=None, subdomain=None, url_defaults=None, root_path=None):
        super().__init__(name, import_name, static_folder, static_url_path, template_folder, url_prefix, subdomain,
                         url_defaults, root_path)


app = YcJobs('ycJobs', __name__)


### ROUTE ENDPOINT DEFINITIONS ###
@auth.login_required
@app.route('/ietf', methods=['GET'])
def trigger_ietf_pull():
    username = request.authorization['username']
    if username != 'admin':
        return abort(401, description="User must be admin")
    job_id = yc_gc.sender.send('run_ietf')
    current_app.logger.info('job_id {}'.format(job_id))
    return make_response(jsonify({'job-id': job_id}), 202)


@app.route('/checkComplete', methods=['POST'])
def check_local():
    """Authorize sender if it is Travis, if travis job was sent from yang-catalog
    repository and job passed fine and Travis run a job on pushed patch, create
    a pull request to YangModules repository. If the job passed on this pull request,
    merge the pull request and remove the repository at yang-catalog repository
            :return response to the request
    """
    current_app.logger.info('Starting pull request job')
    body = json.loads(request.form['payload'])
    current_app.logger.info('Body of travis {}'.format(json.dumps(body)))
    current_app.logger.info('type of job {}'.format(body['type']))
    try:
        check_authorized(request.headers.environ['HTTP_SIGNATURE'], request.form['payload'])
        current_app.logger.info('Authorization successful')
    except:
        current_app.logger.exception('Authorization failed. Request did not come from Travis')
        mf = messageFactory.MessageFactory()
        mf.send_travis_auth_failed()
        return abort(401)

    github_api_url = 'https://api.github.com'
    github_repos_url = '{}/repos'.format(github_api_url)
    yang_models_url = '{}/YangModels/yang'.format(github_repos_url)

    verify_commit = False
    current_app.logger.info('Checking commit SHA if it is the commit sent by yang-catalog user.')
    if body['repository']['owner_name'] == 'yang-catalog':
        commit_sha = body['commit']
    else:
        commit_sha = body['head_commit']
    try:
        with open(yc_gc.commit_msg_file, 'r') as commit_file:
            for line in commit_file:
                if commit_sha in line:
                    verify_commit = True
                    break
    except:
        return abort(404)

    token_header_value = 'token {}'.format(yc_gc.token)
    if verify_commit:
        current_app.logger.info('commit verified')
        if body['repository']['owner_name'] == 'yang-catalog':
            if body['result_message'] == 'Passed':
                if body['type'] in ['push', 'api']:
                    # After build was successful only locally
                    json_body = json.loads(json.dumps({
                        "title": "Cronjob - every day pull and update of ietf draft yang files.",
                        "body": "ietf extracted yang modules",
                        "head": "yang-catalog:master",
                        "base": "master"
                    }))

                    url = '{}/pulls'.format(yang_models_url)
                    r = requests.post(url,
                                      json=json_body, headers={'Authorization': token_header_value})
                    if r.status_code == requests.codes.created:
                        current_app.logger.info('Pull request created successfully')
                        return make_response(jsonify({'info': 'Success'}), 201)
                    else:
                        current_app.logger.error('Could not create a pull request {}'.format(r.status_code))
                        return abort(400)
            else:
                current_app.logger.warning('Travis job did not pass. Removing forked repository.')
                requests.delete('https://api.github.com/repos/yang-catalog/yang',
                                headers={'Authorization': token_header_value})
                return make_response(jsonify({'info': 'Failed'}), 406)
        elif body['repository']['owner_name'] == 'YangModels':
            if body['result_message'] == 'Passed':
                if body['type'] == 'pull_request':
                    # If build was successful on pull request
                    admin_token_header_value = 'token {}'.format(yc_gc.admin_token)
                    pull_number = body['pull_request_number']
                    current_app.logger.info('Pull request was successful {}. sending review.'.format(repr(pull_number)))
                    url = 'https://api.github.com/repos/YangModels/yang/pulls/{}/reviews'.format(repr(pull_number))
                    data = json.dumps({
                        'body': 'AUTOMATED YANG CATALOG APPROVAL',
                        'event': 'APPROVE'
                    })
                    response = requests.post(url, data, headers={'Authorization': admin_token_header_value})
                    current_app.logger.info('review response code {}. Merge response {}.'.format(
                        response.status_code, response.text))
                    data = json.dumps({'commit-title': 'Travis job passed',
                                       'sha': body['head_commit']})
                    response = requests.put('https://api.github.com/repos/YangModels/yang/pulls/{}/merge'.format(repr(pull_number)),
                                            data, headers={'Authorization': admin_token_header_value})
                    current_app.logger.info('Merge response code {}. Merge response {}.'.format(response.status_code, response.text))
                    return make_response(jsonify({'info': 'Success'}), 201)
            else:
                current_app.logger.warning('Travis job did not pass. Removing pull request')
                pull_number = body['pull_request_number']
                json_body = json.loads(json.dumps({
                    "title": "Cron job - every day pull and update of ietf draft yang files.",
                    "body": "ietf extracted yang modules",
                    "state": "closed",
                    "base": "master"
                }))
                requests.patch('https://api.github.com/repos/YangModels/yang/pulls/{}'.format(pull_number), json=json_body,
                               headers={'Authorization': token_header_value})
                current_app.logger.warning('Travis job did not pass. Removing forked repository.')
                requests.delete(
                    'https://api.github.com/repos/yang-catalog/yang',
                    headers={'Authorization': token_header_value})
                return make_response(jsonify({'info': 'Failed'}), 406)
        else:
            current_app.logger.warning('Owner name verification failed. Owner -> {}'.format(body['repository']['owner_name']))
            return make_response(jsonify({'Error': 'Owner verfication failed'}),
                                 401)
    else:
        current_app.logger.info('Commit verification failed. Commit sent by someone else.'
                          'Not doing anything.')
    return make_response(jsonify({'Error': 'Fails'}), 500)


@app.route('/check-platform-metadata', methods=['POST'])
def trigger_populate():
    current_app.logger.info('Trigger populate if necessary')
    repoutil.pull(yc_gc.yang_models)
    try:
        commits = request.json['commits']
        paths = set()
        new = []
        mod = []
        if commits:
            for commit in commits:
                added = commit.get('added')
                if added:
                    for add in added:
                        if 'platform-metadata.json' in add:
                            paths.add('/'.join(add.split('/')[:-1]))
                            new.append('/'.join(add.split('/')[:-1]))
                modified = commit.get('modified')
                if modified:
                    for m in modified:
                        if 'platform-metadata.json' in m:
                            paths.add('/'.join(m.split('/')[:-1]))
                            mod.append('/'.join(m.split('/')[:-1]))
        if len(paths) > 0:
            mf = messageFactory.MessageFactory()
            mf.send_new_modified_platform_metadata(new, mod)
            current_app.logger.info('Forking the repo')
            try:
                populate_path = os.path.abspath(
                    os.path.dirname(os.path.realpath(__file__)) + "/../../../parseAndPopulate/populate.py")
                arguments = ["python", populate_path, "--port", repr(yc_gc.confdPort), "--ip",
                             yc_gc.confd_ip, "--api-protocol", yc_gc.api_protocol, "--api-port",
                             repr(yc_gc.api_port), "--api-ip", yc_gc.ip,
                             "--result-html-dir", yc_gc.result_dir,
                             "--credentials", yc_gc.credentials[0], yc_gc.credentials[1],
                             "--save-file-dir", yc_gc.save_file_dir, "repoLocalDir"]
                arguments = arguments + list(paths) + [yc_gc.yang_models, "github"]
                yc_gc.sender.send("#".join(arguments))
            except:
                current_app.logger.exception('Could not populate after git push')
            return make_response(jsonify({'info': 'Success'}), 200)
        return make_response(jsonify({'info': 'Success'}), 200)
    except Exception as e:
        current_app.logger.error('Automated github webhook failure - {}'.format(e))
        return make_response(jsonify({'info': 'Success'}), 200)


@app.route('/get-statistics', methods=['GET'])
def get_statistics():
    stats_path = '{}/stats/stats.json'.format(yc_gc.private_dir)
    if os.path.exists(stats_path):
        with open(stats_path, 'r') as f:
            return make_response(jsonify(json.load(f)), 200)
    else:
        abort(404, description='Statistics file has not been generated yet')

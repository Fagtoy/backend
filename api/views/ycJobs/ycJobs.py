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

__author__ = 'Miroslav Kovac'
__copyright__ = 'Copyright The IETF Trust 2020, All Rights Reserved'
__license__ = 'Apache License, Version 2.0'
__email__ = 'miroslav.kovac@pantheon.tech'

import json
import os

import requests
from flask.blueprints import Blueprint
from flask.globals import request
from werkzeug.exceptions import abort

from api.authentication.auth import auth, check_authorized
from api.my_flask import app
from utility import message_factory, repoutil
from utility.staticVariables import github_api
from utility.util import create_signature


class YcJobs(Blueprint):
    def __init__(
        self,
        name,
        import_name,
        static_folder=None,
        static_url_path=None,
        template_folder=None,
        url_prefix=None,
        subdomain=None,
        url_defaults=None,
        root_path=None,
    ):
        super().__init__(
            name,
            import_name,
            static_folder,
            static_url_path,
            template_folder,
            url_prefix,
            subdomain,
            url_defaults,
            root_path,
        )


bp = YcJobs('ycJobs', __name__)


@bp.before_request
def set_config():
    global ac
    ac = app.config


@bp.route('/ietf', methods=['GET'])
@auth.login_required
def trigger_ietf_pull():
    assert request.authorization
    username = request.authorization['username']
    if username != 'admin':
        abort(401, description='User must be admin')
    job_id = ac.sender.send('run_ietf')
    app.logger.info(f'job_id {job_id}')
    return {'job-id': job_id}, 202


@bp.route('/checkCompleteGithub', methods=['POST'])
def check_github():
    app.logger.info('Starting Github Actions check')
    body = json.loads(request.data)
    app.logger.info(f'Body of Github Actions:\n{json.dumps(body)}')

    # Request Authorization
    request_signature = request.headers['X_HUB_SIGNATURE']
    computed_signature = create_signature(ac.s_yang_catalog_token, request.data.decode())

    if request_signature.split('sha1=')[-1] == computed_signature:
        app.logger.info('Authorization successful')
    else:
        app.logger.error('Authorization failed. Request did not come from Github')
        abort(401)

    # Check run result - if completed successfully
    if body.get('check_run', {}).get('status') != 'completed':
        app.logger.error('Github Actions run not completed yet')
        return {'info': 'Run not completed yet - no action was taken'}, 200
    if (conclusion := body.get('check_run', {}).get('conclusion')) != 'success':
        html_url = body.get('check_run', {}).get('html_url')
        app.logger.error(f'Github Actions run finished with conclusion {conclusion}\nMore info: {html_url}')

        # Sending email notification to developers team
        mf = message_factory.MessageFactory()
        mf.send_github_action_email(conclusion, html_url)

        return {'info': f'Run finished with conclusion {conclusion}'}, 200

    # Commit verification
    verify_commit = False
    app.logger.info('Checking commit SHA if it is the commit sent by yang-catalog user.')

    commit_sha = body['check_run']['head_sha']
    if body['repository']['full_name'] == 'yang-catalog/yang' or body['repository']['full_name'] == 'YangModels/yang':
        try:
            with open(ac.d_commit_dir, 'r') as commit_file:
                for line in commit_file:
                    if commit_sha in line:
                        verify_commit = True
                        break
        except FileNotFoundError:
            abort(404)

    github_repos_url = f'{github_api}/repos'
    yang_models_url = f'{github_repos_url}/YangModels/yang'
    pull_requests_url = f'{yang_models_url}/pulls'

    if verify_commit:
        token_header_value = f'token {ac.s_yang_catalog_token}'
        app.logger.info(f'Commit {body["check_run"]["head_sha"]} verified')
        # Create PR to YangModels/yang if sent from yang-catalog/yang
        if body['repository']['full_name'] == 'yang-catalog/yang':
            json_body = {
                'title': 'Cronjob - every day pull and update of ietf draft yang files.',
                'body': 'ietf extracted yang modules',
                'head': 'yang-catalog:main',
                'base': 'main',
            }
            url = f'{yang_models_url}/pulls'
            r = requests.post(url, json=json_body, headers={'Authorization': token_header_value})
            if r.status_code == 201:
                app.logger.info('Pull request created successfully')
                return {'info': 'Success'}, 201
            else:
                message = f'Could not create a pull request.\nGithub responed with status code {r.status_code}'
                app.logger.error(message)
                return {'info': message}, 200
        # Automatically merge PR if sent from YangModels/yang
        elif body['repository']['full_name'] == 'YangModels/yang':
            admin_token_header_value = f'token {ac.s_admin_token}'
            pull_requests = requests.get(pull_requests_url).json()
            for pull_request in pull_requests:
                head_sha = pull_request['head']['sha']
                if head_sha == commit_sha:
                    pull_number = pull_request['number']
                    app.logger.info(f'Pull request {pull_number} was successful - sending review.')
                    url = f'{github_api}/repos/YangModels/yang/pulls/{pull_number}/reviews'
                    data = json.dumps({'body': 'AUTOMATED YANG CATALOG APPROVAL', 'event': 'APPROVE'})
                    response = requests.post(url, data, headers={'Authorization': admin_token_header_value})
                    app.logger.info(f'Review response code {response.status_code}')
                    data = json.dumps(
                        {'commit-title': 'Github Actions job passed', 'sha': body['check_run']['head_sha']},
                    )
                    response = requests.put(
                        f'https://api.github.com/repos/YangModels/yang/pulls/{pull_number}/merge',
                        data,
                        headers={'Authorization': admin_token_header_value},
                    )
                    app.logger.info(
                        f'Merge response code {response.status_code}\nMerge response {response.text}',
                    )
                    return {'info': 'Success'}, 201
            else:
                message = f'No opened pull request found with head sha: {commit_sha}'
                return {'info': message}, 200
        else:
            message = f'Owner name verification failed. Owner -> {body["sender"]["login"]}'
            app.logger.warning(message)
            return {'Error': message}, 401
    else:
        app.logger.info('Commit verification failed.' ' Commit sent by someone else - not doing anything.')
        return {'info': 'Commit verification failed - sent by someone else'}, 200


@bp.route('/checkComplete', methods=['POST'])
def check_local():
    """
    Authorize sender if it is Travis, if travis job was sent from yang-catalog
    repository and job passed fine and Travis run a job on pushed patch, create
    a pull request to YangModules repository. If the job passed on this pull request,
    merge the pull request and remove the repository at yang-catalog repository
    :return response to the request
    """
    app.logger.info('Starting pull request job')
    body = json.loads(request.form['payload'])
    app.logger.info(f'Body of travis {json.dumps(body)}')
    app.logger.info(f'type of job {body["type"]}')
    try:
        check_authorized(request.headers['SIGNATURE'], request.form['payload'])
        app.logger.info('Authorization successful')
    except Exception:
        app.logger.exception('Authorization failed. Request did not come from Travis')
        mf = message_factory.MessageFactory()
        mf.send_travis_auth_failed()
        abort(401)

    github_repos_url = f'{github_api}/repos'
    yang_models_url = f'{github_repos_url}/YangModels/yang'

    verify_commit = False
    app.logger.info('Checking commit SHA if it is the commit sent by yang-catalog user.')
    if body['repository']['owner_name'] == 'yang-catalog':
        commit_sha = body['commit']
    else:
        commit_sha = body['head_commit']
    try:
        with open(ac.d_commit_dir, 'r') as commit_file:
            for line in commit_file:
                if commit_sha in line:
                    verify_commit = True
                    break
    except FileNotFoundError:
        abort(404)

    token_header_value = f'token {ac.s_yang_catalog_token}'
    if verify_commit:
        app.logger.info('commit verified')
        if body['repository']['owner_name'] == 'yang-catalog':
            if body['result_message'] == 'Passed':
                if body['type'] in ['push', 'api']:
                    # After build was successful only locally
                    json_body = {
                        'title': 'Cronjob - every day pull and update of ietf draft yang files.',
                        'body': 'ietf extracted yang modules',
                        'head': 'yang-catalog:main',
                        'base': 'main',
                    }
                    url = f'{yang_models_url}/pulls'
                    r = requests.post(url, json=json_body, headers={'Authorization': token_header_value})
                    if r.status_code == 201:
                        app.logger.info('Pull request created successfully')
                        return {'info': 'Success'}, 201
                    else:
                        app.logger.error(f'Could not create a pull request {r.status_code}')
                        abort(400)
            else:
                app.logger.warning('Travis job did not pass.')
                return {'info': 'Failed'}, 406
        elif body['repository']['owner_name'] == 'YangModels':
            if body['result_message'] == 'Passed':
                if body['type'] == 'pull_request':
                    # If build was successful on pull request
                    admin_token_header_value = f'token {ac.s_admin_token}'
                    pull_number = body['pull_request_number']
                    app.logger.info(f'Pull request was successful {repr(pull_number)}. sending review.')
                    url = f'{github_api}/repos/YangModels/yang/pulls/{repr(pull_number)}/reviews'
                    data = json.dumps({'body': 'AUTOMATED YANG CATALOG APPROVAL', 'event': 'APPROVE'})
                    response = requests.post(url, data, headers={'Authorization': admin_token_header_value})
                    app.logger.info(f'review response code {response.status_code}. Merge response {response.text}.')
                    data = json.dumps({'commit-title': 'Travis job passed', 'sha': body['head_commit']})
                    response = requests.put(
                        f'{github_api}/repos/YangModels/yang/pulls/{repr(pull_number)}/merge',
                        data,
                        headers={'Authorization': admin_token_header_value},
                    )
                    app.logger.info(f'Merge response code {response.status_code}. Merge response {response.text}.')
                    return {'info': 'Success'}, 201
            else:
                app.logger.warning('Travis job did not pass. Removing pull request')
                pull_number = body['pull_request_number']
                json_body = json.loads(
                    json.dumps(
                        {
                            'title': 'Cron job - every day pull and update of ietf draft yang files.',
                            'body': 'ietf extracted yang modules',
                            'state': 'closed',
                            'base': 'main',
                        },
                    ),
                )
                requests.patch(
                    f'{github_api}/repos/YangModels/yang/pulls/{pull_number}',
                    json=json_body,
                    headers={'Authorization': token_header_value},
                )
                app.logger.warning('Travis job did not pass.')
                return {'info': 'Failed'}, 406
        else:
            app.logger.warning(f'Owner name verification failed. Owner -> {body["repository"]["owner_name"]}')
            return {'Error': 'Owner verfication failed'}, 401
    else:
        app.logger.info('Commit verification failed. Commit sent by someone else.' 'Not doing anything.')
    return {'Error': 'Fails'}, 500


@bp.route('/check-platform-metadata', methods=['POST'])
def trigger_populate():
    app.logger.info('Trigger populate if necessary')
    repoutil.pull(ac.d_yang_models_dir)
    try:
        assert request.json
        body = json.loads(request.data)
        app.logger.info(f'Body of request:\n{json.dumps(body)}')
        commits = request.json.get('commits') if request.is_json else None
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
            mf = message_factory.MessageFactory()
            mf.send_new_modified_platform_metadata(new, mod)
            app.logger.info('Forking the repo')
            try:
                populate_path = os.path.join(os.environ['BACKEND'], 'parseAndPopulate/populate.py')
                arguments = [
                    'python',
                    populate_path,
                    '--result-html-dir',
                    ac.w_result_html_dir,
                    '--credentials',
                    ac.s_confd_credentials[0],
                    ac.s_confd_credentials[1],
                    '--save-file-dir',
                    ac.d_save_file_dir,
                    'repoLocalDir',
                ]
                arguments = arguments + list(paths) + [ac.d_yang_models_dir, 'github']
                ac.sender.send('#'.join(arguments))
            except Exception:
                app.logger.exception('Could not populate after git push')
    except Exception as e:
        app.logger.error(f'Automated github webhook failure - {e}')

    return {'info': 'Success'}


@bp.route('/get-statistics', methods=['GET'])
def get_statistics():
    stats_path = f'{ac.w_private_directory}/stats/stats.json'
    if os.path.exists(stats_path):
        with open(stats_path, 'r') as reader:
            return reader.read()
    abort(404, description='Statistics file has not been generated yet')


@bp.route('/problematic-drafts', methods=['GET'])
def get_problematic_drafts():
    problematic_drafts_path = f'{ac.w_public_directory}/drafts/problematic_drafts.json'
    if os.path.exists(problematic_drafts_path):
        with open(problematic_drafts_path, 'r') as reader:
            return reader.read()
    abort(404, description='Problematic drafts file has not been generated yet')

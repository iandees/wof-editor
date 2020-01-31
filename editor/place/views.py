import base64
import random
import requests
import string
import time
from . import place_bp
from flask_login import current_user
from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
)


@place_bp.route('/')
def root_page():
    return render_template('place/index.html')


@place_bp.route('/place/<int:id>/edit', methods=["GET", "POST"])
def edit_place(id):
    if request.method == 'POST':
        branch_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        branch_name = "foobar-" + branch_suffix
        file_path = "testing/abc123.json"
        file_content = request.form.get('name')

        base_repo = 'zpqrtbnk/test-repo'
        base_ref = 'heads/master'

        if current_user.is_anonymous:
            flash("Need to login first")
            return redirect(request.url)

        sess = requests.Session()
        sess.headers['Authorization'] = ('token ' + session.get('access_token'))

        # Get the sha1 of `master` branch
        resp = sess.get('https://api.github.com/repos/%s/git/ref/%s' % (base_repo, base_ref))
        current_app.logger.warn(
            "%s %s results in HTTP %d %s",
            resp.request.method,
            resp.request.url,
            resp.status_code,
            resp.content
        )
        data = resp.json()
        base_ref_sha = data['object']['sha']

        # Create a branch from that sha1
        resp = sess.post(
            'https://api.github.com/repos/%s/git/refs' % (base_repo,),
            json={
                'ref': 'refs/heads/%s' % branch_name,
                'sha': base_ref_sha,
            }
        )
        current_app.logger.warn(
            "%s %s (data %s) results in HTTP %d %s",
            resp.request.method,
            resp.request.url,
            resp.request.body,
            resp.status_code,
            resp.content,
        )

        if resp.status_code == 404:
            current_app.logger.warn(
                "Doesn't look like we have access to create a branch in repo, so creating a fork"
            )

            # Kick off a fork and wait for it to be created
            resp = sess.post(
                'https://api.github.com/repos/%s/forks' % (base_repo,),
                json={},
            )
            current_app.logger.warn(
                "%s %s results in HTTP %d %s",
                resp.request.method,
                resp.request.url,
                resp.status_code,
                resp.content,
            )

            if resp.status_code == 202:
                fork_repo = resp.json()['full_name']
                fork_owner = resp.json()['owner']['login'] + ":"
                current_app.logger.warn(
                    "Fork creation of %s started",
                    fork_repo,
                )

                # Wait for the fork to be created
                for t in range(3):
                    resp = sess.get(
                        'https://api.github.com/repos/%s' % (fork_repo,),
                    )

                    if resp.status_code == 200:
                        current_app.logger.warn(
                            "Fork finished after %s checks",
                            t,
                        )
                        break
                    else:
                        current_app.logger.warn(
                            "Fork isn't there yet at try %s, waiting 500ms and trying again",
                            t,
                        )
                        time.sleep(0.5)

            else:
                current_app.logger.warn("Couldn't start fork creation.")
                return "can't create fork", 500

            # Try creating the branch in the fork
            resp = sess.post(
                'https://api.github.com/repos/%s/git/refs' % (fork_repo,),
                json={
                    'ref': 'refs/heads/%s' % branch_name,
                    'sha': base_ref_sha,
                }
            )
            current_app.logger.warn(
                "%s %s (data %s) results in HTTP %d %s",
                resp.request.method,
                resp.request.url,
                resp.request.body,
                resp.status_code,
                resp.content,
            )

            if resp.status_code == 201:
                write_repo = fork_repo
                current_app.logger.warn(
                    "Branch %s created on forked repo %s",
                    branch_name,
                    fork_repo,
                )

        elif resp.status_code == 201:
            write_repo = base_repo
            fork_owner = ""
            current_app.logger.warn(
                "Branch %s created on repo %s",
                branch_name,
                base_repo,
            )

        # Now that we have a branch that we can write to, create a file on it
        file_content_b64 = base64.standard_b64encode(file_content.encode('utf8')).decode('utf8')

        resp = sess.put(
            'https://api.github.com/repos/%s/contents/%s' % (write_repo, file_path),
            json={
                "message": "Adding file.",
                "content": file_content_b64,
                "branch": branch_name,
                # "sha": "",  # TODO If updating an existing file, need to get the sha of the blob in the repo to update
            }
        )

        current_app.logger.warn(
            "%s %s (data %s) results in HTTP %d %s",
            resp.request.method,
            resp.request.url,
            resp.request.body,
            resp.status_code,
            resp.content,
        )
        if resp.status_code == 201:
            current_app.logger.warn(
                "File %s was created in repo %s on branch %s, commit %s",
                file_path,
                write_repo,
                branch_name,
                resp.json()['commit']['sha'],
            )

        else:
            return "couldn't create file on branch", 500

        # We've created a file, now let's create the pull request
        resp = sess.post(
            'https://api.github.com/repos/%s/pulls' % (base_repo,),
            json={
                "title": "Test Updating A File With API",
                "head": (fork_owner + branch_name),
                "base": "master",
                "body": "This is a test of updating a file with a pull request on a forked repo using the GitHub API. Please pardon the noise.",
                "maintainer_can_modify": True,
                "draft": False,
            }
        )

        current_app.logger.warn(
            "%s %s (data %s) results in HTTP %d %s",
            resp.request.method,
            resp.request.url,
            resp.request.body,
            resp.status_code,
            resp.content,
        )
        if resp.status_code == 201:
            pr_url = resp.json()['html_url']

            current_app.logger.warn(
                "Created pull request %s",
                pr_url,
            )

            flash("Created pull request %s" % pr_url)
            return redirect(request.url)
        else:
            return "couldn't create pull request", 500

    return render_template('place/edit.html')

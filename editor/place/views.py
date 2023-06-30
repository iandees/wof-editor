import base64
import collections
import io
import json
import mapzen.whosonfirst.validator
import os
import random
import re
import requests
import string
import time
from . import place_bp
from flask_login import current_user
from flask import (
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)


name_specs = {
    "colloquial": "Colloquial",
    "historical": "Historical",
    "preferred": "Preferred",
    "unknown": "Unknown",
    "variant": "Variant",
}
label_specs = {
    "colloquial_abbreviation": "Colloquial Abbrev.",
    "preferred_abbreviation": "Preferred Abbrev.",
    "preferred_disambiguation": "Preferred Disambiguation",
    "preferred_longname": "Preferred Longname",
    "preferred_placetype": "Preferred Placetype",
    "preferred_shortcode": "Preferred Shortcode",
    "variant_abbreviation": "Variant Abbrev.",
    "variant_disambiguation": "Variant Disambiguation",
    "variant_longname": "Variant Longname",
    "variant_shortcode": "Variant Shortcode",
}
spec_expansion = dict(**name_specs, **label_specs)
lang_expansion = {
    'ara': 'Arabic',
    'ara_AE': 'Arabic (UAE)',
    'ben': 'Bengali',
    'ben_IN': 'Bengali (India)',
    'ben_BD': 'Bengali (Bangladesh)',
    'dan': 'Danish',
    'ell': 'Greek',
    'eng': 'English',
    'eng_GB': 'English (UK)',
    'eng_US': 'English (US)',
    'fin': 'Finnish',
    'fra': 'French',
    'ger': 'German',
    'ind': 'Indonesian',
    'ita': 'Italian',
    'jpn': 'Japanese',
    'kan': 'Kannada',
    'kor': 'Korean',
    'mal': 'Malayalam (India)',
    'nld': 'Dutch',
    'nor': 'Norwegian',
    'pol': 'Polish',
    'por': 'Portuguese',
    'por_BR': 'Portuguese (Brazil)',
    'por_PT': 'Portuguese (Portugal)',
    'ron': 'Romanian',
    'rus': 'Russian',
    'spa': 'Spanish',
    'spa_AR': 'Spanish (Argentina)',
    'spa_MX': 'Spanish (Mexico)',
    'spa_ES': 'Spanish (Spain)',
    'swe': 'Swedish',
    'tam': 'Tamil',
    'tel': 'Telugu',
    'tha': 'Thai',
    'tur': 'Turkish',
    'zho': 'Chinese',
    'zho_CN': 'Chinese (China)',
    'zho_TW': 'Chinese (Taiwan)',
}
provider_expansion = {
    "gn:id": "GeoNames",
    "wk:page": "Wikipedia",
    "wd:id": "Wikidata",
    "gp:id": "GeoPlanet",
    "qs_pg:id": "Quattroshapes Point Gazetteer",
    "loc:id": "Library of Congress",
    "fips:code": "Federal Information Processing Standards (FIPS)",
    "hasc:id": "Statoids HASC",
    "qs:id": "Quattroshapes",
    "woe:id": "Where On Earth",
    "iso:id": "International Organization for Standardization"
}
# Concordance fields that should be ints. See https://github.com/iandees/wof-editor/issues/13#issuecomment-583667919
concordance_ints = set(["gn:id", "gp:id", "qs:id", "qs_pg:id"])


@place_bp.route('/', methods=["GET", "POST"])
def root_page():
    wof_url = None
    if request.method == 'POST':
        wof_id = request.form.get('wof_id', type=int)
        wof_url = request.form.get('wof_url')
    elif request.method == 'GET':
        wof_id = request.args.get('wof_id', type=int)

    if wof_id is not None:
        # Find the WOF repo for the WOF ID
        try:
            wof_repo, place_path = find_wof_doc(wof_id)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                flash("Couldn't find that WOF ID")
            else:
                flash("Something went wrong while finding that WOF ID")
            return redirect(request.url)

        wof_url = "https://raw.githubusercontent.com/whosonfirst-data/%s/master/%s" % (wof_repo, place_path)

    if wof_url is not None:
        return redirect(url_for('place.edit_place', url=wof_url))

    return render_template('place/index.html')


@place_bp.route('/favicon-32x32.png')
def favicon():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static', 'favicon'),
        'favicon-32x32.png',
        mimetype='image/png',
    )


def log_response(resp):
    return json.dumps({
        "request": {
            "method": resp.request.method,
            "url": resp.request.url,
            "body": str(resp.request.body)[:500] if resp.request.body else None,
        },
        "response": {
            "status": resp.status_code,
            "body": str(resp.content)[:500] if resp.content else None,
        }
    })


def build_wof_doc_url_suffix(wof_id):
    id_url_str = str(wof_id)
    id_url_prefix = '/'.join(id_url_str[x:x + 3] for x in range(0, len(id_url_str), 3))

    return id_url_prefix + "/" + id_url_str + ".geojson"


def parse_prefix_map(properties, prefix):
    output = collections.defaultdict(dict)

    for k, v in properties.items():
        if not k.startswith(prefix):
            continue

        without_prefix = k[len(prefix):]
        key_split = without_prefix.split("_x_")
        lang = key_split[0]
        specifier = key_split[1]

        output[lang][specifier] = v

    return output


class ValidationException(Exception):
    pass


def maybe_float(i):
    try:
        return float(i) if i else None
    except ValueError:
        raise ValidationException("field must be a floating point number")


def maybe_int(i):
    try:
        return int(i) if i else None
    except ValueError:
        raise ValidationException("field must be an integer")


def list_of_str(i):
    try:
        return [v['value'] for v in json.loads(i)] if i else None
    except json.decoder.JSONDecodeError:
        raise ValidationException("field must be a JSON-formatted array")


def mz_bool(i):
    v = maybe_int(i)

    if v in (-1, 0, 1):
        return v

    raise ValidationException("field must be one of -1, 0, 1")


def apply_change(wof, form, attr_name, formatter=None):
    new_value = form[attr_name]
    old_value = wof['properties'].get(attr_name)

    formatter = formatter or str

    if old_value != new_value:
        if new_value not in ([], ""):
            try:
                new_value = formatter(new_value)
            except ValidationException as e:
                raise ValidationException("Error in field %s (%s)" % (attr_name, e))

            wof['properties'][attr_name] = new_value
        elif old_value is not None:
            del wof['properties'][attr_name]


def build_wof_repo_name(wof):
    props = wof['properties']
    wof_repo = props.get('wof:repo')
    if wof_repo:
        return "whosonfirst-data/" + wof_repo

    wof_country = props['wof:country']
    wof_placetype = props['wof:placetype']

    if wof_placetype in ('country', 'county', 'locality'):
        return "whosonfirst-data/whosonfirst-data-admin-" + wof_country.lower()
    elif wof_placetype in ('venue',):
        return "whosonfirst-data/whosonfirst-data-venue-" + wof_country.lower()


def build_wof_branchname(wof):
    props = wof['properties']
    branch_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=3))

    return "wofedit-%s-%s" % (props['wof:id'], branch_suffix)


def find_wof_doc(wof_id):
    wof_doc_url_suffix = build_wof_doc_url_suffix(wof_id)

    # Only request the first 10K of the doc to avoid the geometry if it's really big
    resp = requests.get(
        "https://data.whosonfirst.org/" + wof_doc_url_suffix,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Range": "0-10000",
        },
    )

    resp.raise_for_status()

    # Use regex to find the wof repo key in the doc
    match = re.findall(r'\"wof:repo\"\s*:\s*\"([^\"]*)\",', resp.text)
    if match:
        wof_repo = match[0]

    return (wof_repo, "data/" + wof_doc_url_suffix)

@place_bp.route('/place/<int:wof_id>/metadata')
def place_metadata(wof_id):
    try:
        wof_repo, place_path = find_wof_doc(wof_id)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return jsonify({
                "error": "That WOF ID was not found",
            }), 404
        else:
            return jsonify({
                "error": "Something went wrong finding that WOF ID",
                "message": str(e),
            }), 500

    return jsonify({
        "owner": "whosonfirst-data",
        "repo": wof_repo,
        "path": place_path,
        "github_web_url": "https://github.com/whosonfirst-data/%s/tree/master/%s" % (wof_repo, place_path),
    })


@place_bp.route('/place/<int:wof_id>/edit')
def edit_place_id(wof_id):
    return redirect(url_for('place.root_page', wof_id=wof_id))


@place_bp.route('/place/edit', methods=["GET", "POST"])
def edit_place():
    wof_url = request.args.get("url")
    if not wof_url:
        return redirect(url_for('place.root_page'))

    # Get the WOF doc by URL
    resp = requests.get(wof_url, timeout=0.7)
    current_app.logger.warn(log_response(resp))
    if resp.status_code == 200:
        wof_doc = resp.json()
    elif resp.status_code == 404:
        flash("Couldn't find that WOF ID")
        return redirect(url_for("place.root_page"))
    else:
        current_app.logger.warn(
            "Problem getting WOF doc: HTTP %s for %s",
            resp.status_code,
            resp.request.url,
        )
        flash("Couldn't get that WOF doc")
        return redirect(url_for("place.root_page"))

    if 'properties' not in wof_doc or \
            'id' not in wof_doc or \
            wof_doc.get('type') != 'Feature' or \
            'wof:repo' not in wof_doc['properties']:
        flash("That doesn't look like a valid WOF document")
        return redirect(url_for('place.root_page'))

    wof_id = wof_doc['id']
    file_path = 'data/' + build_wof_doc_url_suffix(wof_id)
    place_name = wof_doc['properties'].get('wof:name')

    # Put localized_names and labels information in a more convenient container
    localized_names = parse_prefix_map(wof_doc['properties'], 'name:')
    localized_labels = parse_prefix_map(wof_doc['properties'], 'label:')

    localized_names_tagify_whitelist = []
    for lang in localized_names.keys():
        lang_expanded = lang_expansion.get(lang)
        search_by = [lang, lang_expanded] if lang_expanded else [lang]

        localized_names_tagify_whitelist.append({
            "lang": lang,
            "value": "%s (%s)" % (lang_expanded, lang) if lang_expanded else lang,
            "searchBy": search_by,
        })

    localized_labels_tagify_whitelist = []
    for lang in localized_labels.keys():
        lang_expanded = lang_expansion.get(lang)
        search_by = [lang, lang_expanded] if lang_expanded else [lang]

        localized_labels_tagify_whitelist.append({
            "lang": lang,
            "value": "%s (%s)" % (lang_expanded, lang) if lang_expanded else lang,
            "searchBy": search_by,
        })

    if request.method == 'POST':

        # Consume the changes from the form
        try:
            apply_change(wof_doc, request.form, "wof:name")
            if not wof_doc.get('properties', {}).get("wof:name"):
                raise ValidationException("wof:name must be set")

            apply_change(wof_doc, request.form, "wof:placetype_alt", list_of_str)
            apply_change(wof_doc, request.form, "wof:shortcode")
            apply_change(wof_doc, request.form, "mz:is_current", mz_bool)
            apply_change(wof_doc, request.form, "mz:is_funky", mz_bool)
            apply_change(wof_doc, request.form, "mz:hierarchy_label", mz_bool)
            apply_change(wof_doc, request.form, "edtf:cessation")
            apply_change(wof_doc, request.form, "edtf:deprecated")
            apply_change(wof_doc, request.form, "edtf:inception")
            apply_change(wof_doc, request.form, "edtf:superseded")
            apply_change(wof_doc, request.form, "wof:population", maybe_int)
            apply_change(wof_doc, request.form, "mz:min_zoom", maybe_float)
            apply_change(wof_doc, request.form, "mz:max_zoom", maybe_float)
            apply_change(wof_doc, request.form, "lbl:min_zoom", maybe_float)
            apply_change(wof_doc, request.form, "lbl:max_zoom", maybe_float)
            apply_change(wof_doc, request.form, "wof:lang_x_spoken", list_of_str)
            apply_change(wof_doc, request.form, "wof:lang_x_official", list_of_str)

            for k in filter(lambda i: i.startswith('name:'), request.form.keys()):
                apply_change(wof_doc, request.form, k, list_of_str)
            for k in filter(lambda i: i.startswith('name:'), wof_doc['properties'].keys()):
                apply_change(wof_doc, request.form, k, list_of_str)

            for k in filter(lambda i: i.startswith('label:'), request.form.keys()):
                apply_change(wof_doc, request.form, k, list_of_str)
            for k in filter(lambda i: i.startswith('label:'), wof_doc['properties'].keys()):
                apply_change(wof_doc, request.form, k, list_of_str)

            # Make any changes to existing concordances
            for k, new_value in filter(lambda i: i[0].startswith('wof:concordances_x_'), request.form.items()):
                concordance_provider = k[19:]
                if concordance_provider in concordance_ints:
                    try:
                        new_value = int(new_value)
                    except ValueError:
                        raise ValidationException("Concordance %s must be an integer" % concordance_provider)
                old_value = wof_doc['properties']['wof:concordances'].get(concordance_provider)
                if old_value != new_value:
                    if new_value:
                        wof_doc['properties']['wof:concordances'][concordance_provider] = new_value
                    elif old_value is not None:
                        del wof_doc['properties']['wof:concordances'][concordance_provider]

            # Add any new concordances
            for form_key in filter(lambda i: i.startswith('new-wof:concordances-name'), request.form.keys()):
                new_row_suffix = form_key[25:]
                new_key = request.form.get(form_key)
                new_value = request.form.get('new-wof:concordances-value' + new_row_suffix)
                if new_key and new_value:
                    if new_key in concordance_ints:
                        try:
                            new_value = int(new_value)
                        except ValueError:
                            raise ValidationException("Concordance %s must be an integer" % new_key)
                    wof_doc['properties']['wof:concordances'][new_key] = new_value
        except ValidationException as e:
            flash("Problem validating changes: %s" % e)
            return redirect(request.url)

        # Validate those changes with the WOF validator code
        validator = mapzen.whosonfirst.validator.validator()
        report = validator.validate_feature(wof_doc)

        if not report.ok():
            report_output = io.StringIO()
            report.print_report(report_output)
            report_output.seek(0)

            flash("Error running WOF Validate on your changes: %s" % report_output)
            return redirect(request.url)

        # Exportify the new WOF document
        exporter = mapzen.whosonfirst.export.string()
        exportified_wof_doc = exporter.export_feature(wof_doc)

        if request.form['next-step'] == 'export':
            response = make_response(exportified_wof_doc)
            response.headers.set('Content-Type', 'application/json')
            response.headers.set('Content-Disposition', 'attachment', filename='%s.geojson' % wof_id)
            return response

        if current_user.is_anonymous:
            flash("Need to login first")
            session['next'] = request.url
            return redirect(url_for('auth.login'))

        # Begin the process of setting up a pull request
        base_repo = build_wof_repo_name(wof_doc)
        branch_name = build_wof_branchname(wof_doc)
        base_ref = 'heads/master'

        sess = requests.Session()
        sess.headers['Authorization'] = ('token ' + session.get('access_token'))

        # Get the sha of main branch
        resp = sess.get(
            'https://api.github.com/repos/%s/git/ref/%s' % (base_repo, base_ref),
        )
        current_app.logger.warn(log_response(resp))

        if resp.status_code == 200:
            base_ref_sha = resp.json()['object']['sha']
            current_app.logger.warn(
                "sha of the base ref %s in repo %s is %s",
                base_ref,
                base_repo,
                base_ref_sha,
            )
        else:
            try:
                message = resp.json().get('message')
            except ValueError:
                message = resp.content

            current_app.logger.error("Couldn't get base ref sha")
            flash("Couldn't get the SHA of the main branch in repo %s: %s" % (base_repo, message))
            return redirect(request.url)

        # Kick off a fork and wait for it to be created.
        # We used to try creating the branch on the original repo, but the
        # whosonfirst-data project needs to allow access for this app.
        resp = sess.post(
            'https://api.github.com/repos/%s/forks' % (base_repo,),
            json={},
        )
        current_app.logger.warn(log_response(resp))

        write_repo = None
        if resp.status_code == 202:
            fork_repo = resp.json()['full_name']
            fork_owner = resp.json()['owner']['login'] + ":"
            current_app.logger.warn("Forking %s to %s%s", base_repo, fork_owner, fork_repo)

            for t in range(3):
                # Try creating the branch in the fork
                resp = sess.post(
                    'https://api.github.com/repos/%s/git/refs' % (fork_repo,),
                    json={
                        'ref': 'refs/heads/%s' % branch_name,
                        'sha': base_ref_sha,
                    }
                )
                current_app.logger.warn(log_response(resp))

                if resp.status_code == 201:
                    write_repo = fork_repo
                    current_app.logger.warn(
                        "Branch %s created on forked repo %s",
                        branch_name,
                        fork_repo,
                    )
                    break
                elif resp.status_code == 403:
                    try:
                        message = resp.json().get("message")
                    except ValueError:
                        message = resp.content

                    current_app.logger.warn(
                        "Github 403'd creating the branch because: %s",
                        message,
                    )
                    flash("Github prevented the editor from creating a branch: %s" % message)
                    return redirect(request.url)
                else:
                    current_app.logger.warn(
                        "Couldn't create branch at try %s, waiting 500ms and trying again",
                        t,
                    )
                    time.sleep(0.5)

        else:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = resp.content

            current_app.logger.warn(
                "Couldn't start fork creation: %s",
                message,
            )
            flash("Couldn't create a fork: %s" % message)
            return redirect(request.url)

        if not write_repo:
            current_app.logger.error("No write_repo set, so nowhere to create the branch.")
            flash("Couldn't determine the repo to create the branch on")
            return redirect(request.url)

        current_app.logger.warn("Writing to branch %s on repo %s", branch_name, write_repo)

        # Create a 'blob' with the contents of the updated file
        file_content_b64 = base64.standard_b64encode(exportified_wof_doc.encode('utf8')).decode('utf8')
        resp = sess.post(
            'https://api.github.com/repos/%s/git/blobs' % (write_repo,),
            json={
                "content": file_content_b64,
                "encoding": "base64",
            }
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 201:
            new_blob_sha = resp.json()['sha']
            current_app.logger.warn(
                "Created new blob with updated data in repo %s, sha %s",
                write_repo,
                new_blob_sha,
            )
        else:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = resp.content

            current_app.logger.error("Couldn't create new blob")
            flash("Couldn't create the blob on %s: %s" % (write_repo, message))
            return redirect(request.url)

        # Create a 'tree' with the blob above attached to it
        resp = sess.post(
            'https://api.github.com/repos/%s/git/trees' % (write_repo,),
            json={
                "base_tree": base_ref_sha,
                "tree": [{
                    "path": file_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": new_blob_sha,
                }]
            }
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 201:
            new_tree_sha = resp.json()['sha']
            current_app.logger.warn(
                "Created new tree with changed data for file %s attached in repo %s, sha %s",
                file_path,
                write_repo,
                new_tree_sha,
            )
        else:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = resp.content

            current_app.logger.error("Couldn't create new tree")
            flash("Couldn't create the tree on %s: %s" % (write_repo, message))
            return redirect(request.url)

        # Create a new 'commit' that attaches the tree created above to the branch
        resp = sess.post(
            'https://api.github.com/repos/%s/git/commits' % (write_repo,),
            json={
                "message": "Updating place %s" % (place_name or wof_id),
                "tree": new_tree_sha,
                "parents": [base_ref_sha],
            }
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 201:
            new_commit_sha = resp.json()['sha']
            current_app.logger.warn(
                "Created new commit with data for file %s attached in repo %s, sha %s",
                file_path,
                write_repo,
                new_commit_sha,
            )
        else:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = resp.content

            current_app.logger.error("Couldn't create new commit")
            flash("Couldn't create the commit on %s: %s" % (write_repo, message))
            return redirect(request.url)

        # Update the reference of the branch to this new commit
        resp = sess.patch(
            'https://api.github.com/repos/%s/git/refs/heads/%s' % (write_repo, branch_name),
            json={
                "sha": new_commit_sha,
            }
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 200:
            current_app.logger.warn(
                "Updated ref %s with commit %s",
                branch_name,
                new_commit_sha,
            )
        else:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = resp.content

            current_app.logger.error("Couldn't update ref")
            flash("Couldn't update the ref on %s: %s" % (write_repo, message))
            return redirect(request.url)

        # We've created a file, now let's create the pull request
        resp = sess.post(
            'https://api.github.com/repos/%s/pulls' % (base_repo,),
            json={
                "title": "Update Place %s" % (place_name or wof_id),
                "head": (fork_owner + branch_name),
                "base": "master",
                "body": "Updating `%s` using the [WOF Editor](https://github.com/iandees/wof-editor)" % file_path,
                "maintainer_can_modify": True,
                "draft": False,
            }
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 201:
            pr_url = resp.json()['html_url']

            current_app.logger.warn(
                "Created pull request %s",
                pr_url,
            )

            return redirect(pr_url)
        else:
            try:
                message = resp.json().get("message")
            except ValueError:
                message = resp.content

            current_app.logger.error("Couldn't create pull request")
            flash("Couldn't create the pull request on %s: %s" % (write_repo, message))
            return redirect(request.url)

    return render_template(
        'place/edit.html',
        wof_url=wof_url,
        wof_doc=wof_doc,
        provider_expansion=provider_expansion,
        lang_expansion=lang_expansion,
        name_specs=name_specs,
        localized_names=localized_names,
        localized_names_tagify_whitelist=localized_names_tagify_whitelist,
        label_specs=label_specs,
        localized_labels=localized_labels,
        localized_labels_tagify_whitelist=localized_labels_tagify_whitelist,
    )

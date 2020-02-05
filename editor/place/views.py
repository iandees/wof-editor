import base64
import collections
import io
import json
import mapzen.whosonfirst.validator
import random
import requests
import string
import time
from . import place_bp
from flask_login import current_user
from flask import (
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
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


@place_bp.app_template_filter()
def expand_spec(spec):
    return spec_expansion.get(spec, spec)


@place_bp.app_template_filter()
def expand_lang(lang):
    return lang_expansion.get(lang, lang)


@place_bp.route('/')
def root_page():
    return render_template('place/index.html')


def log_response(resp):
    return "{req_method} {req_url} (data {req_body}) results in HTTP {res_status} (data {res_body})".format(
        req_method=resp.request.method,
        req_url=resp.request.url,
        req_body=resp.request.body[:500] if resp.request.body else "<none>",
        res_status=resp.status_code,
        res_body=resp.content[:500] if resp.content else "<none>",
    )


def build_wof_doc_url_suffix(wof_id):
    id_url_str = str(wof_id)
    id_url_prefix = '/'.join(id_url_str[x:x+3] for x in range(0, len(id_url_str), 3))

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


def apply_change(wof, form, attr_name, formatter=str):
    raw_new_value = form[attr_name]
    old_value = wof['properties'].get(attr_name)

    if old_value != raw_new_value:
        if raw_new_value not in ([], ""):
            try:
                new_value = formatter(raw_new_value)
            except ValidationException as e:
                raise ValidationException("Error in field %s: %s" % (attr_name, e))

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


@place_bp.route('/place/<int:wof_id>/edit', methods=["GET", "POST"])
def edit_place(wof_id):
    # Load the WOF doc for display/edit
    wof_doc_url_suffix = build_wof_doc_url_suffix(wof_id)
    resp = requests.get("https://data.whosonfirst.org/" + wof_doc_url_suffix)
    current_app.logger.warn(log_response(resp))
    if resp.status_code == 200:
        wof_doc = resp.json()
    elif resp.status_code == 404:
        return "that wof doc doesn't exist", 404
    else:
        return "problem getting wof doc: HTTP %s for %s" % (resp.status_code, resp.request.url), 500

    # Put localized_names and labels information in a more convenient container
    localized_names = parse_prefix_map(wof_doc['properties'], 'name:')
    localized_labels = parse_prefix_map(wof_doc['properties'], 'label:')

    if request.method == 'POST':

        # Consume the changes from the form
        try:
            apply_change(wof_doc, request.form, "wof:name")
            apply_change(wof_doc, request.form, "wof:shortcode")
            apply_change(wof_doc, request.form, "mz:is_current", maybe_int)
            apply_change(wof_doc, request.form, "mz:is_funky", maybe_int)
            apply_change(wof_doc, request.form, "mz:hierarchy_label")
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
            apply_change(wof_doc, request.form, "iso:country")

            for k in filter(lambda i: i.startswith('name:'), request.form.keys()):
                apply_change(wof_doc, request.form, k, list_of_str)
            for k in filter(lambda i: i.startswith('name:'), wof_doc['properties'].keys()):
                apply_change(wof_doc, request.form, k, list_of_str)

            for k in filter(lambda i: i.startswith('label:'), request.form.keys()):
                apply_change(wof_doc, request.form, k, list_of_str)
            for k in filter(lambda i: i.startswith('label:'), wof_doc['properties'].keys()):
                apply_change(wof_doc, request.form, k, list_of_str)
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

        file_path = "data/" + wof_doc_url_suffix
        place_name = wof_doc['properties']['wof:name']

        sess = requests.Session()
        sess.headers['Authorization'] = ('token ' + session.get('access_token'))

        # Get the sha1 of `master` branch
        resp = sess.get('https://api.github.com/repos/%s/git/ref/%s' % (base_repo, base_ref))
        current_app.logger.warn(log_response(resp))
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
        current_app.logger.warn(log_response(resp))

        if resp.status_code == 404:
            current_app.logger.warn(
                "Doesn't look like we have access to create a branch in repo, so creating a fork"
            )

            # Kick off a fork and wait for it to be created
            resp = sess.post(
                'https://api.github.com/repos/%s/forks' % (base_repo,),
                json={},
            )
            current_app.logger.warn(log_response(resp))

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
                        write_repo = fork_repo
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
            current_app.logger.warn(log_response(resp))

            if resp.status_code == 201:
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

        # Now that we have a branch that we can write to, update the file on it
        resp = sess.get(
            'https://api.github.com/repos/%s/contents/%s' % (write_repo, file_path),
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 200:
            existing_file_sha = resp.json()['sha']
            current_app.logger.warn(
                "Will update file %s with sha %s in repo %s",
                file_path,
                existing_file_sha,
                write_repo,
            )
        else:
            return "couldn't find existing file %s in %s" % (file_path, write_repo), 500

        file_content_b64 = base64.standard_b64encode(exportified_wof_doc.encode('utf8')).decode('utf8')

        resp = sess.put(
            'https://api.github.com/repos/%s/contents/%s' % (write_repo, file_path),
            json={
                "message": "Updating %s" % place_name,
                "content": file_content_b64,
                "branch": branch_name,
                "sha": existing_file_sha,
            }
        )

        current_app.logger.warn(log_response(resp))
        if resp.status_code == 200:
            current_app.logger.warn(
                "File %s was updated in repo %s on branch %s, commit %s",
                file_path,
                write_repo,
                branch_name,
                resp.json()['commit']['sha'],
            )

        else:
            return "couldn't update file on branch", 500

        # We've created a file, now let's create the pull request
        resp = sess.post(
            'https://api.github.com/repos/%s/pulls' % (base_repo,),
            json={
                "title": "Update Place %s" % place_name,
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
            return "couldn't create pull request", 500

    return render_template(
        'place/edit.html',
        wof_doc=wof_doc,
        name_specs=name_specs,
        localized_names=localized_names,
        label_specs=label_specs,
        localized_labels=localized_labels,
    )

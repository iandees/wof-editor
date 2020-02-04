from . import auth_bp
from .oauth import OAuthSignIn
from .user import User
from urllib.parse import urlparse, urljoin
from flask_login import (
    current_user,
    login_user,
    logout_user,
)
from flask import (
    flash,
    redirect,
    request,
    session,
    url_for,
)


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
        ref_url.netloc == test_url.netloc


def get_redirect_target():
    for target in request.values.get('next'), request.referrer:
        if not target:
            continue
        if is_safe_url(target):
            return target


@auth_bp.route('/login')
def login():
    if not current_user.is_anonymous:
        next_url = session.pop('next', None) or url_for('place.root_page')
        return redirect(next_url)
    else:
        return redirect(url_for('auth.oauth_authorize', provider='github'))


@auth_bp.route('/logout')
def logout():
    logout_user()
    session.pop('access_token', None)
    session.pop('next', None)
    return redirect(url_for('place.root_page'))


@auth_bp.route('/authorize/<provider>')
def oauth_authorize(provider):
    if not current_user.is_anonymous:
        return redirect(session.pop('next'))
    oauth = OAuthSignIn.get_provider(provider)
    return oauth.authorize()


@auth_bp.route('/callback/<provider>')
def oauth_callback(provider):
    if not current_user.is_anonymous:
        return redirect(session.pop('next'))

    oauth = OAuthSignIn.get_provider(provider)
    if not oauth:
        return 'unknown provider', 404

    social_id, username, email, access_token = oauth.callback()

    if social_id is None:
        flash("For some reason, we couldn't log you in. "
              "Please contact us!", 'error')
        return redirect(url_for('place.root_page'))

    user = User(social_id)

    login_user(user, True)
    session['access_token'] = access_token

    next_url = session.pop('next', None)

    return redirect(next_url)

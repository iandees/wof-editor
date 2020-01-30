from rauth import OAuth2Service
from flask import (
    current_app,
    url_for,
    request,
    redirect,
    session,
    json,
)


class OAuthSignIn(object):
    def __init__(self, provider_name, config):
        self.provider_name = provider_name
        self.consumer_id = config['id']
        self.consumer_secret = config['secret']

    def authorize(self):
        pass

    def callback(self):
        pass

    def get_callback_url(self):
        print("get_callback_url; provider=%s" % self.provider_name)
        return url_for('auth.oauth_callback',
                       provider=self.provider_name,
                       _external=True,
                       _scheme='https')

    @classmethod
    def get_provider(self, provider_name):
        if provider_name in providers:
            return providers[provider_name]

        provider_class = provider_classes.get(provider_name)

        if not provider_class:
            # We don't have a class for the requested provider
            providers[provider_name] = None
            return None

        oauth_config = current_app.config.get('OAUTH_CREDENTIALS')
        provider_config = oauth_config.get(provider_name)

        if not provider_config:
            # The provider is not configured
            providers[provider_name] = None
            return None

        provider = provider_class(provider_config)
        providers[provider_name] = provider
        return provider


class GithubSignIn(OAuthSignIn):
    def __init__(self, config):
        super(GithubSignIn, self).__init__('github', config)
        self.service = OAuth2Service(
            name='github',
            client_id=self.consumer_id,
            client_secret=self.consumer_secret,
            authorize_url='https://github.com/login/oauth/authorize',
            access_token_url='https://github.com/login/oauth/access_token',
            base_url='https://api.github.com/'
        )

    def authorize(self):
        print("In authorize()")
        return redirect(self.service.get_authorize_url(
            scope='user:email',
            response_type='code',
            redirect_uri=self.get_callback_url())
        )

    def callback(self):
        if 'code' not in request.args:
            return None, None, None

        print("In callback()")
        oauth_session = self.service.get_auth_session(
            data={
                'code': request.args['code'],
                'grant_type': 'authorization_code',
                'redirect_uri': self.get_callback_url(),
            },
        )

        me = oauth_session.get('user').json()

        return (
            'github$%s' % me['id'],
            me['name'],
            me['email'],
            oauth_session.access_token,
        )


providers = {}
provider_classes = {
    'github': GithubSignIn,
}

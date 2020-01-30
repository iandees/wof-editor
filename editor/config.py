import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', None)

    OAUTH_CREDENTIALS = {
        'github': {
            'id': os.environ.get('GITHUB_APP_ID'),
            'secret': os.environ.get('GITHUB_APP_SECRET'),
        }
    }

    @classmethod
    def init_app(cls, app):
        pass


class LocalConfig(Config):
    SECRET_KEY = "abc123"


class ProductionConfig(Config):
    pass


config = {
    'local': LocalConfig,
    'production': ProductionConfig,
    'default': LocalConfig,
}

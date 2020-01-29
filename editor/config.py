import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', None)

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

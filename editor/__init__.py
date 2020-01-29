from flask import Flask
from flask_bootstrap import Bootstrap

from editor.config import config
from .exportify import exportify_bp
from .place import place_bp


def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    Bootstrap(app)

    app.register_blueprint(exportify_bp)
    app.register_blueprint(place_bp)

    return app

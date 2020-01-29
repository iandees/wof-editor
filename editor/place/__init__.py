from flask import Blueprint

place_bp = Blueprint('place', __name__)

from . import views

from . import place_bp
from flask import (
    render_template,
)


@place_bp.route('/')
def root_page():
    return render_template('place/index.html')


@place_bp.route('/place/<int:id>/edit')
def edit_place(id):
    return render_template('place/edit.html')

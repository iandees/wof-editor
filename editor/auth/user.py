from flask_login import UserMixin
from .. import login_manager


@login_manager.user_loader
def load_user(id):
    return User(id)


class User(UserMixin):
    def __init__(self, social_id):
        self.social_id = social_id

    @property
    def id(self):
        return self.social_id

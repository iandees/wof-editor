import os
from editor import create_app

app = create_app(os.environ.get('WOF_ENV', 'default'))

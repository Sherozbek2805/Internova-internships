from flask_mail import Mail
from flask_jwt_extended import JWTManager
from authlib.integrations.flask_client import OAuth
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

mail = Mail()
jwt = JWTManager()
oauth = OAuth()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])

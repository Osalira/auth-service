from flask import Blueprint
from controllers.auth_controller import register_user, login_user

# Create a Blueprint for authentication routes
auth_bp = Blueprint('auth', __name__)

# Register routes
auth_bp.route('/register', methods=['POST'])(register_user)
auth_bp.route('/login', methods=['POST'])(login_user) 
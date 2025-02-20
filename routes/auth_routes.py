import logging
from flask import Blueprint, request, jsonify
from controllers.auth_controller import register_user, login_user

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create a Blueprint for authentication routes
auth_bp = Blueprint('auth', __name__)

# Register routes
auth_bp.route('/register', methods=['POST'])(register_user)
auth_bp.route('/login', methods=['POST'])(login_user)

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        logger.debug(f"Login attempt for user: {data.get('username')}")
        result = login_user(data)
        if 'token' in result:
            logger.info(f"Successfully generated JWT token for user: {data.get('username')}")
            logger.debug(f"Token details - algorithm: HS256, secret key length: {len(data.get('jwt_secret_key'))}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        return jsonify({'error': str(e)}), 401 
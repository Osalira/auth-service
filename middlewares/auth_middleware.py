from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

def token_required(f):
    """
    Decorator to protect routes that require authentication.
    Verifies the JWT token in the request header.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            # Verify the JWT in the request
            verify_jwt_in_request()
            # Get the current user's identity
            current_user = get_jwt_identity()
            return f(current_user, *args, **kwargs)
        except Exception as e:
            return jsonify({'error': 'Invalid or missing token'}), 401
    return decorated 
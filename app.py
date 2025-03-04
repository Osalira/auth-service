from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
from flask_cors import CORS
from dotenv import load_dotenv
import os
import logging
import jwt as pyjwt
from datetime import datetime, timezone
from sqlalchemy import inspect
import time
import tempfile
import fcntl

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/auth_service.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Configure JWT
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
app.config['JWT_SECRET_KEY'] = JWT_SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', 3600))
app.config['JWT_TOKEN_LOCATION'] = ['headers']
app.config['JWT_HEADER_NAME'] = 'token'
app.config['JWT_HEADER_TYPE'] = ''  # No prefix needed
jwt = JWTManager(app)

# Configure CORS
CORS(app)

# Import database and models
from database import engine, Base
import models  # Import models to register them with Base

# Use a lock file to prevent concurrent schema creation
def initialize_database():
    lock_file = os.path.join(tempfile.gettempdir(), 'auth_service_db_init.lock')
    try:
        with open(lock_file, 'w') as f:
            # Try to acquire an exclusive lock
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.info("Acquired lock for database initialization")
                
                # Now check if tables exist
                inspector = inspect(engine)
                if not inspector.has_table("accounts"):
                    logger.info("Creating database tables as they don't exist")
                    Base.metadata.create_all(bind=engine)
                else:
                    logger.info("Database tables already exist, skipping creation")
                    
                # Release the lock
                fcntl.flock(f, fcntl.LOCK_UN)
                logger.info("Released lock for database initialization")
                
            except IOError:
                logger.info("Another process is initializing the database, waiting...")
                # Wait for the other process to finish initialization
                time.sleep(2)
                logger.info("Continuing after waiting for database initialization")
                
    except Exception as e:
        logger.error(f"Error during database initialization: {str(e)}")
        # Continue execution even if there's an error with the lock mechanism

# Initialize the database with a lock to prevent race conditions
initialize_database()

# Import routes
from routes import auth_bp

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/authentication')

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "auth-service"})

@app.route('/authentication/validate-token', methods=['POST'])
def validate_token():
    """
    Dedicated endpoint for token validation.
    Extracts token from various sources and validates it.
    Returns user information if valid.
    """
    logger.debug("Token validation request received")
    
    # Get token from request
    if not request.is_json:
        return jsonify({"success": False, "error": "Request must be JSON"}), 400
        
    token = request.json.get('token')
    if not token:
        return jsonify({"success": False, "error": "Token is missing"}), 401
    
    try:
        # Decode token without verifying subject type
        decoded_token = pyjwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=['HS256'],
            options={"verify_sub": False}  # Don't verify subject type
        )
        
        # Extract user info from the subject claim
        user_info = decoded_token.get('sub')
        if not user_info:
            return jsonify({
                "success": False,
                "error": "Token missing user information"
            }), 401
        
        # Return user info and token data
        return jsonify({
            "success": True,
            "data": {
                "user": user_info,
                "token_data": {
                    "exp": decoded_token.get('exp'),
                    "iat": decoded_token.get('iat'),
                    "jti": decoded_token.get('jti'),
                    "type": decoded_token.get('type')
                }
            }
        }), 200
        
    except pyjwt.ExpiredSignatureError:
        return jsonify({
            "success": False,
            "error": "Token has expired"
        }), 401
    except pyjwt.InvalidTokenError as e:
        return jsonify({
            "success": False,
            "error": f"Invalid token: {str(e)}"
        }), 401
    except Exception as e:
        logger.error(f"Token validation failed with unexpected error: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Token validation error: {str(e)}"
        }), 401

if __name__ == '__main__':
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Run the app
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true') 
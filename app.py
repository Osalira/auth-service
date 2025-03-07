from flask import Flask, jsonify, request, Response
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
import threading
from rabbitmq import start_consumer, publish_event

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
from database import engine, Base, get_db
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
app.register_blueprint(auth_bp)

# Event handlers for RabbitMQ consumers
def handle_user_events(event):
    """Handle user-related events"""
    logger.info(f"Received user event: {event.get('event_type')}")
    
    event_type = event.get('event_type')
    try:
        if event_type == 'user.login':
            # Log the login event
            user_id = event.get('user_id')
            username = event.get('username')
            logger.info(f"User login: {username} (ID: {user_id})")
            
            # Update last_login in database if needed
            db = get_db()
            user = db.query(models.Account).filter_by(id=user_id).first()
            if user:
                user.last_login = datetime.utcnow()
                db.commit()
                logger.info(f"Updated last_login for user {username}")
            db.close()
        
        elif event_type == 'user.password_reset_requested':
            # Process password reset request
            username = event.get('username')
            logger.info(f"Password reset requested for user: {username}")
            
            # You would implement password reset logic here
            # For example, generate a token and send an email

        elif event_type == 'system.error':
            # Log system errors
            service = event.get('service')
            error = event.get('error')
            logger.error(f"System error in {service}: {error}")
    
    except Exception as e:
        logger.error(f"Error processing user event: {str(e)}")
        # Publish error event
        error_event = {
            'event_type': 'system.error',
            'service': 'auth-service',
            'operation': 'event_processing',
            'error': str(e),
            'original_event': event
        }
        publish_event('system_events', 'system.error', error_event)

def start_event_consumers():
    """Start RabbitMQ event consumers"""
    try:
        # Start consumer for user events
        logger.info("Starting user events consumer")
        start_consumer(
            queue_name='auth_service_user_events',
            routing_keys=['user.login', 'user.logout', 'user.password_reset_requested'],
            exchange='user_events',
            callback=handle_user_events
        )
        
        # Start consumer for system events
        logger.info("Starting system events consumer")
        start_consumer(
            queue_name='auth_service_system_events',
            routing_keys=['system.error', 'system.notification'],
            exchange='system_events',
            callback=handle_user_events
        )
        
        logger.info("Event consumers started successfully")
    except Exception as e:
        logger.error(f"Failed to start event consumers: {str(e)}")

# Start event consumers in a separate thread after a short delay
def delayed_start_event_consumers():
    """Start event consumers after a short delay to ensure app is fully initialized"""
    def start_consumers_thread():
        # Wait a few seconds for the app to fully initialize
        time.sleep(5)
        start_event_consumers()
    
    # Start the delayed consumer thread
    consumer_thread = threading.Thread(target=start_consumers_thread)
    consumer_thread.daemon = True
    consumer_thread.start()

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
    
    # Start event consumers after a short delay
    delayed_start_event_consumers()
    
    # Run the app
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true') 
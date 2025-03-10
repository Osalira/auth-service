from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging
import uuid
import threading

from database import get_db, get_db_context
from models import Account, User, Company
from rabbitmq import publish_event

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    trace_id = uuid.uuid4().hex[:8]
    
    # Handle JMeter test format (user_name instead of username)
    if 'user_name' in data and 'username' not in data:
        data['username'] = data['user_name']
    
    # Set default account_type if not provided
    if 'account_type' not in data:
        data['account_type'] = 'user'
    
    # Set default email if not provided for user accounts
    if data['account_type'] == 'user' and 'email' not in data and 'name' in data:
        data['email'] = f"{data['username']}@example.com"
    
    # Validate required fields
    required_fields = ['username', 'password']
    for field in required_fields:
        if field not in data:
            return jsonify({"success": False, "data": {"error": f"Missing required field: {field}"}}), 400
    
    # Additional validation for user or company specific fields
    if data['account_type'] == 'user':
        if 'name' not in data:
            # Use username as name if not provided
            data['name'] = data['username']
        if 'email' not in data:
            # Generate a default email if not provided
            data['email'] = f"{data['username']}@example.com"
    elif data['account_type'] == 'company':
        if 'company_name' not in data:
            return jsonify({"success": False, "data": {"error": "Company name is required for company accounts"}}), 400
        if 'business_registration' not in data:
            return jsonify({"success": False, "data": {"error": "Business registration number is required for company accounts"}}), 400
        if 'company_email' not in data:
            # Generate a default email if not provided
            data['company_email'] = f"{data['username']}@company.com"
    
    # First, check if username exists without opening a transaction
    try:
        # Use a short-lived connection just to check username existence
        with get_db_context() as db:
            existing_account = db.query(Account.id).filter_by(username=data['username']).first()
            
            if existing_account:
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing username: {data['username']}")
                return jsonify({"success": False, "data": {"error": "Username already exists", "trace_id": trace_id}}), 400
    except Exception as e:
        logger.error(f"[TraceID: {trace_id}] Error checking for existing username: {str(e)}")
        # Continue to try the full registration process even if the check failed
    
    # Process the registration if username doesn't exist
    try:
        with get_db_context() as db:
            # Create the account
            account = Account(
                username=data['username'],
                account_type=data['account_type'],
                created_at=datetime.utcnow()
            )
            account.set_password(data['password'])
            db.add(account)
            
            # Flush to get the account ID
            db.flush()
            
            # Create the user-specific or company-specific record
            if data['account_type'] == 'user':
                user = User(
                    id=account.id,  # Use id instead of account_id to match the model
                    name=data['name'],
                    email=data['email']
                )
                db.add(user)
                response_data = {
                    "success": True,
                    "data": {
                        "id": account.id,
                        "username": account.username,
                        "account_type": account.account_type,
                        "name": data['name'],
                        "email": data['email'],
                        "trace_id": trace_id
                    }
                }
            else:  # company
                company = Company(
                    id=account.id,  # Use id instead of account_id to match the model
                    company_name=data['company_name'],
                    business_registration=data['business_registration'],
                    company_email=data['company_email']
                )
                db.add(company)
                response_data = {
                    "success": True,
                    "data": {
                        "id": account.id,
                        "username": account.username,
                        "account_type": account.account_type,
                        "company_name": data['company_name'],
                        "business_registration": data['business_registration'],
                        "company_email": data['company_email'],
                        "trace_id": trace_id
                    }
                }
            
            # Commit the transaction
            db.commit()
            
            # Queue events for publishing (no thread creation)
            try:
                # Create event data
                registration_started_event = {
                    'event_type': 'user.registration_started',
                    'username': data['username'],
                    'account_type': data['account_type'],
                    'timestamp': datetime.utcnow().isoformat(),
                    'trace_id': trace_id
                }
                
                user_registered_event = {
                    'event_type': 'user.registered',
                    'user_id': account.id, 
                    'username': account.username,
                    'account_type': account.account_type,
                    'created_at': datetime.utcnow().isoformat(),
                    'trace_id': trace_id
                }
                
                # Add account-specific data to the event
                if data['account_type'] == 'user':
                    user_registered_event.update({
                        'name': user.name,
                        'email': user.email
                    })
                else:  # company
                    user_registered_event.update({
                        'company_name': company.company_name,
                        'business_registration': company.business_registration,
                        'company_email': company.company_email
                    })
                
                # Publish events via the queue system
                publish_event('user_events', 'user.registration_started', registration_started_event)
                publish_event('user_events', 'user.registered', user_registered_event)
            except Exception as e:
                logger.error(f"[TraceID: {trace_id}] Failed to queue registration events: {str(e)}")
            
            return jsonify(response_data), 201
            
    except IntegrityError as e:
        db.rollback()
        error_message = str(e)
        logger.error(f"[TraceID: {trace_id}] IntegrityError during registration: {error_message}")
        
        # Create error event data
        error_event = {
            'event_type': 'user.registration_failed',
            'username': data['username'],
            'error': str(e),
            'trace_id': trace_id
        }
        
        # Queue error event without creating a thread
        try:
            publish_event('system_events', 'user.registration_failed', error_event)
        except Exception as e:
            logger.error(f"[TraceID: {trace_id}] Failed to queue error event: {str(e)}")
        
        # More robust checks for username constraint violations
        if "accounts.username" in error_message or "accounts_username_key" in error_message or "username" in error_message:
            return jsonify({"success": False, "data": {"error": "Username already exists (caught in IntegrityError)", "trace_id": trace_id}}), 400
        
        # More robust checks for business registration constraint violations
        elif "companies.business_registration" in error_message or "business_registration_key" in error_message:
            return jsonify({"success": False, "data": {"error": "Business registration already exists", "trace_id": trace_id}}), 400
        
        # If we couldn't identify the error type, return a generic error
        else:
            return jsonify({"success": False, "data": {"error": f"Database error: {error_message}", "trace_id": trace_id}}), 400
    
    except Exception as e:
        db.rollback()
        logger.error(f"[TraceID: {trace_id}] Registration error: {str(e)} (Type: {type(e).__name__})")
        
        # Create error event data
        error_event = {
            'event_type': 'system.error',
            'service': 'auth-service',
            'operation': 'register',
            'error': str(e),
            'error_type': type(e).__name__,
            'trace_id': trace_id
        }
        
        # Queue error event without creating a thread
        try:
            publish_event('system_events', 'system.error', error_event)
        except Exception as e:
            logger.error(f"[TraceID: {trace_id}] Failed to queue error event: {str(e)}")
        
        # Check if it's a database connection issue
        if "timeout" in str(e).lower() or "connection" in str(e).lower():
            logger.error(f"[TraceID: {trace_id}] Database connection issue: {str(e)}")
            return jsonify({"success": False, "data": {"error": "Database connection issue. Please try again later.", "trace_id": trace_id}}), 503
        
        # Generic error
        return jsonify({"success": False, "data": {"error": f"An unexpected error occurred: {str(e)}", "trace_id": trace_id}}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    # Handle JMeter test format (user_name instead of username)
    if 'user_name' in data and 'username' not in data:
        data['username'] = data['user_name']
    
    # Validate required fields
    if 'username' not in data or 'password' not in data:
        return jsonify({"success": False, "data": {"error": "Username and password are required"}}), 400
    
    # Use context manager for database session
    try:
        with get_db_context() as db:
            # Find the account
            account = db.query(Account).filter_by(username=data['username']).first()
            
            # Check if account exists and password is correct
            if not account or not account.check_password(data['password']):
                return jsonify({"success": False, "data": {"error": "Invalid username or password"}}), 400
            
            # Check if account is active
            if not account.is_active:
                return jsonify({"success": False, "data": {"error": "Account is inactive"}}), 403
            
            # Update last login
            account.last_login = datetime.utcnow()
            
            # Get user or company details
            account_details = {}
            if account.account_type == 'user':
                user = db.query(User).filter_by(id=account.id).first()
                if user:
                    account_details = {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "account_balance": float(user.account_balance) if user.account_balance else 0.0
                    }
            else:  # company
                company = db.query(Company).filter_by(id=account.id).first()
                if company:
                    account_details = {
                        "id": company.id,
                        "company_name": company.company_name,
                        "business_registration": company.business_registration,
                        "company_email": company.company_email
                    }
            
            # Create access token
            access_token = create_access_token(
                identity={
                    "id": account.id,
                    "username": account.username,
                    "account_type": account.account_type,
                    **account_details
                }
            )
            
            # Format response as expected by JMeter
            response_data = {
                "success": True,
                "data": {
                    "token": access_token,
                    "message": "Login successful",
                    "account": {
                        "id": account.id,
                        "username": account.username,
                        "account_type": account.account_type,
                        **account_details
                    }
                }
            }
            
            return jsonify(response_data), 200
            
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        return jsonify({"success": False, "data": {"error": f"Error during login: {str(e)}"}}), 500

# Extra endpoints (optional, for completeness)

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    current_user = get_jwt_identity()
    
    db = get_db()
    try:
        account = db.query(Account).filter(Account.id == current_user['id']).first()
        
        if not account:
            return jsonify({"success": False, "data": {"error": "User not found"}}), 404
        
        # Get additional information based on account type
        additional_info = {}
        if account.account_type == 'user':
            user = db.query(User).filter(User.id == account.id).first()
            if user:
                additional_info = user.to_dict()
        else:  # company
            company = db.query(Company).filter(Company.id == account.id).first()
            if company:
                additional_info = company.to_dict()
        
        user_data = {
            "id": account.id,
            "username": account.username,
            "account_type": account.account_type,
            **additional_info
        }
        
        return jsonify({
            "success": True,
            "data": user_data
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get current user: {str(e)}")
        return jsonify({"success": False, "data": {"error": f"Failed to get current user: {str(e)}"}}), 500 
from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging
import uuid

from database import get_db
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
        # For company accounts, only company_name is required, which can come from 'name' field
        if 'name' not in data and 'company_name' not in data:
            return jsonify({"success": False, "data": {"error": "Company accounts require a name"}}), 400
        
        # Use 'name' as 'company_name' if not provided
        if 'company_name' not in data:
            data['company_name'] = data['name']
        
        # Generate default values for required company fields
        if 'business_registration' not in data:
            # Generate a unique business registration
            data['business_registration'] = f"BR-{uuid.uuid4().hex[:8].upper()}"
        
        if 'company_email' not in data:
            # Generate a default company email
            data['company_email'] = f"{data['username']}-company@example.com"
    else:
        return jsonify({"success": False, "data": {"error": "Invalid account_type. Must be 'user' or 'company'"}}), 400
    
    db = get_db()
    try:
        # First check if username already exists BEFORE attempting creation
        existing_account = db.query(Account).filter_by(username=data['username']).first()
        if existing_account:
            logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing username: {data['username']}")
            return jsonify({"success": False, "data": {"error": "Username already exists", "trace_id": trace_id}}), 400
            
        # Check for email uniqueness if provided
        if data['account_type'] == 'user' and 'email' in data:
            existing_email = db.query(User).filter_by(email=data['email']).first()
            if existing_email:
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing email: {data['email']}")
                return jsonify({"success": False, "data": {"error": "Email already exists", "trace_id": trace_id}}), 400
                
        # Check for company email uniqueness if provided
        if data['account_type'] == 'company' and 'company_email' in data:
            existing_company_email = db.query(Company).filter_by(company_email=data['company_email']).first()
            if existing_company_email:
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing company email: {data['company_email']}")
                return jsonify({"success": False, "data": {"error": "Company email already exists", "trace_id": trace_id}}), 400
                
        # Check for business registration uniqueness if provided
        if data['account_type'] == 'company' and 'business_registration' in data:
            existing_registration = db.query(Company).filter_by(business_registration=data['business_registration']).first()
            if existing_registration:
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing business registration: {data['business_registration']}")
                return jsonify({"success": False, "data": {"error": "Business registration already exists", "trace_id": trace_id}}), 400
            
        # Publish user registration attempt event (before actual creation)
        # This can be consumed by monitoring/fraud detection systems
        registration_started_event = {
            'event_type': 'user.registration_started',
            'username': data['username'],
            'account_type': data['account_type'],
            'timestamp': datetime.utcnow().isoformat(),
            'trace_id': trace_id
        }
        publish_event('user_events', 'user.registration_started', registration_started_event)
            
        # Create account
        account = Account(
            username=data['username'],
            account_type=data['account_type']
        )
        account.set_password(data['password'])
        
        db.add(account)
        db.flush()  # Flush to get the account ID
        
        # Create user or company based on account_type
        if data['account_type'] == 'user':
            user = User(
                id=account.id,
                name=data['name'],
                email=data['email'],
                account_balance=data.get('account_balance', 0.0)
            )
            db.add(user)
        else:  # company
            company = Company(
                id=account.id,
                company_name=data['company_name'],
                business_registration=data['business_registration'],
                company_email=data['company_email'],
                contact_phone=data.get('contact_phone'),
                address=data.get('address'),
                industry=data.get('industry'),
                total_shares_issued=data.get('total_shares_issued', 0),
                shares_available=data.get('shares_available', 0)
            )
            db.add(company)
        
        # Final commit - only commit here after everything is ready
        db.commit()
        
        # Return success response with account details
        account_data = {
            "id": account.id,
            "username": account.username,
            "account_type": account.account_type
        }
        
        # Get additional user or company details to include in the token
        account_details = {}
        if data['account_type'] == 'user':
            user = db.query(User).filter_by(id=account.id).first()
            if user:
                account_details = {
                    "name": user.name,
                    "email": user.email,
                    "account_balance": float(user.account_balance) if user.account_balance else 0.0
                }
                # Add these details to the account_data as well
                account_data.update(account_details)
        else:  # company
            company = db.query(Company).filter_by(id=account.id).first()
            if company:
                account_details = {
                    "company_name": company.company_name,
                    "business_registration": company.business_registration,
                    "company_email": company.company_email
                }
                # Add these details to the account_data as well
                account_data.update(account_details)
        
        # Create access token - just like in the login endpoint
        access_token = create_access_token(
            identity={
                "id": account.id,
                "username": account.username,
                "account_type": account.account_type,
                **account_details
            }
        )
        
        # Format response as expected by JMeter and the frontend
        response_data = {
            "success": True,
            "data": {
                "token": access_token,  # Include the token here
                "message": "Account created successfully",
                "account": account_data
            }
        }
        
        # Publish user.registered event
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
            
        # Publish the event asynchronously
        publish_event('user_events', 'user.registered', user_registered_event)
        logger.info(f"[TraceID: {trace_id}] Published user.registered event for user {account.username} (ID: {account.id})")
        
        return jsonify(response_data), 201
        
    except IntegrityError as e:
        db.rollback()
        error_message = str(e)
        logger.error(f"[TraceID: {trace_id}] IntegrityError during registration: {error_message}")
        
        # Publish registration error event
        error_event = {
            'event_type': 'user.registration_failed',
            'username': data['username'],
            'error': str(e),
            'trace_id': trace_id
        }
        publish_event('system_events', 'user.registration_failed', error_event)
        
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
        
        # Publish error event
        error_event = {
            'event_type': 'system.error',
            'service': 'auth-service',
            'operation': 'register',
            'error': str(e),
            'error_type': type(e).__name__,
            'trace_id': trace_id
        }
        publish_event('system_events', 'system.error', error_event)
        
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
    
    db = get_db()
    try:
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
        db.commit()
        
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
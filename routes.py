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
    trace_id = request.headers.get('X-Request-ID', uuid.uuid4().hex[:8])
    
    # OPTIMIZATION: Handle JMeter format efficiently, set defaults in one pass
    if 'user_name' in data and 'username' not in data:
        data['username'] = data['user_name']
    
    account_type = data.get('account_type', 'user')
    data['account_type'] = account_type
    
    # Set default email if not provided for user accounts
    if account_type == 'user':
        username = data.get('username', '')
        data['name'] = data.get('name', username)
        data['email'] = data.get('email', f"{username}@example.com")
    elif account_type == 'company':
        # Pre-check company fields to fail fast without DB queries
        if not data.get('company_name'):
            return jsonify({"success": False, "data": {"error": "Company name is required for company accounts"}}), 400
        if not data.get('business_registration'):
            return jsonify({"success": False, "data": {"error": "Business registration number is required for company accounts"}}), 400
        data['company_email'] = data.get('company_email', f"{data.get('username', '')}@company.com")
    
    # Validate required fields
    if not data.get('username'):
        return jsonify({"success": False, "data": {"error": "Missing required field: username"}}), 400
    if not data.get('password'):
        return jsonify({"success": False, "data": {"error": "Missing required field: password"}}), 400
    
    # Prepare events outside the main transaction to reduce transaction time
    registration_started_event = {
        'event_type': 'user.registration_started',
        'username': data['username'],
        'account_type': account_type,
        'timestamp': datetime.utcnow().isoformat(),
        'trace_id': trace_id
    }
    
    try:
        # Variables to store account info for use after the transaction
        account_id = None
        username = None
        account_type_val = None
        response_data = None
        
        # OPTIMIZATION: Use a single transaction for the entire operation
        with get_db_context() as db:
            # Check if username exists
            existing_account = db.query(Account.id).filter_by(username=data['username']).first()
            if existing_account:
                return jsonify({"success": False, "data": {"error": "Username already exists", "trace_id": trace_id}}), 400
            
            # Create the account with all fields set
            account = Account(
                username=data['username'],
                account_type=account_type,
                created_at=datetime.utcnow()
            )
            account.set_password(data['password'])
            db.add(account)
            
            # Flush to get the account ID
            db.flush()
            
            # Store account information before session closes
            account_id = account.id
            username = account.username
            account_type_val = account.account_type
            
            # Create account-specific record in the same transaction
            if account_type == 'user':
                db.add(User(
                    id=account.id,
                    name=data['name'],
                    email=data['email']
                ))
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
                db.add(Company(
                    id=account.id,
                    company_name=data['company_name'],
                    business_registration=data['business_registration'],
                    company_email=data['company_email']
                ))
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
                
        # OPTIMIZATION: Event publishing after transaction commit to reduce transaction duration
        # and prevent event publishing from blocking the response
        user_registered_event = {
            'event_type': 'user.registered',
            'user_id': account_id,
            'username': username,
            'account_type': account_type_val,
            'created_at': datetime.utcnow().isoformat(),
            'trace_id': trace_id
        }
            
        try:
            # Publish events asynchronously after transaction is committed
            publish_event('user_events', 'user.registration_started', registration_started_event)
            publish_event('user_events', 'user.registered', user_registered_event)
        except Exception as event_error:
            # Log but don't fail the registration if event publishing fails
            logger.error(f"[TraceID: {trace_id}] Error publishing registration events: {str(event_error)}")
        
        return jsonify(response_data), 201
        
    except IntegrityError as e:
        # Handle race condition where username might be taken concurrently
        logger.warning(f"[TraceID: {trace_id}] Integrity error during registration: {str(e)}")
        db_message = str(e).lower()
        if 'unique constraint' in db_message and 'username' in db_message:
            return jsonify({"success": False, "data": {"error": "Username already exists", "trace_id": trace_id}}), 400
        return jsonify({"success": False, "data": {"error": f"Database integrity error: {str(e)}", "trace_id": trace_id}}), 400
    except Exception as e:
        logger.error(f"[TraceID: {trace_id}] Error during registration: {str(e)}")
        return jsonify({"success": False, "data": {"error": f"Registration failed: {str(e)}", "trace_id": trace_id}}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    trace_id = request.headers.get('X-Request-ID', uuid.uuid4().hex[:8])
    
    # OPTIMIZATION: Handle JMeter format efficiently and validate in one pass
    username = data.get('user_name') or data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"success": False, "data": {"error": "Username and password are required", "trace_id": trace_id}}), 400
    
    try:
        with get_db_context() as db:
            # OPTIMIZATION: Use join to load account and user/company details in one query
            if data.get('account_type') == 'company':
                # Query for company accounts
                result = db.query(Account, Company).join(
                    Company, Account.id == Company.id
                ).filter(
                    Account.username == username
                ).first()
            else:
                # Query for user accounts (default)
                result = db.query(Account, User).join(
                    User, Account.id == User.id
                ).filter(
                    Account.username == username
                ).first()
            
            if not result:
                # If not found with joined query, try just the account
                account = db.query(Account).filter_by(username=username).first()
                if not account or not account.check_password(password):
                    return jsonify({"success": False, "data": {"error": "Invalid username or password", "trace_id": trace_id}}), 400
                
                # Account found but no associated user/company details
                account_type = account.account_type
                account_details = {}
            else:
                # Unpack the joined result
                account, details = result
                
                # Check password
                if not account.check_password(password):
                    return jsonify({"success": False, "data": {"error": "Invalid username or password", "trace_id": trace_id}}), 400
                
                # Check if account is active
                if not account.is_active:
                    return jsonify({"success": False, "data": {"error": "Account is inactive", "trace_id": trace_id}}), 403
                
                # Get account type and details
                account_type = account.account_type
                
                # Format details based on account type
                if account_type == 'user' and isinstance(details, User):
                    account_details = {
                        "id": details.id,
                        "name": details.name,
                        "email": details.email,
                        "account_balance": float(details.account_balance) if details.account_balance else 0.0
                    }
                elif account_type == 'company' and isinstance(details, Company):
                    account_details = {
                        "id": details.id,
                        "company_name": details.company_name,
                        "business_registration": details.business_registration,
                        "company_email": details.company_email
                    }
                else:
                    account_details = {}
            
            # Update last login if account has this field (add it to your model if needed)
            if hasattr(account, 'last_login'):
                account.last_login = datetime.utcnow()
            
            # Create access token with complete user information
            identity_data = {
                "id": account.id,
                "username": account.username,
                "account_type": account_type,
                **account_details
            }
            
            access_token = create_access_token(identity=identity_data)
            
            # Format response according to JMeter expectations
            response_data = {
                "success": True,
                "data": {
                    "token": access_token,
                    "message": "Login successful",
                    "account": identity_data,
                    "trace_id": trace_id
                }
            }
            
            return jsonify(response_data), 200
            
    except Exception as e:
        logger.error(f"[TraceID: {trace_id}] Error during login: {str(e)}")
        return jsonify({"success": False, "data": {"error": "Login failed", "trace_id": trace_id}}), 500

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
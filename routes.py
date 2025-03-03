from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging
import uuid

from database import get_db
from models import Account, User, Company

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    
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
            trace_id = uuid.uuid4().hex[:8]
            logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing username: {data['username']}")
            return jsonify({"success": False, "data": {"error": "Username already exists", "trace_id": trace_id}}), 400
            
        # Check for email uniqueness if provided
        if data['account_type'] == 'user' and 'email' in data:
            existing_email = db.query(User).filter_by(email=data['email']).first()
            if existing_email:
                trace_id = uuid.uuid4().hex[:8]
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing email: {data['email']}")
                return jsonify({"success": False, "data": {"error": "Email already exists", "trace_id": trace_id}}), 400
                
        # Check for company email uniqueness if provided
        if data['account_type'] == 'company' and 'company_email' in data:
            existing_company_email = db.query(Company).filter_by(company_email=data['company_email']).first()
            if existing_company_email:
                trace_id = uuid.uuid4().hex[:8]
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing company email: {data['company_email']}")
                return jsonify({"success": False, "data": {"error": "Company email already exists", "trace_id": trace_id}}), 400
                
        # Check for business registration uniqueness if provided
        if data['account_type'] == 'company' and 'business_registration' in data:
            existing_registration = db.query(Company).filter_by(business_registration=data['business_registration']).first()
            if existing_registration:
                trace_id = uuid.uuid4().hex[:8]
                logger.warning(f"[TraceID: {trace_id}] Attempted to register with existing business registration: {data['business_registration']}")
                return jsonify({"success": False, "data": {"error": "Business registration already exists", "trace_id": trace_id}}), 400
            
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
        return jsonify(response_data), 201
        
    except IntegrityError as e:
        db.rollback()
        error_message = str(e)
        trace_id = uuid.uuid4().hex[:8]
        logger.error(f"[TraceID: {trace_id}] IntegrityError during registration: {error_message}")
        
        # More robust checks for username constraint violations
        if "accounts.username" in error_message or "accounts_username_key" in error_message or "username" in error_message:
            return jsonify({"success": False, "data": {"error": "Username already exists (caught in IntegrityError)", "trace_id": trace_id}}), 400
        
        # More robust checks for business registration constraint violations
        elif "companies.business_registration" in error_message or "business_registration_key" in error_message:
            return jsonify({"success": False, "data": {"error": "Business registration already exists", "trace_id": trace_id}}), 400
        
        # More robust checks for company email constraint violations
        elif "companies.company_email" in error_message or "company_email_key" in error_message:
            return jsonify({"success": False, "data": {"error": "Company email already exists", "trace_id": trace_id}}), 400
        
        # More robust checks for user email constraint violations
        elif "users.email" in error_message or "users_email_key" in error_message:
            return jsonify({"success": False, "data": {"error": "Email address already exists", "trace_id": trace_id}}), 400
        
        # If it's another unique constraint violation that we didn't specifically catch
        elif "unique constraint" in error_message.lower() or "uniqueviolation" in error_message.lower():
            constraint_name = error_message.split('constraint "')[1].split('"')[0] if 'constraint "' in error_message else "unknown"
            return jsonify({"success": False, "data": {"error": f"Duplicate value for {constraint_name}", "trace_id": trace_id}}), 400
        
        else:
            logger.error(f"[TraceID: {trace_id}] Unhandled registration error: {e}")
            return jsonify({"success": False, "data": {"error": "An error occurred during registration", "trace_id": trace_id}}), 500
    except Exception as e:
        db.rollback()
        trace_id = uuid.uuid4().hex[:8]
        
        # Log with detailed formatting including exception type
        logger.error(f"[TraceID: {trace_id}] Registration error: {e} (Type: {type(e).__name__})")
        
        # Add detailed error handling for common issues
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            logger.error(f"[TraceID: {trace_id}] Database connection issue: {e}")
            return jsonify({"success": False, "data": {"error": "Database connection issue, please try again later", "trace_id": trace_id}}), 503
        
        # Import traceback if not already imported at the top
        import traceback
        logger.error(f"[TraceID: {trace_id}] Exception traceback: {traceback.format_exc()}")
        
        return jsonify({"success": False, "data": {"error": "An error occurred during registration", "trace_id": trace_id}}), 500

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
            return jsonify({"success": False, "data": {"error": "Invalid username or password"}}), 401
        
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
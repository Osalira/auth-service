from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging

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
        if 'company_name' not in data or 'business_registration' not in data or 'company_email' not in data:
            return jsonify({"success": False, "data": {"error": "Company accounts require company_name, business_registration, and company_email"}}), 400
    else:
        return jsonify({"success": False, "data": {"error": "Invalid account_type. Must be 'user' or 'company'"}}), 400
    
    db = get_db()
    try:
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
        
        db.commit()
        
        # Return success response with account details
        account_data = {
            "id": account.id,
            "username": account.username,
            "account_type": account.account_type
        }
        
        # Format response as expected by JMeter
        response_data = {
            "success": True,
            "data": {
                "message": "Account created successfully",
                "account": account_data
            }
        }
        
        return jsonify(response_data), 201
        
    except IntegrityError:
        db.rollback()
        return jsonify({"success": False, "data": {"error": "Username already exists"}}), 400
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating account: {str(e)}")
        return jsonify({"success": False, "data": {"error": f"Error creating account: {str(e)}"}}), 500

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
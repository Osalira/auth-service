from flask import jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import create_access_token
from datetime import datetime
from models.user import Account, User, Company, db
import logging

logger = logging.getLogger('auth')
bcrypt = Bcrypt()

def register_user():
    """
    Register a new user in the system.
    
    Expected JSON payload:
    {
        "user_name": "string",
        "password": "string",
        "name": "string",
        "account_type": "user" | "company"  # Optional, defaults to "user"
    }
    """
    try:
        data = request.get_json()
        logger.debug(f"Received registration data: {data}")
        
        # Validate required fields
        required_fields = ['user_name', 'password', 'name']
        if not all(field in data for field in required_fields):
            return jsonify({
                'success': False,
                'data': {
                    'error': 'Missing required fields'
                }
            }), 400
        
        # Validate account_type if provided
        account_type = data.get('account_type', 'user')
        if account_type not in ['user', 'company']:
            return jsonify({
                'success': False,
                'data': {
                    'error': 'Invalid account type. Must be either "user" or "company"'
                }
            }), 400
        
        # Check if username already exists in accounts
        if Account.query.filter_by(username=data['user_name']).first():
            return jsonify({
                'success': False,
                'data': {
                    'error': 'Username already exists'
                }
            }), 409
            
        # Hash password
        hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
        
        try:
            # Create new account based on type
            if account_type == 'company':
                new_account = Company(
                    username=data['user_name'],
                    password=hashed_password,
                    company_name=data['name']
                )
            else:
                new_account = User(
                    username=data['user_name'],
                    password=hashed_password,
                    full_name=data['name']
                )
            
            logger.debug(f"Created new account object: {new_account}")
            
            # Save to database
            db.session.add(new_account)
            db.session.commit()
            
            logger.info(f"Successfully registered new {account_type} account with username: {data['user_name']}")
            
            return jsonify({
                'success': True,
                'data': None
            }), 201
            
        except Exception as e:
            logger.error(f"Database error during account creation: {str(e)}")
            db.session.rollback()
            raise
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'data': {
                'error': str(e)
            }
        }), 500

def login_user():
    """
    Authenticate a user and return a JWT token.
    
    Expected JSON payload:
    {
        "user_name": "string",
        "password": "string"
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        if not all(field in data for field in ['user_name', 'password']):
            return jsonify({
                'success': False,
                'data': {
                    'error': 'Missing username or password'
                }
            }), 400
        
        # Find account by username (supports both User and Company)
        account = Account.query.filter_by(username=data['user_name']).first()
        
        # Verify account exists and password is correct
        if account and bcrypt.check_password_hash(account.password, data['password']):
            # Update last login time
            account.last_login = datetime.utcnow()
            db.session.commit()
            
            # Create access token
            additional_claims = {
                'user_id': account.id,
                'name': account.company_name if isinstance(account, Company) else account.name,
                'account_type': account.account_type
            }
            logger.debug(f"Creating JWT token with claims: {additional_claims}")
            
            access_token = create_access_token(
                identity=account.username,
                additional_claims=additional_claims
            )
            
            logger.debug(f"Generated JWT token: {access_token}")
            
            return jsonify({
                'success': True,
                'data': {
                    'token': access_token
                }
            }), 200
        
        return jsonify({
            'success': False,
            'data': {
                'error': 'Invalid username or password'
            }
        }), 401
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'data': {
                'error': str(e)
            }
        }), 500 
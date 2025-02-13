from flask import jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import create_access_token
from datetime import datetime
from models.user import User, db

bcrypt = Bcrypt()

def register_user():
    """
    Register a new user in the system.
    
    Expected JSON payload:
    {
        "username": "string",
        "password": "string",
        "email": "string"
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'password', 'email']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Check if username already exists
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 409
            
        # Check if email already exists
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 409
        
        # Hash password
        hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
        
        # Create new user
        new_user = User(
            username=data['username'],
            password=hashed_password,
            email=data['email']
        )
        
        # Save to database
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            'message': 'User registered successfully',
            'user': new_user.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

def login_user():
    """
    Authenticate a user and return a JWT token.
    
    Expected JSON payload:
    {
        "username": "string",
        "password": "string"
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        if not all(field in data for field in ['username', 'password']):
            return jsonify({'error': 'Missing username or password'}), 400
        
        # Find user by username
        user = User.query.filter_by(username=data['username']).first()
        
        # Verify user exists and password is correct
        if user and bcrypt.check_password_hash(user.password, data['password']):
            # Update last login time
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            # Create access token
            access_token = create_access_token(
                identity=user.username,
                additional_claims={
                    'user_id': user.id,
                    'email': user.email
                }
            )
            
            return jsonify({
                'access_token': access_token,
                'user': user.to_dict()
            }), 200
        
        return jsonify({'error': 'Invalid username or password'}), 401
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500 
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Account(db.Model):
    """Base model for shared account attributes"""
    
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # Stores hashed password
    account_type = db.Column(db.String(20), nullable=False)  # 'user' or 'company'
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __mapper_args__ = {
        'polymorphic_identity': 'account',
        'polymorphic_on': account_type
    }

    def __init__(self, username, password, account_type):
        self.username = username
        self.password = password
        self.account_type = account_type

    def __repr__(self):
        return f'<Account {self.username}>'

class User(Account):
    """Model for individual user accounts"""
    
    __tablename__ = 'users'

    id = db.Column(db.Integer, db.ForeignKey('accounts.id'), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    account_balance = db.Column(db.Float, default=0.0)

    __mapper_args__ = {
        'polymorphic_identity': 'user',
    }

    def __init__(self, username, password, full_name):
        super().__init__(username=username, password=password, account_type='user')
        self.name = full_name

    def to_dict(self):
        """Convert user object to dictionary (excluding sensitive information)"""
        return {
            'id': self.id,
            'username': self.username,
            'name': self.name,
            'email': self.email,
            'account_type': self.account_type,
            'account_balance': self.account_balance,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

class Company(Account):
    """Model for company accounts"""
    
    __tablename__ = 'companies'

    id = db.Column(db.Integer, db.ForeignKey('accounts.id'), primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    business_registration = db.Column(db.String(50), unique=True, nullable=True)
    company_email = db.Column(db.String(120), unique=True, nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    industry = db.Column(db.String(50), nullable=True)
    total_shares_issued = db.Column(db.BigInteger, default=0)
    shares_available = db.Column(db.BigInteger, default=0)

    __mapper_args__ = {
        'polymorphic_identity': 'company',
    }

    def __init__(self, username, password, company_name):
        super().__init__(username=username, password=password, account_type='company')
        self.company_name = company_name

    def to_dict(self):
        """Convert company object to dictionary (excluding sensitive information)"""
        return {
            'id': self.id,
            'username': self.username,
            'company_name': self.company_name,
            'company_email': self.company_email,
            'business_registration': self.business_registration,
            'industry': self.industry,
            'account_type': self.account_type,
            'total_shares_issued': self.total_shares_issued,
            'shares_available': self.shares_available,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        } 
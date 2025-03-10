from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from database import Base

class Account(Base):
    """User account model"""
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    account_type = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="account", uselist=False, cascade="all, delete-orphan")
    company = relationship("Company", back_populates="account", uselist=False, cascade="all, delete-orphan")
    
    def set_password(self, password):
        """Set password hash using werkzeug"""
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if the password matches"""
        return check_password_hash(self.password, password)
    
    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "account_type": self.account_type,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, ForeignKey("accounts.id"), primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True)
    account_balance = Column(Float, default=0.0)
    
    # Relationship with Account (one-to-one)
    account = relationship("Account", back_populates="user")
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "account_balance": self.account_balance,
            "username": self.account.username if self.account else None
        }


class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, ForeignKey("accounts.id"), primary_key=True)
    company_name = Column(String(120), nullable=False)
    business_registration = Column(String(50), unique=True, nullable=True)
    company_email = Column(String(120), unique=True, nullable=True)
    contact_phone = Column(String(20))
    address = Column(String(255))
    industry = Column(String(50))
    total_shares_issued = Column(BigInteger, default=0)
    shares_available = Column(BigInteger, default=0)
    
    # Relationship with Account (one-to-one)
    account = relationship("Account", back_populates="company")
    
    def to_dict(self):
        return {
            "id": self.id,
            "company_name": self.company_name,
            "business_registration": self.business_registration,
            "company_email": self.company_email,
            "contact_phone": self.contact_phone,
            "address": self.address,
            "industry": self.industry,
            "total_shares_issued": self.total_shares_issued,
            "shares_available": self.shares_available,
            "username": self.account.username if self.account else None
        } 
import os
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from sqlalchemy import inspect

from models.user import db
from routes.auth_routes import auth_bp
from config import Config

def create_app():
    """Initialize and configure the Flask application"""
    app = Flask(__name__)
    
    # Load configuration from the Config class
    app.config.from_object(Config)
    
    # Initialize extensions
    db.init_app(app)
    JWTManager(app)
    Bcrypt(app)
    
    # Initialize Flask-Migrate to manage database migrations
    migrate = Migrate(app, db)
    
    # Register blueprints (grouping routes under /api/auth)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    
    # Initialize database
    with app.app_context():
        # Create all tables with the latest schema
        db.create_all()
    
    @app.route('/health')
    def health_check():
        return {'status': 'healthy'}, 200
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000)

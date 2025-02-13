# Authentication Service

This service handles user authentication for the Day Trading System, including user registration, login, and JWT token generation.

## Features

- User registration with email verification
- User login with JWT token generation
- Password hashing using bcrypt
- Token-based authentication middleware
- PostgreSQL database integration

## Prerequisites

- Python 3.8+
- PostgreSQL
- Virtual Environment (recommended)

## Setup

1. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables (create a .env file):
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/daytrading
JWT_SECRET_KEY=your-secret-key-here
FLASK_SECRET_KEY=your-flask-secret-key
FLASK_DEBUG=True
```

4. Initialize the database:
```bash
flask db init
flask db migrate
flask db upgrade
```

## Running the Service

Start the service:
```bash
python app.py
```

The service will run on `http://localhost:5000`

## API Endpoints

### Authentication

- `POST /api/auth/register` - Register a new user
  ```json
  {
    "username": "string",
    "password": "string",
    "email": "string"
  }
  ```

- `POST /api/auth/login` - Login and get JWT token
  ```json
  {
    "username": "string",
    "password": "string"
  }
  ```

### Health Check

- `GET /health` - Service health check

## Security Notes

- JWT tokens expire after 1 hour
- Passwords are hashed using bcrypt
- All sensitive configuration should be moved to environment variables in production
- CORS settings should be configured based on your deployment setup 
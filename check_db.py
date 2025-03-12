#!/usr/bin/env python
"""
Database connection test utility for auth-service.
This script will attempt to connect to the auth service database and report success or failure.
It works both locally and within the Docker container.
"""

import os
import time
import logging
from sqlalchemy import create_engine, text, MetaData
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_db_url():
    """Get database URL that works in both Docker and locally"""
    # Get the DATABASE_URL from environment, or use a default for local development
    db_url = os.getenv('DATABASE_URL')
    
    if not db_url:
        # Try to build it from individual settings
        user = os.getenv('POSTGRES_USER', 'user')
        password = os.getenv('POSTGRES_PASSWORD', 'password')
        host = os.getenv('DB_HOST', 'localhost')
        port = os.getenv('DB_PORT', '60020')  # Use the exposed port for local development
        db = os.getenv('DB_NAME', 'auth_db')
        
        db_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    # If running locally, replace the Docker hostname with localhost
    if 'auth_db' in db_url or 'db:5432' in db_url:
        local_url = db_url.replace('auth_db:5432', 'localhost:60020').replace('db:5432', 'localhost:60020')
        logger.info(f"Modified database URL for local use: {local_url}")
        return local_url
    
    logger.info(f"Using database URL: {db_url}")
    return db_url

def test_db_connection():
    """Test connection to the database"""
    db_url = get_db_url()
    engine = create_engine(db_url)
    
    # Try to connect with retries
    max_retries = 5
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Test the connection and run a simple query
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                row = result.fetchone()
                if row and row[0] == 1:
                    logger.info("🟢 Database connection successful!")
                    
                    # Check if tables exist
                    metadata = MetaData()
                    metadata.reflect(bind=engine)
                    logger.info(f"Found {len(metadata.tables)} tables in the database")
                    
                    if 'accounts' in metadata.tables:
                        logger.info("✅ Accounts table found")
                        # Check if it has any records
                        count_query = text("SELECT COUNT(*) FROM accounts")
                        count_result = conn.execute(count_query)
                        count = count_result.fetchone()[0]
                        logger.info(f"   There are {count} accounts in the database")
                    else:
                        logger.warning("❌ Accounts table not found")
                    
                    return True
        except Exception as e:
            retry_count += 1
            logger.warning(f"Attempt {retry_count}/{max_retries} failed: {str(e)}")
            if retry_count < max_retries:
                logger.info(f"Retrying in 5 seconds...")
                time.sleep(5)
            else:
                logger.error("❌ Could not connect to database after maximum retries.")
                logger.error(f"Error: {str(e)}")
                return False

if __name__ == "__main__":
    logger.info("Testing database connection...")
    test_db_connection() 
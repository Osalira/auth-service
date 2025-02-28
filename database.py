from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
import time
import logging

# Load environment variables
load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)

# Configure database
DATABASE_URL = os.getenv('DATABASE_URL')

# Add retry logic for database connection
def get_engine_with_retry(url, max_retries=5, retry_interval=2):
    """Attempt to connect to the database with retries"""
    retries = 0
    last_exception = None
    
    while retries < max_retries:
        try:
            logger.info(f"Attempting to connect to database (attempt {retries + 1}/{max_retries})...")
            engine = create_engine(url)
            # Test the connection
            connection = engine.connect()
            connection.close()
            logger.info("Successfully connected to the database")
            return engine
        except Exception as e:
            last_exception = e
            logger.warning(f"Failed to connect to database: {e}")
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
    
    logger.error(f"Failed to connect to database after {max_retries} attempts. Last error: {last_exception}")
    # Re-raise the last exception
    raise last_exception

# Create engine with retry
engine = get_engine_with_retry(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Helper function to get database session
def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close() 
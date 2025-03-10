from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
import os
from dotenv import load_dotenv
import time
import logging
import contextlib
import threading

# Load environment variables
load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)

# Configure database
DATABASE_URL = os.getenv('DATABASE_URL')

# Get connection pool configuration from environment with defaults
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 200))
DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', 500))
DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', 60))
DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', 1800))

# Track session count for debugging
session_counter = 0
session_counter_lock = threading.Lock()

# Add retry logic for database connection
def get_engine_with_retry(url, max_retries=5, retry_interval=2):
    """Attempt to connect to the database with retries"""
    retries = 0
    last_exception = None
    
    while retries < max_retries:
        try:
            logger.info(f"Attempting to connect to database (attempt {retries + 1}/{max_retries})...")
            # Increase connection pool size for high concurrency
            engine = create_engine(
                url,
                pool_size=DB_POOL_SIZE,           # Configurable from environment
                max_overflow=DB_MAX_OVERFLOW,     # Configurable from environment
                pool_timeout=DB_POOL_TIMEOUT,     # Configurable from environment
                pool_recycle=DB_POOL_RECYCLE,     # Configurable from environment
                pool_pre_ping=True,               # Check connection validity before using
                echo_pool=True                    # Log pool events for debugging
            )
            
            # Add event listeners to track connection pool activity
            @event.listens_for(engine, "checkout")
            def checkout(dbapi_conn, conn_record, conn_proxy):
                logger.debug(f"Connection checkout: {conn_record}")
            
            @event.listens_for(engine, "checkin")
            def checkin(dbapi_conn, conn_record):
                logger.debug(f"Connection checkin: {conn_record}")
            
            # Test the connection
            connection = engine.connect()
            connection.close()
            logger.info(f"Successfully connected to the database with pool_size={DB_POOL_SIZE}, max_overflow={DB_MAX_OVERFLOW}")
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

# Create scoped session factory for thread safety
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

# Helper function to get database session
@contextlib.contextmanager
def get_db_context():
    """Provide a transactional scope around a series of operations using context manager"""
    global session_counter
    
    with session_counter_lock:
        session_counter += 1
        current_count = session_counter
    
    logger.debug(f"Creating new database session (#{current_count}, active: {current_count})")
    
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error in database session: {str(e)}")
        raise
    finally:
        session.close()
        with session_counter_lock:
            session_counter -= 1
        logger.debug(f"Closed database session (#{current_count}, remaining: {session_counter})")

# Backward compatibility function
def get_db():
    """Legacy function to get a database session. Prefer using get_db_context() with 'with' statement"""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close() 
#!/usr/bin/env python
"""
Standalone script to add performance indexes to auth-service database.
This doesn't import anything from the application to avoid connection issues.
"""

import os
import time
import logging
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table, Column, Index, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import CreateIndex
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_connection_url():
    """Get database URL with fallbacks for local development"""
    # Try environment variable first
    url = os.getenv('DATABASE_URL')
    
    # If not set in environment, use a hardcoded local development URL
    if not url:
        # Use the port mapping from docker-compose.yml
        url = "postgresql://postgres:osalocal_database@localhost:60020/auth_db"
        logger.info(f"No DATABASE_URL in environment, using local URL: {url}")
    else:
        # If the URL points to a Docker container, rewrite it for local use
        if 'auth_db:5432' in url or 'db:5432' in url:
            url = url.replace('auth_db:5432', 'localhost:60020').replace('db:5432', 'localhost:60020')
            logger.info(f"Rewrote Docker URL for local access: {url}")
        else:
            logger.info(f"Using DATABASE_URL from environment: {url}")
    
    return url

def add_indexes():
    """Add performance indexes to auth-service database tables"""
    logger.info("Starting index creation for performance optimization")
    
    # Get database URL and create engine
    db_url = get_connection_url()
    engine = create_engine(db_url)
    
    # Try to connect with retries
    connected = False
    max_retries = 5
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_retries} - Connecting to database: {db_url}")
            with engine.connect() as conn:
                # Test connection with a simple query
                result = conn.execute(sqlalchemy.text("SELECT 1"))
                if result.scalar() == 1:
                    logger.info("✅ Successfully connected to database")
                    connected = True
                    break
        except Exception as e:
            logger.error(f"❌ Failed to connect (attempt {attempt}/{max_retries}): {str(e)}")
            if attempt < max_retries:
                logger.info(f"Waiting 3 seconds before retry...")
                time.sleep(3)
    
    if not connected:
        logger.error("Could not connect to database after maximum retries. Exiting.")
        return False
    
    try:
        # Create metadata object and reflect database schema
        metadata = MetaData()
        metadata.reflect(bind=engine)
        
        # Check if expected tables exist
        required_tables = ['accounts', 'users', 'companies']
        for table_name in required_tables:
            if table_name not in metadata.tables:
                logger.warning(f"❌ Table '{table_name}' not found in database!")
        
        # Define indexes to create
        indexes_to_create = []
        
        # Account table indexes
        if 'accounts' in metadata.tables:
            accounts = metadata.tables['accounts']
            existing_indexes = [idx.name for idx in accounts.indexes]
            
            # Define additional indexes for accounts table
            account_indexes = [
                {'name': 'idx_account_username_is_active', 'columns': ['username', 'is_active']},
                {'name': 'idx_account_username_account_type', 'columns': ['username', 'account_type']}
            ]
            
            for idx_info in account_indexes:
                if idx_info['name'] not in existing_indexes:
                    # Get column objects from table
                    columns = [accounts.columns[col_name] for col_name in idx_info['columns']]
                    indexes_to_create.append(Index(idx_info['name'], *columns))
        
        # User table indexes
        if 'users' in metadata.tables:
            users = metadata.tables['users']
            existing_indexes = [idx.name for idx in users.indexes]
            
            # Define additional indexes for users table
            user_indexes = [
                {'name': 'idx_user_name', 'columns': ['name']},
                {'name': 'idx_user_email', 'columns': ['email']}
            ]
            
            for idx_info in user_indexes:
                if idx_info['name'] not in existing_indexes:
                    # Get column objects from table
                    columns = [users.columns[col_name] for col_name in idx_info['columns']]
                    indexes_to_create.append(Index(idx_info['name'], *columns))
        
        # Company table indexes
        if 'companies' in metadata.tables:
            companies = metadata.tables['companies']
            existing_indexes = [idx.name for idx in companies.indexes]
            
            # Define additional indexes for companies table
            company_indexes = [
                {'name': 'idx_company_name', 'columns': ['company_name']},
                {'name': 'idx_company_email', 'columns': ['company_email']}
            ]
            
            for idx_info in company_indexes:
                if idx_info['name'] not in existing_indexes:
                    # Get column objects from table
                    try:
                        columns = [companies.columns[col_name] for col_name in idx_info['columns']]
                        indexes_to_create.append(Index(idx_info['name'], *columns))
                    except KeyError as e:
                        logger.warning(f"Column {e} not found in companies table")
        
        # Create all the new indexes
        with engine.begin() as conn:
            for idx in indexes_to_create:
                try:
                    logger.info(f"Creating index: {idx.name}")
                    idx.create(conn)
                    logger.info(f"✅ Successfully created index: {idx.name}")
                except Exception as e:
                    logger.warning(f"❌ Could not create index {idx.name}: {str(e)}")
        
        # Final report
        logger.info(f"✅ Process completed. Attempted to create {len(indexes_to_create)} indexes.")
        
        # List all existing indexes for verification
        inspector = inspect(engine)
        for table_name in required_tables:
            if table_name in metadata.tables:
                all_indexes = inspector.get_indexes(table_name)
                logger.info(f"Table '{table_name}' now has {len(all_indexes)} indexes:")
                for idx in all_indexes:
                    logger.info(f"  - {idx['name']} on columns: {idx['column_names']}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Error creating indexes: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("===== Starting standalone index creation script =====")
    success = add_indexes()
    if success:
        logger.info("✅ Index creation completed successfully!")
    else:
        logger.error("❌ Index creation failed!")
        exit(1) 
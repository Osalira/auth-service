#!/usr/bin/env python
"""
Simple database connection checker for local auth database.
Uses the hardcoded credentials without relying on environment variables.
"""

import sys
import time
import logging
import psycopg2
from sqlalchemy import create_engine, text, inspect, MetaData

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_db_direct():
    """Check database connectivity using psycopg2 directly"""
    logger.info("Checking database connection using psycopg2...")
    
    # Using your local credentials
    conn_params = {
        'host': 'localhost',
        'port': 60020,
        'user': 'postgres',
        'password': 'osalocal_database',
        'dbname': 'auth_db'
    }
    
    try:
        # Try to connect directly with psycopg2
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        
        logger.info(f"✅ Successfully connected to PostgreSQL!")
        logger.info(f"PostgreSQL version: {version[0]}")
        
        # Try to query accounts table
        try:
            cursor.execute("SELECT COUNT(*) FROM accounts;")
            count = cursor.fetchone()[0]
            logger.info(f"✅ Found accounts table with {count} records")
        except Exception as e:
            logger.error(f"❌ Error querying accounts table: {str(e)}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Error connecting to database: {str(e)}")
        return False

def check_db_sqlalchemy():
    """Check database connectivity using SQLAlchemy"""
    logger.info("Checking database connection using SQLAlchemy...")
    
    # Connection URL with your credentials
    db_url = "postgresql://postgres:osalocal_database@localhost:60020/auth_db"
    
    try:
        # Create engine and try to connect
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            # Execute a simple query
            result = conn.execute(text("SELECT 1"))
            if result.scalar() == 1:
                logger.info("✅ Successfully connected with SQLAlchemy")
                
                # Check database schema
                metadata = MetaData()
                metadata.reflect(bind=engine)
                
                tables = list(metadata.tables.keys())
                logger.info(f"✅ Found {len(tables)} tables: {', '.join(tables)}")
                
                # Get information about indexes
                inspector = inspect(engine)
                for table_name in ['accounts', 'users', 'companies']:
                    if table_name in tables:
                        indexes = inspector.get_indexes(table_name)
                        logger.info(f"Table '{table_name}' has {len(indexes)} indexes:")
                        for idx in indexes:
                            logger.info(f"  - {idx['name']} on columns: {idx['column_names']}")
                
                return True
        
    except Exception as e:
        logger.error(f"❌ Error connecting with SQLAlchemy: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("===== Database Connection Check =====")
    
    # Try both connection methods
    direct_result = check_db_direct()
    sqlalchemy_result = check_db_sqlalchemy()
    
    if direct_result and sqlalchemy_result:
        logger.info("✅ All database connection checks passed!")
        sys.exit(0)
    else:
        logger.error("❌ Some database connection checks failed!")
        sys.exit(1) 
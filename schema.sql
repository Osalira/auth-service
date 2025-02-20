-- Drop existing tables in the correct order
DROP TABLE IF EXISTS companies CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;

-- Create the base accounts table
CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    account_type VARCHAR(20) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create the users table with proper inheritance
CREATE TABLE users (
    id INTEGER PRIMARY KEY REFERENCES accounts(id),
    name VARCHAR(120) NOT NULL,
    email VARCHAR(120) UNIQUE,
    account_balance FLOAT DEFAULT 0.0
);

-- Create the companies table with proper inheritance
CREATE TABLE companies (
    id INTEGER PRIMARY KEY REFERENCES accounts(id),
    company_name VARCHAR(120) NOT NULL,
    business_registration VARCHAR(50) UNIQUE,
    company_email VARCHAR(120) UNIQUE,
    contact_phone VARCHAR(20),
    address VARCHAR(255),
    industry VARCHAR(50),
    total_shares_issued BIGINT DEFAULT 0,
    shares_available BIGINT DEFAULT 0
); 
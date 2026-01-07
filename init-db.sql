-- Initialize DepotGate databases
-- This script runs when the PostgreSQL container starts for the first time

-- Create the receipts database (metadata db is created by default via POSTGRES_DB)
CREATE DATABASE depotgate_receipts;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE depotgate_metadata TO depotgate;
GRANT ALL PRIVILEGES ON DATABASE depotgate_receipts TO depotgate;

USE atlas_database;

CREATE TABLE command_requests (
    user_id BIGINT PRIMARY KEY,
    count INT DEFAULT 0
);
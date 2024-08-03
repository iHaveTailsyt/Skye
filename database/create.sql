CREATE atlas_database;

USE atlas_database;

CREATE TABLE premium_users (
    id BIGINT PRIMARY KEY
);

CREATE TABLE command_requests (
    user_id BIGINT PRIMARY KEY,
    count INT DEFAULT 0
);
CREATE atlas_database;

USE atlas_database;

CREATE TABLE allowed_user_ids (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL
);

CREATE TABLE premium_users (
    id BIGINT PRIMARY KEY
);

CREATE TABLE command_requests (
    user_id BIGINT PRIMARY KEY,
    count INT DEFAULT 0,
    command_name VARCHAR(255) NOT NULL,
    command_description TEXT NOT NULL
);
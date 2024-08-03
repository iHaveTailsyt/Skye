CREATE DATABASE atlas_database;

USE atlas_database;

CREATE TABLE allowed_user_ids (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL
);

CREATE TABLE premium_users (
    id BIGINT PRIMARY KEY
);
USE atlas_database;

CREATE TABLE afk_status (
    user_id BIGINT PRIMARY KEY,
    afk_message VARCHAR(255),
    afk_since TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
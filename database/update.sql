USE atlas_database;

CREATE TABLE alert_opts (
    user_id BIGINT NOT NULL,
    alert_type VARCHAR(255) NOT NULL,
    PRIMARY KEY (user_id, alert_type)
);
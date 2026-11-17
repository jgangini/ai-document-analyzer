CREATE TABLE file_groups (
    file_group_id                 NUMBER NOT NULL,
    user_id                       NUMBER NOT NULL,
    group_key                     VARCHAR2(256) NOT NULL,
    group_type                    VARCHAR2(64) DEFAULT 'generic' NOT NULL,
    primary_identifier            VARCHAR2(128),
    secondary_identifier          VARCHAR2(128),
    primary_subject               VARCHAR2(512),
    secondary_subject             VARCHAR2(512),
    current_profile_count         NUMBER DEFAULT 0 NOT NULL,
    current_effective_from        DATE,
    current_effective_to          DATE,
    metadata_json                 CLOB DEFAULT '{}' NOT NULL,
    file_group_updated            TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_group_created            TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_groups_id PRIMARY KEY (file_group_id),
    CONSTRAINT fk_file_groups_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT uq_file_groups_key UNIQUE (user_id, group_key)
);
--

CREATE SEQUENCE file_groups_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_groups_id
    BEFORE INSERT ON file_groups
    FOR EACH ROW
    WHEN (NEW.file_group_id IS NULL)
BEGIN
    :NEW.file_group_id := file_groups_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_groups_updated
BEFORE UPDATE ON file_groups
FOR EACH ROW
BEGIN
    :NEW.file_group_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_groups_primary_identifier
    ON file_groups (user_id, primary_identifier);
--

CREATE INDEX idx_file_groups_secondary_identifier
    ON file_groups (user_id, secondary_identifier);
--

CREATE INDEX idx_file_groups_type
    ON file_groups (user_id, group_type);
--

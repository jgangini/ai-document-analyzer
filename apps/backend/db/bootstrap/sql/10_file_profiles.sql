CREATE TABLE file_profiles (
    file_profile_id               NUMBER NOT NULL,
    user_id                       NUMBER NOT NULL,
    file_group_id                 NUMBER,
    file_id                       NUMBER NOT NULL,
    profile_type                  VARCHAR2(64) DEFAULT 'generic' NOT NULL,
    file_role                     VARCHAR2(64) DEFAULT 'other' NOT NULL,
    primary_identifier            VARCHAR2(128),
    secondary_identifier          VARCHAR2(128),
    primary_subject               VARCHAR2(512),
    secondary_subject             VARCHAR2(512),
    signed_at                     DATE,
    effective_from                DATE,
    effective_to                  DATE,
    is_current                    NUMBER DEFAULT 0 NOT NULL,
    fact_confidence               NUMBER,
    fact_summary                  CLOB DEFAULT '' NOT NULL,
    metadata_json                 CLOB DEFAULT '{}' NOT NULL,
    file_profile_updated          TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_profile_created          TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_profiles_id PRIMARY KEY (file_profile_id),
    CONSTRAINT fk_file_profiles_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_profiles_group FOREIGN KEY (file_group_id)
        REFERENCES file_groups(file_group_id) ON DELETE SET NULL,
    CONSTRAINT fk_file_profiles_file FOREIGN KEY (file_id)
        REFERENCES files(file_id) ON DELETE CASCADE,
    CONSTRAINT uq_file_profiles_file UNIQUE (file_id)
);
--

CREATE SEQUENCE file_profiles_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_file_profiles_id
    BEFORE INSERT ON file_profiles
    FOR EACH ROW
    WHEN (NEW.file_profile_id IS NULL)
BEGIN
    :NEW.file_profile_id := file_profiles_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_file_profiles_updated
BEFORE UPDATE ON file_profiles
FOR EACH ROW
BEGIN
    :NEW.file_profile_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_file_profiles_group_role
    ON file_profiles (file_group_id, file_role, is_current);
--

CREATE INDEX idx_file_profiles_dates
    ON file_profiles (user_id, effective_to, effective_from);
--

CREATE INDEX idx_file_profiles_identifiers
    ON file_profiles (user_id, primary_identifier, secondary_identifier);
--

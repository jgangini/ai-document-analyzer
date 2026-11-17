CREATE TABLE archive_metadata_uploads (
    metadata_upload_id         VARCHAR2(64) NOT NULL,
    user_id                    NUMBER NOT NULL,
    source_file_name           VARCHAR2(500) NOT NULL,
    display_name               VARCHAR2(300),
    description                VARCHAR2(1000),
    access_scope               VARCHAR2(32) DEFAULT 'private' NOT NULL,
    metadata_status            VARCHAR2(32) DEFAULT 'active' NOT NULL,
    column_names_json          CLOB DEFAULT '[]' NOT NULL,
    total_rows                 NUMBER DEFAULT 0 NOT NULL,
    metadata_upload_updated    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    metadata_upload_created    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_archive_metadata_uploads PRIMARY KEY (metadata_upload_id),
    CONSTRAINT ck_archive_metadata_uploads_status
        CHECK (metadata_status IN ('active', 'archived')),
    CONSTRAINT ck_archive_metadata_uploads_access
        CHECK (access_scope IN ('private', 'all')),
    CONSTRAINT fk_archive_metadata_uploads_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);
--

CREATE OR REPLACE TRIGGER trg_archive_metadata_uploads_updated
    BEFORE UPDATE ON archive_metadata_uploads
    FOR EACH ROW
BEGIN
    :NEW.metadata_upload_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_archive_metadata_uploads_user
    ON archive_metadata_uploads (user_id);
--

CREATE INDEX idx_archive_metadata_uploads_status
    ON archive_metadata_uploads (user_id, metadata_status, metadata_upload_updated);
--

CREATE INDEX idx_archive_meta_upload_access
    ON archive_metadata_uploads (access_scope, metadata_status, metadata_upload_updated);
--

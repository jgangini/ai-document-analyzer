CREATE TABLE archive_metadata_upload_rows (
    metadata_upload_row_id         NUMBER NOT NULL,
    metadata_upload_id             VARCHAR2(64) NOT NULL,
    user_id                        NUMBER NOT NULL,
    file_key                       VARCHAR2(256) NOT NULL,
    row_json                       CLOB DEFAULT '{}' NOT NULL,
    search_text                    CLOB DEFAULT '' NOT NULL,
    metadata_upload_row_updated    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    metadata_upload_row_created    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_archive_metadata_upload_rows PRIMARY KEY (metadata_upload_row_id),
    CONSTRAINT fk_archive_metadata_upload_rows_upload FOREIGN KEY (metadata_upload_id)
        REFERENCES archive_metadata_uploads(metadata_upload_id) ON DELETE CASCADE,
    CONSTRAINT fk_archive_metadata_upload_rows_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT uq_archive_metadata_upload_rows UNIQUE (metadata_upload_id, file_key)
);
--

CREATE SEQUENCE archive_metadata_upload_rows_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_archive_metadata_upload_rows_id
    BEFORE INSERT ON archive_metadata_upload_rows
    FOR EACH ROW
    WHEN (NEW.metadata_upload_row_id IS NULL)
BEGIN
    :NEW.metadata_upload_row_id := archive_metadata_upload_rows_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_archive_metadata_upload_rows_updated
    BEFORE UPDATE ON archive_metadata_upload_rows
    FOR EACH ROW
BEGIN
    :NEW.metadata_upload_row_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_archive_metadata_upload_rows_file
    ON archive_metadata_upload_rows (metadata_upload_id, user_id, file_key);
--

CREATE INDEX idx_archive_metadata_upload_rows_text
    ON archive_metadata_upload_rows (search_text)
    INDEXTYPE IS CTXSYS.CONTEXT
    PARAMETERS ('MAINTENANCE AUTO');
--

CREATE TABLE archive_metadata (
    archive_metadata_id         NUMBER NOT NULL,
    user_id                     NUMBER NOT NULL,
    archive_slug                VARCHAR2(256) NOT NULL,
    metadata_upload_id          VARCHAR2(64),
    metadata_source             VARCHAR2(32) DEFAULT 'metadata_csv' NOT NULL,
    metadata_json               CLOB DEFAULT '{}' NOT NULL,
    metadata_search_text        CLOB DEFAULT '' NOT NULL,
    archive_metadata_updated    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    archive_metadata_created    TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_archive_metadata PRIMARY KEY (archive_metadata_id),
    CONSTRAINT fk_archive_metadata_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_archive_metadata_upload FOREIGN KEY (metadata_upload_id)
        REFERENCES archive_metadata_uploads(metadata_upload_id) ON DELETE SET NULL,
    CONSTRAINT uq_archive_metadata_slug UNIQUE (user_id, archive_slug)
);
--

CREATE SEQUENCE archive_metadata_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_archive_metadata_id
    BEFORE INSERT ON archive_metadata
    FOR EACH ROW
    WHEN (NEW.archive_metadata_id IS NULL)
BEGIN
    :NEW.archive_metadata_id := archive_metadata_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_archive_metadata_updated
    BEFORE UPDATE ON archive_metadata
    FOR EACH ROW
BEGIN
    :NEW.archive_metadata_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_archive_metadata_text
    ON archive_metadata (metadata_search_text)
    INDEXTYPE IS CTXSYS.CONTEXT
    PARAMETERS ('MAINTENANCE AUTO');
--

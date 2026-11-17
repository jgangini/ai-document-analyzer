CREATE TABLE files (
    file_id                           NUMBER NOT NULL,
    user_id                           NUMBER NOT NULL,
    file_input_file_name              VARCHAR2(500) NOT NULL,
    file_input_size                   NUMBER DEFAULT 0 NOT NULL,
    file_input_obj_name               VARCHAR2(1000) DEFAULT '' NOT NULL,
    file_output_obj_name              VARCHAR2(4000) DEFAULT 'pending/object' NOT NULL,
    archive_slug                      VARCHAR2(256),
    file_code                         VARCHAR2(64),
    file_code_source                  VARCHAR2(32) DEFAULT 'none' NOT NULL,
    access_scope                      VARCHAR2(32) DEFAULT 'private' NOT NULL,
    file_page_count                   NUMBER DEFAULT 0 NOT NULL,
    file_version                      NUMBER DEFAULT 1 NOT NULL,
    file_state                        NUMBER DEFAULT 1 NOT NULL,
    file_updated                      TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    file_created                      TIMESTAMP(6) DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_file_id PRIMARY KEY (file_id),
    CONSTRAINT fk_files_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);
--

CREATE SEQUENCE file_id_seq START WITH 1 INCREMENT BY 1 NOCACHE;
--

CREATE OR REPLACE TRIGGER trg_files_id
    BEFORE INSERT ON files
    FOR EACH ROW
    WHEN (NEW.file_id IS NULL)
BEGIN
    :NEW.file_id := file_id_seq.NEXTVAL;
END;
/
--

CREATE OR REPLACE TRIGGER trg_files_updated
BEFORE UPDATE ON files
FOR EACH ROW
BEGIN
    :NEW.file_updated := CURRENT_TIMESTAMP;
END;
/
--

CREATE INDEX idx_files_user_file_code
    ON files (user_id, file_code);
--

CREATE INDEX idx_files_user_archive_slug
    ON files (user_id, archive_slug);
